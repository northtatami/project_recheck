from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from recheck.utils.path_utils import normalize_relpath


@dataclass
class ScannedFile:
    relative_path: str
    file_name: str
    size: int
    modified_time: str
    absolute_path: str


def _matches_pattern(rel_path: str, pattern: str) -> bool:
    normalized = normalize_relpath(rel_path)
    name = Path(normalized).name
    return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern)


def is_excluded(rel_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    normalized = normalize_relpath(rel_path)
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern:
            continue
        if _matches_pattern(normalized, pattern):
            return True
    return False


def scan_folder(root_folder: str, exclude_patterns: list[str] | None = None) -> list[ScannedFile]:
    root = Path(root_folder)
    patterns = exclude_patterns or []
    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root_folder}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root folder is not a directory: {root_folder}")

    results: list[ScannedFile] = []
    for absolute_path in root.rglob("*"):
        if absolute_path.is_dir():
            continue
        relative_path = normalize_relpath(str(absolute_path.relative_to(root)))
        if is_excluded(relative_path, patterns):
            continue
        stat = absolute_path.stat()
        results.append(
            ScannedFile(
                relative_path=relative_path,
                file_name=absolute_path.name,
                size=stat.st_size,
                modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                absolute_path=str(absolute_path),
            )
        )
    return results
