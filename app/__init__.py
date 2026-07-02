import mimetypes
import os
import posixpath
import re
import time
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from .classification import (
    COMIC_ARCHIVE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    READABLE_EXTENSIONS,
    classify_file,
    is_supported_file,
)
from .db import DEFAULT_DB_PATH, add_scan_path, get_connection, init_db
from .scanner import scan_paths


INLINE_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".gif"}
SECTION_MIME_FALLBACK = {
    "PDF": "application/pdf",
    "GIF": "image/gif",
    "EPUB/Books": "application/epub+zip",
}
EPUB_DOCUMENT_EXTENSIONS = {".xhtml", ".html", ".htm"}
EPUB_DOCUMENT_MIME_TYPES = {"application/xhtml+xml", "text/html"}
COMIC_PAGE_EXTENSIONS = INLINE_IMAGE_EXTENSIONS
SUPPORTED_ITEM_EXTENSIONS = tuple(sorted(READABLE_EXTENSIONS))
SUPPORTED_ITEM_PLACEHOLDERS = ", ".join("?" for _ in SUPPORTED_ITEM_EXTENSIONS)
INLINE_IMAGE_DB_EXTENSIONS = tuple(sorted(INLINE_IMAGE_EXTENSIONS))
INLINE_IMAGE_DB_PLACEHOLDERS = ", ".join("?" for _ in INLINE_IMAGE_DB_EXTENSIONS)


def _get_view_mode(raw_value: str) -> str:
    value = (raw_value or "").strip().lower()
    return value if value in {"grid", "list"} else "grid"


def _is_image_ext(ext: str) -> bool:
    return ext.lower() in INLINE_IMAGE_EXTENSIONS


