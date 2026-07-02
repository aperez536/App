import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("library.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_paths (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            section TEXT NOT NULL,
            extension TEXT,
            size_bytes INTEGER,
            discovered_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def add_scan_path(path: str, db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO scan_paths(path, created_at) VALUES(?, ?)",
        (path, now_iso()),
    )
    conn.commit()
    conn.close()
