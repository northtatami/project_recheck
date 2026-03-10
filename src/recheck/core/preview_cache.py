from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from recheck.core.file_scanner import ScannedFile
from recheck.core.models import AppSettings, PreviewCacheGeneration
from recheck.utils.filetype_utils import is_preview_cache_target
from recheck.utils.path_utils import normalize_relpath, timestamp_id, utc_now_iso


class PreviewCacheStore:
    def __init__(self, app_data_dir: Path) -> None:
        self.app_data_dir = Path(app_data_dir)
        self.cache_dir = self.app_data_dir / "preview_cache"
        self.generations_dir = self.cache_dir / "generations"
        self.blobs_dir = self.cache_dir / "blobs"
        self.generations_dir.mkdir(parents=True, exist_ok=True)
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    def _generation_file(self, generation_id: str) -> Path:
        return self.generations_dir / f"{generation_id}.json"

    def _blob_path(self, hash_value: str) -> Path:
        return self.blobs_dir / hash_value[:2] / hash_value

    def _hash_file(self, file_path: str) -> str:
        hasher = hashlib.sha256()
        with Path(file_path).open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    def _save_generation(self, generation: PreviewCacheGeneration) -> None:
        path = self._generation_file(generation.generation_id)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(generation.to_dict(), handle, ensure_ascii=False, indent=2)

    def _load_generation(self, generation_file: Path) -> PreviewCacheGeneration:
        with generation_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return PreviewCacheGeneration.from_dict(payload)

    def list_generations(self) -> list[PreviewCacheGeneration]:
        generations: list[PreviewCacheGeneration] = []
        for path in self.generations_dir.glob("*.json"):
            try:
                generations.append(self._load_generation(path))
            except Exception:
                continue
        generations.sort(key=lambda item: item.created_at, reverse=True)
        return generations

    def cache_snapshot_files(
        self,
        *,
        snapshot_id: str,
        source_folder: str,
        scanned_files: list[ScannedFile],
        settings: AppSettings,
    ) -> PreviewCacheGeneration:
        generation_id = timestamp_id("g")
        created_at = utc_now_iso()
        file_hashes: dict[str, str] = {}

        for scanned in scanned_files:
            if not is_preview_cache_target(scanned.absolute_path, settings.preview_cache_target_extensions):
                continue
            hash_value = self._hash_file(scanned.absolute_path)
            blob_path = self._blob_path(hash_value)
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            if not blob_path.exists():
                shutil.copy2(scanned.absolute_path, blob_path)
            file_hashes[normalize_relpath(scanned.relative_path)] = hash_value

        generation = PreviewCacheGeneration(
            generation_id=generation_id,
            snapshot_id=snapshot_id,
            created_at=created_at,
            source_folder=str(Path(source_folder)),
            file_hashes=file_hashes,
        )
        self._save_generation(generation)
        self.prune(settings)
        return generation

    def resolve_cached_file(self, generation_id: str | None, relative_path: str) -> str | None:
        if not generation_id:
            return None
        generation_file = self._generation_file(generation_id)
        if not generation_file.exists():
            return None
        generation = self._load_generation(generation_file)
        hash_value = generation.file_hashes.get(normalize_relpath(relative_path))
        if not hash_value:
            return None
        blob = self._blob_path(hash_value)
        if not blob.exists():
            return None
        return str(blob)

    def prune(self, settings: AppSettings) -> None:
        generations = self.list_generations()
        keep = list(generations)
        drop: list[PreviewCacheGeneration] = []

        max_generations = max(1, int(settings.preview_cache_max_generations))
        if len(keep) > max_generations:
            drop.extend(keep[max_generations:])
            keep = keep[:max_generations]

        def referenced_hashes(items: list[PreviewCacheGeneration]) -> set[str]:
            refs: set[str] = set()
            for generation in items:
                refs.update(generation.file_hashes.values())
            return refs

        def total_size_bytes(hashes: set[str]) -> int:
            size = 0
            for hash_value in hashes:
                path = self._blob_path(hash_value)
                if path.exists():
                    size += path.stat().st_size
            return size

        refs = referenced_hashes(keep)
        max_bytes = settings.preview_cache_max_total_size_bytes
        while keep and total_size_bytes(refs) > max_bytes:
            oldest = keep.pop()
            drop.append(oldest)
            refs = referenced_hashes(keep)

        for generation in drop:
            path = self._generation_file(generation.generation_id)
            if path.exists():
                path.unlink()

        refs = referenced_hashes(keep)
        for first_level in self.blobs_dir.glob("*"):
            if not first_level.is_dir():
                continue
            for blob in first_level.glob("*"):
                if blob.name not in refs:
                    blob.unlink(missing_ok=True)
            if not any(first_level.iterdir()):
                first_level.rmdir()

    def cache_size_bytes(self) -> int:
        size = 0
        for blob in self.blobs_dir.rglob("*"):
            if blob.is_file():
                size += blob.stat().st_size
        return size
