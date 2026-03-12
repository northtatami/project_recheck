from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ProjectConfig:
    project_id: str
    name: str
    root_folder: str
    snapshot_dir: str
    exclude_rules: list[str] = field(default_factory=list)
    last_base_snapshot_id: str | None = None
    last_compare_snapshot_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectConfig":
        return cls(
            project_id=data["project_id"],
            name=data["name"],
            root_folder=data["root_folder"],
            snapshot_dir=data["snapshot_dir"],
            exclude_rules=data.get("exclude_rules", []),
            last_base_snapshot_id=data.get("last_base_snapshot_id"),
            last_compare_snapshot_id=data.get("last_compare_snapshot_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class AppSettings:
    language: str = "ja"
    ui_text_size: str = "medium"
    preview_cache_max_generations: int = 5
    preview_cache_max_total_size_gb: float = 10.0
    preview_cache_target_extensions: list[str] = field(default_factory=list)
    preview_pane_visible: bool = True
    quick_guide_completed: bool = False
    created_at: str = ""
    updated_at: str = ""

    @property
    def preview_cache_max_total_size_bytes(self) -> int:
        size_gb = max(0.1, float(self.preview_cache_max_total_size_gb))
        return int(size_gb * 1024 * 1024 * 1024)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        return cls(
            language=str(data.get("language", "ja")),
            ui_text_size=str(data.get("ui_text_size", "medium")),
            preview_cache_max_generations=int(data.get("preview_cache_max_generations", 5)),
            preview_cache_max_total_size_gb=float(data.get("preview_cache_max_total_size_gb", 10.0)),
            preview_cache_target_extensions=list(data.get("preview_cache_target_extensions", [])),
            preview_pane_visible=bool(data.get("preview_pane_visible", True)),
            quick_guide_completed=bool(data.get("quick_guide_completed", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass
class SnapshotFileRecord:
    relative_path: str
    file_name: str
    size: int
    modified_time: str
    snapshot_created_time: str = ""
    cached_blob_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotFileRecord":
        return cls(
            relative_path=data["relative_path"],
            file_name=data["file_name"],
            size=int(data["size"]),
            modified_time=data["modified_time"],
            snapshot_created_time=str(data.get("snapshot_created_time", "")),
            cached_blob_hash=data.get("cached_blob_hash"),
        )


@dataclass
class SnapshotRecord:
    snapshot_id: str
    name: str
    created_at: str
    source_folder: str
    file_count: int
    manifest_path: str
    preview_generation_id: str | None = None
    cached_file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotRecord":
        return cls(
            snapshot_id=data["snapshot_id"],
            name=data["name"],
            created_at=data["created_at"],
            source_folder=data["source_folder"],
            file_count=int(data["file_count"]),
            manifest_path=data["manifest_path"],
            preview_generation_id=data.get("preview_generation_id"),
            cached_file_count=int(data.get("cached_file_count", 0)),
        )


@dataclass
class SnapshotManifest:
    snapshot_id: str
    name: str
    created_at: str
    source_folder: str
    preview_generation_id: str | None
    files: list[SnapshotFileRecord]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [item.to_dict() for item in self.files]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotManifest":
        return cls(
            snapshot_id=data["snapshot_id"],
            name=data["name"],
            created_at=data["created_at"],
            source_folder=str(data.get("source_folder", "")),
            preview_generation_id=data.get("preview_generation_id"),
            files=[SnapshotFileRecord.from_dict(item) for item in data.get("files", [])],
        )


@dataclass
class DiffEntry:
    status: str
    file_name: str
    relative_path: str
    base_modified_time: str | None
    compare_modified_time: str | None
    base_size: int | None
    compare_size: int | None
    base_file_path: str | None
    compare_file_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DiffEntry":
        return cls(
            status=data["status"],
            file_name=data["file_name"],
            relative_path=data["relative_path"],
            base_modified_time=data.get("base_modified_time"),
            compare_modified_time=data.get("compare_modified_time"),
            base_size=data.get("base_size"),
            compare_size=data.get("compare_size"),
            base_file_path=data.get("base_file_path"),
            compare_file_path=data.get("compare_file_path"),
        )


@dataclass
class CompareLogRecord:
    compare_id: str
    created_at: str
    base_snapshot_id: str
    compare_snapshot_id: str
    scope_mode: str
    scope_folders: list[str]
    counts: dict[str, int]
    entries: list[DiffEntry]
    log_path: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompareLogRecord":
        return cls(
            compare_id=data["compare_id"],
            created_at=data["created_at"],
            base_snapshot_id=data["base_snapshot_id"],
            compare_snapshot_id=data["compare_snapshot_id"],
            scope_mode=data["scope_mode"],
            scope_folders=list(data.get("scope_folders", [])),
            counts=dict(data.get("counts", {})),
            entries=[DiffEntry.from_dict(item) for item in data.get("entries", [])],
            log_path=data["log_path"],
        )


@dataclass
class PreviewCacheGeneration:
    generation_id: str
    snapshot_id: str
    created_at: str
    source_folder: str
    file_hashes: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreviewCacheGeneration":
        return cls(
            generation_id=str(data["generation_id"]),
            snapshot_id=str(data["snapshot_id"]),
            created_at=str(data["created_at"]),
            source_folder=str(data.get("source_folder", "")),
            file_hashes=dict(data.get("file_hashes", {})),
        )
