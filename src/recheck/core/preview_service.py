from __future__ import annotations

from pathlib import Path


def file_exists(path: str | None) -> bool:
    return bool(path and Path(path).exists())


def read_text_preview(path: str, limit_chars: int = 100000) -> str:
    target = Path(path)
    for encoding in ("utf-8", "utf-8-sig", "cp932", "latin-1"):
        try:
            with target.open("r", encoding=encoding, errors="strict") as handle:
                return handle.read(limit_chars)
        except UnicodeDecodeError:
            continue
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit_chars)