def _get_configured_paths(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT path FROM scan_paths").fetchall()
    conn.close()
    return [row["path"] for row in rows]


def _path_allowed(target: Path, configured_paths: list[str]) -> bool:
    for cp in configured_paths:
        root = Path(cp).resolve()
        try:
            if target == root or target.is_relative_to(root):
                return True
        except ValueError:
            continue
    return False


def _humanize_label(name: str) -> str:
    return re.sub(r"[_\-]+", " ", Path(name).stem).strip().title() or Path(name).name


def _normalize_epub_path(base_dir: str, relative_path: str) -> str:
    target = relative_path.split("#", 1)[0].strip()
    if not target:
        return ""
    normalized = posixpath.normpath(posixpath.join(base_dir, target.lstrip("/")))
    if normalized in {"", "."}:
        return ""
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("EPUB path escapes archive")
    return normalized.lstrip("./")


def _load_epub_book(file_path: Path) -> dict:
    with zipfile.ZipFile(file_path) as archive:
        try:
            container_root = ET.fromstring(archive.read("META-INF/container.xml"))
        except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
            raise ValueError("Invalid EPUB container") from exc

        rootfile = container_root.find(".//{*}rootfile")
        package_path = rootfile.get("full-path") if rootfile is not None else None
        if not package_path:
            raise ValueError("Missing EPUB package file")

        try:
            package_root = ET.fromstring(archive.read(package_path))
        except (KeyError, ET.ParseError) as exc:
            raise ValueError("Invalid EPUB package") from exc

        package_dir = posixpath.dirname(package_path)
        manifest = {}
        for item in package_root.findall(".//{*}manifest/{*}item"):
            item_id = item.get("id")
            href = item.get("href")
            media_type = item.get("media-type", "")
            if item_id and href:
                manifest[item_id] = {
                    "href": _normalize_epub_path(package_dir, href),
                    "media_type": media_type,
                }

        chapters = []
        for itemref in package_root.findall(".//{*}spine/{*}itemref"):
            ref = manifest.get(itemref.get("idref", ""))
            if not ref or ref["media_type"] not in EPUB_DOCUMENT_MIME_TYPES:
                continue
            chapters.append(
                {
                    "href": ref["href"],
                    "label": _humanize_label(ref["href"]),
                }
            )

        if not chapters:
            raise ValueError("EPUB has no readable chapters")

        return {"chapters": chapters}


def _rewrite_epub_html(file_path: Path, html: str, current_href: str) -> str:
    base_dir = posixpath.dirname(current_href)
    pattern = re.compile(
        r"(?P<attr>\b(?:src|href)\s*=\s*)(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        value = match.group("value")
        if not value or value.startswith(("#", "data:", "http://", "https://", "mailto:", "tel:", "javascript:")):
            return match.group(0)

        raw_target, _, fragment = value.partition("#")
        try:
            resolved = _normalize_epub_path(base_dir, raw_target)
        except ValueError:
            return match.group(0)
        if not resolved:
            return match.group(0)

        ext = PurePosixPath(resolved).suffix.lower()
        if ext in EPUB_DOCUMENT_EXTENSIONS:
            rewritten = url_for("read_epub_document", path=str(file_path), href=resolved)
            if fragment:
                rewritten = f"{rewritten}#{fragment}"
        else:
            rewritten = url_for("read_epub_asset", path=str(file_path), asset=resolved)
        return f"{attr}{quote}{rewritten}{quote}"

    return pattern.sub(replace, html)


def _get_comic_pages(file_path: Path) -> list[str]:
    with zipfile.ZipFile(file_path) as archive:
        pages = [
            name
            for name in archive.namelist()
            if not name.endswith("/")
            and PurePosixPath(name).suffix.lower() in COMIC_PAGE_EXTENSIONS
            and not PurePosixPath(name).name.startswith(".")
        ]
    return sorted(pages, key=str.lower)


def _build_item_payload(file_path: Path) -> dict:
    return {
        "id": None,
        "file_name": file_path.name,
        "path": str(file_path),
        "section": classify_file(str(file_path)),
        "extension": file_path.suffix.lower(),
        "size_bytes": file_path.stat().st_size,
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = Path(os.environ.get("APP_DB_PATH", DEFAULT_DB_PATH))

    with app.app_context():
        init_db(app.config["DB_PATH"])
        seed_paths = os.environ.get("APP_SCAN_PATHS", "").strip()
        if seed_paths:
            for path in [p.strip() for p in seed_paths.split(",") if p.strip()]:
                add_scan_path(path, app.config["DB_PATH"])

    def resolve_allowed_target(raw_path: str, *, expect_file: bool = False, expect_dir: bool = False) -> tuple[Path, list[str]]:
        if not raw_path:
            abort(400)

        configured = _get_configured_paths(app.config["DB_PATH"])
        if not configured:
            abort(403)

        try:
            target = Path(raw_path).resolve(strict=True)
        except (OSError, RuntimeError):
            abort(404)

        if not _path_allowed(target, configured):
            abort(403)
        if expect_file and not target.is_file():
            abort(404)
        if expect_dir and not target.is_dir():
            abort(404)
        return target, configured

    def get_item_with_file(item_id: int) -> tuple[dict, Path]:
        conn = get_connection(app.config["DB_PATH"])
        item_row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        if not item_row:
            abort(404)

        file_path, _ = resolve_allowed_target(item_row["path"], expect_file=True)
        item = dict(item_row)
        item["path"] = str(file_path)
        item["extension"] = item.get("extension") or file_path.suffix.lower()
        item["size_bytes"] = item.get("size_bytes") or file_path.stat().st_size
        item["file_mtime_ns"] = item.get("file_mtime_ns") or file_path.stat().st_mtime_ns
        return item, file_path

    def build_refresh_url() -> str:
        route_args = dict(request.view_args or {})
        query_args = request.args.to_dict(flat=True)
        query_args["refresh"] = "1"
        return url_for(request.endpoint, **route_args, **query_args)

    def with_cache_token(target_url: str, file_path: Path, *, force_refresh: bool = False) -> str:
        separator = "&" if "?" in target_url else "?"
        token = str(file_path.stat().st_mtime_ns)
        if force_refresh:
            token = f"{token}-{time.time_ns()}"
        return f"{target_url}{separator}v={token}"

    def build_image_navigation(item: dict, file_path: Path) -> dict | None:
        if not _is_image_ext((item.get("extension") or file_path.suffix).lower()):
            return None

        view_mode = _get_view_mode(request.args.get("view", "grid"))
        from_dir = request.args.get("from_dir", "").strip()
        if item.get("id") is None:
            target_dir = file_path.parent
            if from_dir:
                try:
                    candidate_dir, _ = resolve_allowed_target(from_dir, expect_dir=True)
                    target_dir = candidate_dir
                except HTTPException:
                    target_dir = file_path.parent

            files = [
                entry
                for entry in sorted(target_dir.iterdir(), key=lambda p: p.name.lower())
                if entry.is_file()
                and not entry.name.startswith(".")
                and _is_image_ext(entry.suffix.lower())
            ]
            current_path = file_path.resolve()
            if not files:
                return None

            current_index = next(
                (index for index, entry in enumerate(files) if entry.resolve() == current_path),
                None,
            )
            if current_index is None:
                return None

            previous_url = None
            next_url = None
            if current_index > 0:
                previous_url = url_for(
                    "read_file",
                    path=str(files[current_index - 1]),
                    from_dir=str(target_dir),
                    view=view_mode,
                )
            if current_index + 1 < len(files):
                next_url = url_for(
                    "read_file",
                    path=str(files[current_index + 1]),
                    from_dir=str(target_dir),
                    view=view_mode,
                )
            return {"previous_url": previous_url, "next_url": next_url}

        section = request.args.get("section", "").strip() or item.get("section")
        conn = get_connection(app.config["DB_PATH"])
        rows = conn.execute(
            f"""
            SELECT id
            FROM items
            WHERE section = ?
              AND lower(COALESCE(extension, '')) IN ({INLINE_IMAGE_DB_PLACEHOLDERS})
            ORDER BY file_name
            """,
            (section, *INLINE_IMAGE_DB_EXTENSIONS),
        ).fetchall()
        conn.close()
        if not rows:
            return None

        ids = [row["id"] for row in rows]
        try:
            current_index = ids.index(item["id"])
        except ValueError:
            return None

        previous_url = None
        next_url = None
        if current_index > 0:
            previous_url = url_for(
                "item_detail",
                item_id=ids[current_index - 1],
                section=section,
                view=view_mode,
            )
        if current_index + 1 < len(ids):
            next_url = url_for(
                "item_detail",
                item_id=ids[current_index + 1],
                section=section,
                view=view_mode,
            )
        return {"previous_url": previous_url, "next_url": next_url}

    def render_reader(item: dict, file_path: Path, inline_url: str, download_url: str):
        ext = (item.get("extension") or file_path.suffix).lower()
        reader_kind = "unsupported"
        comic_pages: list[dict] = []
        epub = None

        if _is_image_ext(ext):
            reader_kind = "image"
        elif item["section"] == "PDF":
            reader_kind = "pdf"
        elif ext in COMIC_ARCHIVE_EXTENSIONS:
            try:
                comic_pages = [
                    {
                        "label": f"Página {index}",
                        "url": url_for("read_archive_image", path=str(file_path), entry=entry),
                    }
                    for index, entry in enumerate(_get_comic_pages(file_path), start=1)
                ]
            except (zipfile.BadZipFile, OSError):
                comic_pages = []
            if comic_pages:
                reader_kind = "comic"
        elif item["section"] == "EPUB/Books":
            try:
                book = _load_epub_book(file_path)
            except ValueError:
                book = None
            if book:
                chapter_count = len(book["chapters"])
                chapter_index = request.args.get("chapter", default=0, type=int)
                chapter_index = min(max(chapter_index, 0), chapter_count - 1)
                current = book["chapters"][chapter_index]
                epub = {
                    "chapters": [
                        {
                            **chapter,
                            "url": (
                                url_for("read_file", path=str(file_path), chapter=index)
                                if item["id"] is None
                                else url_for("item_detail", item_id=item["id"], chapter=index)
                            ),
                        }
                        for index, chapter in enumerate(book["chapters"])
                    ],
                    "current_index": chapter_index,
                    "current_label": current["label"],
                    "document_url": url_for("read_epub_document", path=str(file_path), href=current["href"]),
                    "previous_url": (
                        url_for("read_file", path=str(file_path), chapter=chapter_index - 1)
                        if item["id"] is None and chapter_index > 0
                        else url_for("item_detail", item_id=item["id"], chapter=chapter_index - 1)
                        if item["id"] is not None and chapter_index > 0
                        else None
                    ),
                    "next_url": (
                        url_for("read_file", path=str(file_path), chapter=chapter_index + 1)
                        if item["id"] is None and chapter_index + 1 < chapter_count
                        else url_for("item_detail", item_id=item["id"], chapter=chapter_index + 1)
                        if item["id"] is not None and chapter_index + 1 < chapter_count
                        else None
                    ),
                }
                reader_kind = "epub"

        return render_template(
            "item.html",
            item=item,
            is_image=_is_image_ext(ext),
            inline_url=inline_url,
            download_url=download_url,
            reader_kind=reader_kind,
            comic_pages=comic_pages,
            epub=epub,
            image_navigation=build_image_navigation(item, file_path),
            refresh_url=build_refresh_url(),
        )

    @app.get("/")
    def library():
        conn = get_connection(app.config["DB_PATH"])
        paths = conn.execute("SELECT id, path FROM scan_paths ORDER BY path").fetchall()
        sections = conn.execute(
            f"""
            SELECT section, COUNT(*) AS item_count
            FROM items
            WHERE lower(COALESCE(extension, '')) IN ({SUPPORTED_ITEM_PLACEHOLDERS})
            GROUP BY section
            ORDER BY section
            """,
            SUPPORTED_ITEM_EXTENSIONS,
        ).fetchall()

        active_section = request.args.get("section", "").strip()
        view_mode = _get_view_mode(request.args.get("view", "grid"))
        items = []
        if active_section:
            items = conn.execute(
                f"""
                SELECT id, file_name, path, section, extension
                FROM items
                WHERE section = ?
                  AND lower(COALESCE(extension, '')) IN ({SUPPORTED_ITEM_PLACEHOLDERS})
                ORDER BY file_name
                LIMIT 300
                """,
                (active_section, *SUPPORTED_ITEM_EXTENSIONS),
            ).fetchall()
        conn.close()
        return render_template(
            "index.html",
            paths=paths,
            sections=sections,
            items=items,
            active_section=active_section,
            view_mode=view_mode,
        )

    @app.post("/paths")
    def add_path():
        path = request.form.get("path", "").strip()
        if path:
            add_scan_path(path, app.config["DB_PATH"])
        return redirect(url_for("library"))

    @app.post("/paths/remove")
    def remove_path():
        path = request.form.get("path", "").strip()
        if path:
            conn = get_connection(app.config["DB_PATH"])
            conn.execute("DELETE FROM scan_paths WHERE path = ?", (path,))
            conn.commit()
            conn.close()
        return redirect(url_for("library"))

    @app.post("/scan")
    def scan():
        configured = _get_configured_paths(app.config["DB_PATH"])
        scan_paths(app.config["DB_PATH"], configured)
        return redirect(url_for("library"))

    @app.get("/browse")
    def browse():
        browse_path_str = request.args.get("path", "").strip()
        view_mode = _get_view_mode(request.args.get("view", "grid"))
        configured = _get_configured_paths(app.config["DB_PATH"])

        if not browse_path_str:
            return render_template(
                "browse.html",
                browse_path="",
                parent_path=None,
                dirs=[],
                files=[],
                configured_paths=configured,
                breadcrumbs=[],
                view_mode=view_mode,
            )

        target, _ = resolve_allowed_target(browse_path_str, expect_dir=True)

        dirs = []
        files = []
        try:
            entries = sorted(
                target.iterdir(),
                key=lambda e: (e.is_file(), e.name.lower()),
            )
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    try:
                        child_count = sum(
                            1 for c in entry.iterdir() if not c.name.startswith(".")
                        )
                    except PermissionError:
                        child_count = 0
                    dirs.append(
                        {"name": entry.name, "path": str(entry), "count": child_count}
                    )
                elif entry.is_file() and is_supported_file(str(entry)):
                    ext = entry.suffix.lower()
                    files.append(
                        {
                            "name": entry.name,
                            "path": str(entry),
                            "section": classify_file(str(entry)),
                            "extension": ext,
                            "is_image": _is_image_ext(ext),
                            "size": entry.stat().st_size,
                        }
                    )
        except PermissionError:
            abort(403)

        breadcrumbs = []
        for cp in configured:
            root_path = Path(cp).resolve()
            try:
                if target == root_path or target.is_relative_to(root_path):
                    parts = []
                    p = target
                    while True:
                        parts.append({"name": p.name, "path": str(p)})
                        if p == root_path:
                            break
                        p = p.parent
                    breadcrumbs = list(reversed(parts))
                    break
            except ValueError:
                continue

        parent = target.parent
        parent_path = str(parent) if _path_allowed(parent, configured) else None

        return render_template(
            "browse.html",
            browse_path=str(target),
            parent_path=parent_path,
            dirs=dirs,
            files=files,
            configured_paths=configured,
            breadcrumbs=breadcrumbs,
            view_mode=view_mode,
        )

    @app.get("/read")
    def read_file():
        file_path, _ = resolve_allowed_target(request.args.get("path", "").strip(), expect_file=True)
        if not is_supported_file(str(file_path)):
            abort(404)
        item = _build_item_payload(file_path)
        force_refresh = request.args.get("refresh") == "1"
        return render_reader(
            item,
            file_path,
            inline_url=with_cache_token(
                url_for("file_serve", path=str(file_path)),
                file_path,
                force_refresh=force_refresh,
            ),
            download_url=url_for("file_serve", path=str(file_path), dl=1),
        )

    @app.get("/file-serve")
    def file_serve():
        file_path, _ = resolve_allowed_target(request.args.get("path", "").strip(), expect_file=True)
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        as_download = request.args.get("dl") == "1"
        return send_file(
            file_path,
            mimetype=mime_type,
            as_attachment=as_download,
            download_name=file_path.name,
        )

    @app.get("/read/epub-document")
    def read_epub_document():
        file_path, _ = resolve_allowed_target(request.args.get("path", "").strip(), expect_file=True)
        if file_path.suffix.lower() != ".epub":
            abort(404)

        try:
            book = _load_epub_book(file_path)
        except ValueError:
            abort(415)

        href = request.args.get("href", "").strip()
        if not href:
            href = book["chapters"][0]["href"]
        try:
            href = _normalize_epub_path("", href)
        except ValueError:
            abort(404)
        if PurePosixPath(href).suffix.lower() not in EPUB_DOCUMENT_EXTENSIONS:
            abort(404)

        try:
            with zipfile.ZipFile(file_path) as archive:
                html = archive.read(href).decode("utf-8", errors="replace")
        except (KeyError, OSError, zipfile.BadZipFile):
            abort(404)

        return Response(_rewrite_epub_html(file_path, html, href), mimetype="text/html")

    @app.get("/read/epub-asset")
    def read_epub_asset():
        file_path, _ = resolve_allowed_target(request.args.get("path", "").strip(), expect_file=True)
        if file_path.suffix.lower() != ".epub":
            abort(404)

        asset = request.args.get("asset", "").strip()
        if not asset:
            abort(400)
        try:
            asset = _normalize_epub_path("", asset)
        except ValueError:
            abort(404)

        try:
            with zipfile.ZipFile(file_path) as archive:
                payload = archive.read(asset)
        except (KeyError, OSError, zipfile.BadZipFile):
            abort(404)

        mime_type = mimetypes.guess_type(asset)[0] or "application/octet-stream"
        return Response(payload, mimetype=mime_type)

    @app.get("/read/archive-image")
    def read_archive_image():
        file_path, _ = resolve_allowed_target(request.args.get("path", "").strip(), expect_file=True)
        if file_path.suffix.lower() not in COMIC_ARCHIVE_EXTENSIONS:
            abort(404)

        entry = request.args.get("entry", "").strip()
        if not entry:
            abort(400)
        entry_path = PurePosixPath(entry)
        if entry_path.suffix.lower() not in COMIC_PAGE_EXTENSIONS or entry_path.name.startswith("."):
            abort(404)

        try:
            with zipfile.ZipFile(file_path) as archive:
                payload = archive.read(entry)
        except (KeyError, OSError, zipfile.BadZipFile):
            abort(404)

        mime_type = mimetypes.guess_type(entry)[0] or "application/octet-stream"
        return Response(payload, mimetype=mime_type)

    @app.get("/items/<int:item_id>")
    def item_detail(item_id: int):
        item, file_path = get_item_with_file(item_id)
        force_refresh = request.args.get("refresh") == "1"
        return render_reader(
            item,
            file_path,
            inline_url=with_cache_token(
                url_for("view_item", item_id=item_id),
                file_path,
                force_refresh=force_refresh,
            ),
            download_url=url_for("download_item", item_id=item_id),
        )

    @app.get("/items/<int:item_id>/view")
    def view_item(item_id: int):
        item, file_path = get_item_with_file(item_id)
        mime_type = mimetypes.guess_type(str(file_path))[0] or SECTION_MIME_FALLBACK.get(
            item["section"], "application/octet-stream"
        )
        return send_file(
            file_path,
            mimetype=mime_type,
            as_attachment=False,
            download_name=item["file_name"],
        )

    @app.get("/items/<int:item_id>/download")
    def download_item(item_id: int):
        item, file_path = get_item_with_file(item_id)
        return send_file(file_path, as_attachment=True, download_name=item["file_name"])

    return app
