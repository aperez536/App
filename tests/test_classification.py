import unittest

from app.classification import classify_file, is_supported_file


class ClassificationTests(unittest.TestCase):
    def test_known_sections(self):
        self.assertEqual(classify_file("a.pdf"), "PDF")
        self.assertEqual(classify_file("a.GIF"), "GIF")
        self.assertEqual(classify_file("a.jpeg"), "Images")
        self.assertEqual(classify_file("a.cbz"), "Comics/Archives")
        self.assertEqual(classify_file("a.epub"), "EPUB/Books")

    def test_unknown_fallback(self):
        self.assertEqual(classify_file("a.unknownext"), "Unknown/Other")

    def test_supported_files(self):
        self.assertTrue(is_supported_file("a.pdf"))
        self.assertTrue(is_supported_file("a.cbz"))
        self.assertTrue(is_supported_file("a.epub"))
        self.assertFalse(is_supported_file("a.txt"))


if __name__ == "__main__":
    unittest.main()
