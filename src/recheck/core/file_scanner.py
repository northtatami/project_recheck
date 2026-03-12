from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import datetime
import os
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


def _record_skip(skipped_paths: list[str] | None, path: str) -> None:
    if skipped_paths is not None:
        skipped_paths.append(path)


def scan_folder(
    root_folder: str,
    exclude_patterns: list[str] | None = None,
    skipped_paths: list[str] | None = None,
) -> list[ScannedFile]:
    # skipped_paths: optional list to record paths skipped due to access errors.
    root = Path(root_folder)
    patterns = exclude_patterns or []
    if not root.exists():
        raise FileNotFoundError(f"Root folder does not exist: {root_folder}")
    if not root.is_dir():
        raise NotADirectoryError(f"Root folder is not a directory: {root_folder}")

    results: list[ScannedFile] = []
    root_str = str(root)

    def scan_dir(current: Path) -> None:
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            scan_dir(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        relative_path = normalize_relpath(str(Path(entry.path).relative_to(root)))
                        if is_excluded(relative_path, patterns):
                            continue
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except PermissionError:
                            _record_skip(skipped_paths, entry.path)
                            continue
                        except OSError as exc:
                            if getattr(exc, "winerror", None) in {5, 32, 1314, 1920}:
                                _record_skip(skipped_paths, entry.path)
                                continue
                            raise
                        results.append(
                            ScannedFile(
                                relative_path=relative_path,
                                file_name=entry.name,
                                size=stat.st_size,
                                modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                                absolute_path=entry.path,
                            )
                        )
                    except PermissionError:
                        _record_skip(skipped_paths, entry.path)
                        continue
                    except OSError as exc:
                        if getattr(exc, "winerror", None) in {5, 32, 1314, 1920}:
                            _record_skip(skipped_paths, entry.path)
                            continue
                        raise
        except PermissionError:
            _record_skip(skipped_paths, str(current))
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in {5, 32, 1314, 1920}:
                _record_skip(skipped_paths, str(current))
                return
            raise

    scan_dir(Path(root_str))
    return results
