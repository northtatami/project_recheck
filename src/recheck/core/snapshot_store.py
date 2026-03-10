from __future__ import annotations

import json
import shutil
from pathlib import Path

from recheck.core.file_scanner import scan_folder
from recheck.core.models import ProjectConfig, SnapshotFileRecord, SnapshotManifest, SnapshotRecord
from recheck.utils.path_utils import timestamp_id, utc_now_iso


class SnapshotStore:
    def __init__(self) -> None:
        pass

    def _index_file(self, project: ProjectConfig) -> Path:
        return Path(project.snapshot_dir) / "index.json"

    def _snapshot_folder(self, project: ProjectConfig, snapshot_id: str) -> Path:
        return Path(project.snapshot_dir) / snapshot_id

    def _load_index(self, project: ProjectConfig) -> list[SnapshotRecord]:
        index_path = self._index_file(project)
        if not index_path.exists():
            return []
        with index_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return [SnapshotRecord.from_dict(item) for item in payload]

    def _save_index(self, project: ProjectConfig, records: list[SnapshotRecord]) -> None:
        index_path = self._index_file(project)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("w", encoding="utf-8") as handle:
            json.dump([record.to_dict() for record in records], handle, ensure_ascii=False, indent=2)

    def list_snapshots(self, project: ProjectConfig) -> list[SnapshotRecord]:
        records = self._load_index(project)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records

    def save_snapshot(self, project: ProjectConfig, name: str | None = None) -> SnapshotRecord:
        snapshot_id = timestamp_id("s")
        created_at = utc_now_iso()
        snapshot_name = name.strip() if name and name.strip() else snapshot_id

        snapshot_root = self._snapshot_folder(project, snapshot_id)
        files_dir = snapshot_root / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        scanned_files = scan_folder(project.root_folder, project.exclude_rules)
        manifest_files: list[SnapshotFileRecord] = []
        for scanned in scanned_files:
            source = Path(scanned.absolute_path)
            target = files_dir / scanned.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            manifest_files.append(
                SnapshotFileRecord(
                    relative_path=scanned.relative_path,
                    file_name=scanned.file_name,
                    size=scanned.size,
                    modified_time=scanned.modified_time,
                )
            )

        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            name=snapshot_name,
            created_at=created_at,
            files_dir=str(files_dir),
            files=manifest_files,
        )
        manifest_path = snapshot_root / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, ensure_ascii=False, indent=2)

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            name=snapshot_name,
            created_at=created_at,
            source_folder=project.root_folder,
            file_count=len(manifest_files),
            manifest_path=str(manifest_path),
            files_dir=str(files_dir),
        )
        records = self._load_index(project)
        records.append(record)
        self._save_index(project, records)
        return record

    def load_manifest(self, project: ProjectConfig, snapshot_id: str) -> SnapshotManifest:
        for record in self._load_index(project):
            if record.snapshot_id != snapshot_id:
                continue
            manifest_path = Path(record.manifest_path)
            if not manifest_path.exists():
                raise FileNotFoundError(f"Snapshot manifest does not exist: {manifest_path}")
            with manifest_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return SnapshotManifest.from_dict(payload)
        raise KeyError(f"Snapshot not found: {snapshot_id}")

    def get_snapshot(self, project: ProjectConfig, snapshot_id: str) -> SnapshotRecord | None:
        for record in self._load_index(project):
            if record.snapshot_id == snapshot_id:
                return record
        return None
