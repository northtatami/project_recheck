from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
TEXT_EXTS = {
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".xml",
    ".ini",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".html",
    ".htm",
}
PDF_EXTS = {".pdf"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm"}
OFFICE_EXTS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def detect_preview_type(path: str | None) -> str:
    if not path:
        return "none"
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in TEXT_EXTS:
        return "text"
    if suffix in PDF_EXTS:
        return "pdf"
    if suffix in AUDIO_EXTS:
        return "audio"
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in OFFICE_EXTS:
        return "office"
    return "unsupported"
