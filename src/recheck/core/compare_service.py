from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from recheck.core.models import CompareLogRecord, DiffEntry, ProjectConfig, SnapshotFileRecord, SnapshotManifest
from recheck.utils.path_utils import normalize_relpath, timestamp_id, utc_now_iso

STATUSES = ("added", "removed", "modified", "unchanged")


@dataclass
class CompareResult:
    entries: list[DiffEntry]
    counts: dict[str, int]


def _in_scope(relative_path: str, mode: str, scope_folders: list[str]) -> bool:
    if mode == "whole" or not scope_folders:
        return True
    normalized_path = normalize_relpath(relative_path)
    normalized_scopes = [normalize_relpath(item) for item in scope_folders if item.strip()]
    if mode == "selected" and normalized_scopes:
        normalized_scopes = normalized_scopes[:1]
    for folder in normalized_scopes:
        if normalized_path == folder or normalized_path.startswith(f"{folder}/"):
            return True
    return False


def _status_from_records(base: SnapshotFileRecord | None, compare: SnapshotFileRecord | None) -> str:
    if base is None and compare is not None:
        return "added"
    if base is not None and compare is None:
        return "removed"
    if base is None and compare is None:
        return "unchanged"
    assert base is not None and compare is not None
    if base.size != compare.size or base.modified_time != compare.modified_time:
        return "modified"
    return "unchanged"


def compare_snapshots(
    base: SnapshotManifest,
    compare: SnapshotManifest,
    scope_mode: str = "whole",
    scope_folders: list[str] | None = None,
) -> CompareResult:
    scope_folders = scope_folders or []
    base_map = {item.relative_path: item for item in base.files}
    compare_map = {item.relative_path: item for item in compare.files}

    all_paths = sorted(set(base_map.keys()) | set(compare_map.keys()))
    entries: list[DiffEntry] = []
    counts = {status: 0 for status in STATUSES}

    for rel_path in all_paths:
        if not _in_scope(rel_path, scope_mode, scope_folders):
            continue
        base_item = base_map.get(rel_path)
        compare_item = compare_map.get(rel_path)
        status = _status_from_records(base_item, compare_item)
        counts[status] += 1

        file_name = (compare_item.file_name if compare_item else base_item.file_name) if (base_item or compare_item) else ""
        base_path = str(Path(base.files_dir) / rel_path) if base_item else None
        compare_path = str(Path(compare.files_dir) / rel_path) if compare_item else None

        entries.append(
            DiffEntry(
                status=status,
                file_name=file_name,
                relative_path=rel_path,
                base_modified_time=base_item.modified_time if base_item else None,
                compare_modified_time=compare_item.modified_time if compare_item else None,
                base_size=base_item.size if base_item else None,
                compare_size=compare_item.size if compare_item else None,
                base_file_path=base_path,
                compare_file_path=compare_path,
            )
        )

    return CompareResult(entries=entries, counts=counts)


class CompareLogStore:
    def _compare_dir(self, project: ProjectConfig, project_storage_dir: Path) -> Path:
        compare_dir = project_storage_dir / "compares"
        compare_dir.mkdir(parents=True, exist_ok=True)
        return compare_dir

    def save_compare_log(
        self,
        project: ProjectConfig,
        project_storage_dir: Path,
        base_snapshot_id: str,
        compare_snapshot_id: str,
        scope_mode: str,
        scope_folders: list[str],
        result: CompareResult,
    ) -> CompareLogRecord:
        compare_id = timestamp_id("c")
        created_at = utc_now_iso()
        compare_dir = self._compare_dir(project, project_storage_dir)
        log_path = compare_dir / f"{compare_id}.json"

        record = CompareLogRecord(
            compare_id=compare_id,
            created_at=created_at,
            base_snapshot_id=base_snapshot_id,
            compare_snapshot_id=compare_snapshot_id,
            scope_mode=scope_mode,
            scope_folders=scope_folders,
            counts=result.counts,
            entries=result.entries,
            log_path=str(log_path),
        )
        with log_path.open("w", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
        return record

    def list_compare_logs(self, project_storage_dir: Path) -> list[CompareLogRecord]:
        compare_dir = project_storage_dir / "compares"
        if not compare_dir.exists():
            return []
        records: list[CompareLogRecord] = []
        for path in sorted(compare_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            records.append(CompareLogRecord.from_dict(payload))
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def load_compare_log(self, log_path: str) -> CompareLogRecord:
        with Path(log_path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return CompareLogRecord.from_dict(payload)
