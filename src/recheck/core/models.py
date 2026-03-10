from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ProjectConfig:
    project_id: str
    name: str
    root_folder: str
    snapshot_dir: str
    initial_scope_folders: list[str] = field(default_factory=list)
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
            initial_scope_folders=data.get("initial_scope_folders", []),
            exclude_rules=data.get("exclude_rules", []),
            last_base_snapshot_id=data.get("last_base_snapshot_id"),
            last_compare_snapshot_id=data.get("last_compare_snapshot_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class SnapshotFileRecord:
    relative_path: str
    file_name: str
    size: int
    modified_time: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotFileRecord":
        return cls(
            relative_path=data["relative_path"],
            file_name=data["file_name"],
            size=int(data["size"]),
            modified_time=data["modified_time"],
        )


@dataclass
class SnapshotRecord:
    snapshot_id: str
    name: str
    created_at: str
    source_folder: str
    file_count: int
    manifest_path: str
    files_dir: str

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
            files_dir=data["files_dir"],
        )


@dataclass
class SnapshotManifest:
    snapshot_id: str
    name: str
    created_at: str
    files_dir: str
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
            files_dir=data["files_dir"],
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
