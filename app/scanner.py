from pathlib import Path

from .classification import classify_file
from .db import get_connection, now_iso


def _iter_files(root: Path):
    if not root.exists() or not root.is_dir():
        return
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def scan_paths(db_path: Path, configured_paths: list[str]) -> int:
    conn = get_connection(db_path)
    scanned = 0
    current_time = now_iso()

    for raw_path in configured_paths:
        root = Path(raw_path).expanduser().resolve()
        for file_path in _iter_files(root) or []:
            scanned += 1
            section = classify_file(str(file_path))
            conn.execute(
                """
                INSERT INTO items(path, file_name, section, extension, size_bytes, discovered_at, last_seen_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    file_name=excluded.file_name,
                    section=excluded.section,
                    extension=excluded.extension,
                    size_bytes=excluded.size_bytes,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    str(file_path),
                    file_path.name,
                    section,
                    file_path.suffix.lower(),
                    file_path.stat().st_size,
                    current_time,
                    current_time,
                ),
            )
    conn.commit()
    conn.close()
    return scanned
