import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.db import add_scan_path
from app.scanner import scan_paths


CONTAINER_XML = """<?xml version='1.0'?>
<container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>
  <rootfiles>
    <rootfile full-path='OEBPS/content.opf' media-type='application/oebps-package+xml'/>
  </rootfiles>
</container>
"""

CONTENT_OPF = """<?xml version='1.0' encoding='utf-8'?>
<package version='3.0' xmlns='http://www.idpf.org/2007/opf' unique-identifier='bookid'>
  <metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>
    <dc:title>Libro de prueba</dc:title>
  </metadata>
  <manifest>
    <item id='chapter-1' href='chapter-1.xhtml' media-type='application/xhtml+xml'/>
  </manifest>
  <spine>
    <itemref idref='chapter-1'/>
  </spine>
</package>
"""

CHAPTER_XHTML = """<?xml version='1.0' encoding='utf-8'?>
<html xmlns='http://www.w3.org/1999/xhtml'>
  <head><title>Capitulo 1</title></head>
  <body><h1>Capitulo 1</h1><p>Contenido EPUB</p></body>
</html>
"""

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


class AppRoutesTests(unittest.TestCase):
    def create_client(self, root: Path):
        db_path = root / 'library.db'
        with patch.dict(os.environ, {'APP_DB_PATH': str(db_path)}, clear=False):
            app = create_app()
        app.config.update(TESTING=True)
        return app.test_client(), db_path

    def test_browse_shows_only_supported_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            library_dir.mkdir()
            (library_dir / 'comic.cbz').write_bytes(b'PK\x03\x04')
            (library_dir / 'notes.txt').write_text('hola', encoding='utf-8')

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)

            response = client.get('/browse', query_string={'path': str(library_dir)})
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('comic.cbz', html)
            self.assertNotIn('notes.txt', html)
            self.assertIn('/read?path=', html)
            self.assertIn(f'from_dir={library_dir}', html)
            self.assertNotIn('target="_blank"', html)

    def test_library_supports_list_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            library_dir.mkdir()
            (library_dir / 'guide.pdf').write_bytes(b'%PDF')

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)
            scan_paths(db_path, [str(library_dir)])

            response = client.get('/', query_string={'section': 'PDF', 'view': 'list'})
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('cards-grid list-view', html)
            self.assertIn('href="/?section=PDF&amp;view=grid"', html)
            self.assertIn('href="/browse?view=list"', html)
            self.assertIn('href="/items/1?section=PDF&amp;view=list"', html)

    def test_browse_supports_list_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            child_dir = library_dir / 'sub'
            library_dir.mkdir()
            child_dir.mkdir()
            (library_dir / 'guide.pdf').write_bytes(b'%PDF')

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)

            response = client.get(
                '/browse',
                query_string={'path': str(library_dir), 'view': 'list'},
            )
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('folders-grid list-view', html)
            self.assertIn('cards-grid list-view', html)
            self.assertIn(f'href="/browse?path={library_dir}/sub&amp;view=list"', html)
            self.assertIn(f'href="/browse?view=list"', html)

    def test_read_epub_inside_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            library_dir.mkdir()
            epub_path = library_dir / 'book.epub'
            with zipfile.ZipFile(epub_path, 'w') as archive:
                archive.writestr('mimetype', 'application/epub+zip')
                archive.writestr('META-INF/container.xml', CONTAINER_XML)
                archive.writestr('OEBPS/content.opf', CONTENT_OPF)
                archive.writestr('OEBPS/chapter-1.xhtml', CHAPTER_XHTML)

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)

            response = client.get('/read', query_string={'path': str(epub_path)})
            html = response.get_data(as_text=True)
            document = client.get(
                '/read/epub-document',
                query_string={'path': str(epub_path), 'href': 'OEBPS/chapter-1.xhtml'},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn('viewer-epub-frame', html)
            self.assertIn('Chapter 1', html)
            self.assertEqual(document.status_code, 200)
            self.assertIn('Contenido EPUB', document.get_data(as_text=True))

    def test_read_comic_inside_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            library_dir.mkdir()
            comic_path = library_dir / 'comic.cbz'
            with zipfile.ZipFile(comic_path, 'w') as archive:
                archive.writestr('001.png', PNG_BYTES)
                archive.writestr('002.png', PNG_BYTES)

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)

            response = client.get('/read', query_string={'path': str(comic_path)})
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('/read/archive-image?path=', html)
            self.assertIn('Página 1', html)
            self.assertIn('Página 2', html)

    def test_read_image_shows_next_and_refresh_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            library_dir = tmp_path / 'library'
            library_dir.mkdir()
            first = library_dir / 'a.png'
            second = library_dir / 'b.gif'
            first.write_bytes(PNG_BYTES)
            second.write_bytes(b'GIF89a')

            client, db_path = self.create_client(tmp_path)
            add_scan_path(str(library_dir), db_path)

            response = client.get(
                '/read',
                query_string={'path': str(first), 'from_dir': str(library_dir), 'view': 'list'},
            )
            html = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 200)
            self.assertIn('Siguiente imagen', html)
            self.assertIn(f'path={second}&amp;from_dir={library_dir}&amp;view=list', html)
            self.assertIn('refresh=1', html)


if __name__ == '__main__':
    unittest.main()
