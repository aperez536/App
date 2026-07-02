import mimetypes
import os
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from .classification import classify_file
from .db import DEFAULT_DB_PATH, add_scan_path, get_connection, init_db
from .scanner import scan_paths


# Extensions that can be rendered inline as images
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif",
    ".avif", ".gif", ".svg", ".ico",
}

SECTION_MIME_FALLBACK = {
    "PDF": "application/pdf",
    "GIF": "image/gif",
    "EPUB/Books": "application/epub+zip",
}


def _is_image_ext(ext: str) -> bool:
    return ext.lower() in IMAGE_EXTENSIONS


def _get_configured_paths(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT path FROM scan_paths").fetchall()
    conn.close()
    return [row["path"] for row in rows]


def _path_allowed(target: Path, configured_paths: list[str]) -> bool:
    """Return True only when *target* is within one of the configured scan paths.

    Both paths are fully resolved (symlinks expanded, ``..`` removed) before
    comparison so that path-traversal tricks cannot bypass the allowlist.
    Requires Python 3.9+ for ``Path.is_relative_to``.
    """
    for cp in configured_paths:
        root = Path(cp).resolve()
        try:
            if target == root or target.is_relative_to(root):
                return True
        except ValueError:
            # Raised on Windows when paths are on different drives
            continue
    return False


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = Path(os.environ.get("APP_DB_PATH", DEFAULT_DB_PATH))

    with app.app_context():
        init_db(app.config["DB_PATH"])
        seed_paths = os.environ.get("APP_SCAN_PATHS", "").strip()
        if seed_paths:
            for path in [p.strip() for p in seed_paths.split(",") if p.strip()]:
                add_scan_path(path, app.config["DB_PATH"])

    @app.get("/")
    def library():
        conn = get_connection(app.config["DB_PATH"])
        paths = conn.execute("SELECT id, path FROM scan_paths ORDER BY path").fetchall()
        sections = conn.execute(
            """
            SELECT section, COUNT(*) AS item_count
            FROM items
            GROUP BY section
            ORDER BY section
            """
        ).fetchall()

        active_section = request.args.get("section", "").strip()
        items = []
        if active_section:
            items = conn.execute(
                """
                SELECT id, file_name, path, section, extension
                FROM items
                WHERE section = ?
                ORDER BY file_name
                LIMIT 300
                """,
                (active_section,),
            ).fetchall()
        conn.close()
        return render_template(
            "index.html",
            paths=paths,
            sections=sections,
            items=items,
            active_section=active_section,
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
            )

        try:
            target = Path(browse_path_str).resolve(strict=True)
        except (OSError, RuntimeError):
            abort(404)

        if not _path_allowed(target, configured):
            abort(403)

        if not target.is_dir():
            abort(404)

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
                elif entry.is_file():
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

        # Build breadcrumbs
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
        )

    @app.get("/file-serve")
    def file_serve():
        file_path_str = request.args.get("path", "").strip()
        if not file_path_str:
            abort(400)

        configured = _get_configured_paths(app.config["DB_PATH"])
        if not configured:
            abort(403)

        # Resolve symlinks and normalise the path before the allowlist check
        try:
            file_path = Path(file_path_str).resolve(strict=True)
        except (OSError, RuntimeError):
            abort(404)

        if not _path_allowed(file_path, configured):
            abort(403)

        if not file_path.is_file():
            abort(404)

        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        as_download = request.args.get("dl") == "1"
        return send_file(
            file_path,
            mimetype=mime_type,
            as_attachment=as_download,
            download_name=file_path.name,
        )

    @app.get("/items/<int:item_id>")
    def item_detail(item_id: int):
        conn = get_connection(app.config["DB_PATH"])
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        if not item:
            abort(404)
        is_image = _is_image_ext(item["extension"] or "")
        return render_template("item.html", item=item, is_image=is_image)

    @app.get("/items/<int:item_id>/view")
    def view_item(item_id: int):
        conn = get_connection(app.config["DB_PATH"])
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        if not item:
            abort(404)

        file_path = Path(item["path"])
        if not file_path.exists() or not file_path.is_file():
            abort(404)

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
        conn = get_connection(app.config["DB_PATH"])
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        if not item:
            abort(404)

        file_path = Path(item["path"])
        if not file_path.exists() or not file_path.is_file():
            abort(404)

        return send_file(file_path, as_attachment=True, download_name=item["file_name"])

    return app
