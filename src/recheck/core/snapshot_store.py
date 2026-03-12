from __future__ import annotations

import json
from pathlib import Path

from recheck.core.file_scanner import scan_folder
from recheck.core.models import (
    AppSettings,
    ProjectConfig,
    SnapshotFileRecord,
    SnapshotManifest,
    SnapshotRecord,
)
from recheck.core.preview_cache import PreviewCacheStore
from recheck.utils.path_utils import normalize_relpath, timestamp_id, utc_now_iso


class SnapshotStore:
    def __init__(self, preview_cache_store: PreviewCacheStore) -> None:
        self.preview_cache_store = preview_cache_store

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

    def save_snapshot(
        self,
        project: ProjectConfig,
        *,
        settings: AppSettings,
        name: str | None = None,
        source_folder: str | None = None,
        scan_warnings: list[str] | None = None,
    ) -> SnapshotRecord:
        # scan_warnings: populated with paths skipped during snapshot scanning.
        snapshot_id = timestamp_id("s")
        created_at = utc_now_iso()
        snapshot_name = name.strip() if name and name.strip() else snapshot_id
        snapshot_source = str(Path(source_folder or project.root_folder))

        snapshot_root = self._snapshot_folder(project, snapshot_id)
        snapshot_root.mkdir(parents=True, exist_ok=True)

        scanned_files = scan_folder(snapshot_source, project.exclude_rules, skipped_paths=scan_warnings)
        generation = self.preview_cache_store.cache_snapshot_files(
            snapshot_id=snapshot_id,
            source_folder=snapshot_source,
            scanned_files=scanned_files,
            settings=settings,
        )
        cached_hashes = generation.file_hashes

        manifest_files: list[SnapshotFileRecord] = []
        for scanned in scanned_files:
            rel = normalize_relpath(scanned.relative_path)
            manifest_files.append(
                SnapshotFileRecord(
                    relative_path=rel,
                    file_name=scanned.file_name,
                    size=scanned.size,
                    modified_time=scanned.modified_time,
                    snapshot_created_time=created_at,
                    cached_blob_hash=cached_hashes.get(rel),
                )
            )

        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            name=snapshot_name,
            created_at=created_at,
            source_folder=snapshot_source,
            preview_generation_id=generation.generation_id,
            files=manifest_files,
        )
        manifest_path = snapshot_root / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest.to_dict(), handle, ensure_ascii=False, indent=2)

        record = SnapshotRecord(
            snapshot_id=snapshot_id,
            name=snapshot_name,
            created_at=created_at,
            source_folder=snapshot_source,
            file_count=len(manifest_files),
            manifest_path=str(manifest_path),
            preview_generation_id=generation.generation_id,
            cached_file_count=len(cached_hashes),
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
            manifest = SnapshotManifest.from_dict(payload)
            if not manifest.source_folder:
                manifest.source_folder = record.source_folder
            if not manifest.preview_generation_id:
                manifest.preview_generation_id = record.preview_generation_id
            return manifest
        raise KeyError(f"Snapshot not found: {snapshot_id}")

    def get_snapshot(self, project: ProjectConfig, snapshot_id: str) -> SnapshotRecord | None:
        for record in self._load_index(project):
            if record.snapshot_id == snapshot_id:
                return record
        return None

    def resolve_preview_path(self, manifest: SnapshotManifest, relative_path: str) -> str | None:
        normalized_rel = normalize_relpath(relative_path)
        cached = self.preview_cache_store.resolve_cached_file(manifest.preview_generation_id, normalized_rel)
        if cached:
            return cached

        source_candidate = Path(manifest.source_folder) / normalized_rel
        if source_candidate.exists():
            return str(source_candidate)
        return None
