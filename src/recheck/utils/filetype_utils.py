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
PREVIEW_CACHE_DEFAULT_EXTENSIONS = sorted(IMAGE_EXTS | TEXT_EXTS | PDF_EXTS | AUDIO_EXTS)


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


def normalize_extensions(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        ext = raw.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext in seen:
            continue
        seen.add(ext)
        normalized.append(ext)
    return normalized


def is_preview_cache_target(path: str, target_extensions: list[str]) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in set(normalize_extensions(target_extensions))
