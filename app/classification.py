from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".avif", ".svg", ".ico",
}
COMIC_ARCHIVE_EXTENSIONS = {".cbz", ".zip"}
READABLE_EXTENSIONS = {
    ".pdf",
    ".gif",
    ".epub",
    *IMAGE_EXTENSIONS,
    *COMIC_ARCHIVE_EXTENSIONS,
}

SECTION_EXTENSIONS = {
    "PDF": {".pdf"},
    "GIF": {".gif"},
    "Images": IMAGE_EXTENSIONS,
    "Comics/Archives": {".cbz", ".cbr", ".zip", ".rar", ".rar5", ".7z"},
    "EPUB/Books": {".epub"},
}


def classify_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    for section, exts in SECTION_EXTENSIONS.items():
        if ext in exts:
            return section
    return "Unknown/Other"


def is_supported_file(path: str) -> bool:
    return Path(path).suffix.lower() in READABLE_EXTENSIONS
