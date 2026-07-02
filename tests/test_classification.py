import unittest

from app.classification import classify_file


class ClassificationTests(unittest.TestCase):
    def test_known_sections(self):
        self.assertEqual(classify_file("a.pdf"), "PDF")
        self.assertEqual(classify_file("a.GIF"), "GIF")
        self.assertEqual(classify_file("a.jpeg"), "Images")
        self.assertEqual(classify_file("a.cbz"), "Comics/Archives")
        self.assertEqual(classify_file("a.epub"), "EPUB/Books")

    def test_unknown_fallback(self):
        self.assertEqual(classify_file("a.unknownext"), "Unknown/Other")


if __name__ == "__main__":
    unittest.main()
