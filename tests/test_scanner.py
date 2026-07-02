import tempfile
import unittest
from pathlib import Path

from app.db import get_connection, init_db
from app.scanner import scan_paths


class ScannerTests(unittest.TestCase):
    def test_scan_indexes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "library.db"
            content_dir = tmp_path / "content"
            content_dir.mkdir()

            (content_dir / "one.pdf").write_bytes(b"%PDF")
            (content_dir / "two.gif").write_bytes(b"GIF89a")
            (content_dir / "three.xyz").write_text("x", encoding="utf-8")

            init_db(db_path)

            first_count = scan_paths(db_path, [str(content_dir)])
            second_count = scan_paths(db_path, [str(content_dir)])

            self.assertEqual(first_count, 3)
            self.assertEqual(second_count, 3)

            conn = get_connection(db_path)
            total = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
            sections = {
                row["section"]: row["count"]
                for row in conn.execute(
                    "SELECT section, COUNT(*) AS count FROM items GROUP BY section"
                ).fetchall()
            }
            conn.close()

            self.assertEqual(total, 3)
            self.assertEqual(sections["PDF"], 1)
            self.assertEqual(sections["GIF"], 1)
            self.assertEqual(sections["Unknown/Other"], 1)


if __name__ == "__main__":
    unittest.main()
