import mimetypes
import os
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from .db import DEFAULT_DB_PATH, add_scan_path, get_connection, init_db
from .scanner import scan_paths


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
        paths = conn.execute("SELECT path FROM scan_paths ORDER BY path").fetchall()
        sections = conn.execute(
            """
            SELECT section, COUNT(*) AS item_count
            FROM items
            GROUP BY section
            ORDER BY section
            """
        ).fetchall()

        grouped_items = {}
        for row in sections:
            grouped_items[row["section"]] = conn.execute(
                "SELECT id, file_name, path FROM items WHERE section = ? ORDER BY file_name",
                (row["section"],),
            ).fetchall()
        conn.close()
        return render_template("index.html", paths=paths, sections=sections, grouped_items=grouped_items)

    @app.post("/paths")
    def add_path():
        path = request.form.get("path", "").strip()
        if path:
            add_scan_path(path, app.config["DB_PATH"])
        return redirect(url_for("library"))

    @app.post("/scan")
    def scan():
        conn = get_connection(app.config["DB_PATH"])
        paths = [row["path"] for row in conn.execute("SELECT path FROM scan_paths").fetchall()]
        conn.close()
        scan_paths(app.config["DB_PATH"], paths)
        return redirect(url_for("library"))

    @app.get("/items/<int:item_id>")
    def item_detail(item_id: int):
        conn = get_connection(app.config["DB_PATH"])
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        conn.close()
        if not item:
            abort(404)
        return render_template("item.html", item=item)

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

        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        return send_file(file_path, mimetype=mime_type, as_attachment=False, download_name=item["file_name"])

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
