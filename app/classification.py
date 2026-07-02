from pathlib import Path

SECTION_EXTENSIONS = {
    "PDF": {".pdf"},
    "GIF": {".gif"},
    "Images": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".avif", ".svg", ".ico"},
    "Comics/Archives": {".cbz", ".cbr", ".zip", ".rar", ".rar5", ".7z"},
    "EPUB/Books": {".epub"},
}


def classify_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    for section, exts in SECTION_EXTENSIONS.items():
        if ext in exts:
            return section
    return "Unknown/Other"
