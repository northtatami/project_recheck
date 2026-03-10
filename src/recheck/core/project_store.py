from __future__ import annotations

import json
import os
from pathlib import Path

from recheck.core.models import ProjectConfig
from recheck.utils.path_utils import safe_slug, timestamp_id, utc_now_iso


class ProjectStore:
    def __init__(self, app_data_dir: str | None = None) -> None:
        if app_data_dir:
            base_dir = Path(app_data_dir)
        else:
            env_override = os.environ.get("RECHECK_DATA_DIR")
            if env_override:
                base_dir = Path(env_override)
            elif os.name == "nt":
                base_dir = Path.home() / "AppData" / "Local" / "ReCheck"
            else:
                base_dir = Path.home() / ".recheck"
        self.app_data_dir = base_dir
        self.projects_dir = self.app_data_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def _project_file(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "project.json"

    def list_projects(self) -> list[ProjectConfig]:
        projects: list[ProjectConfig] = []
        for project_dir in sorted(self.projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            config_path = project_dir / "project.json"
            if not config_path.exists():
                continue
            with config_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            projects.append(ProjectConfig.from_dict(payload))
        projects.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
        return projects

    def load_project(self, project_id: str) -> ProjectConfig:
        config_path = self._project_file(project_id)
        with config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return ProjectConfig.from_dict(payload)

    def save_project(self, project: ProjectConfig) -> ProjectConfig:
        now = utc_now_iso()
        if not project.created_at:
            project.created_at = now
        project.updated_at = now

        project_dir = self._project_dir(project.project_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "compares").mkdir(parents=True, exist_ok=True)

        if not project.snapshot_dir:
            project.snapshot_dir = str(project_dir / "snapshots")
        Path(project.snapshot_dir).mkdir(parents=True, exist_ok=True)

        config_path = self._project_file(project.project_id)
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(project.to_dict(), handle, ensure_ascii=False, indent=2)
        return project

    def create_project(
        self,
        name: str,
        root_folder: str,
        snapshot_dir: str,
        initial_scope_folders: list[str],
        exclude_rules: list[str],
    ) -> ProjectConfig:
        project_id = f"{safe_slug(name)}_{timestamp_id('p')}"
        project = ProjectConfig(
            project_id=project_id,
            name=name.strip(),
            root_folder=str(Path(root_folder)),
            snapshot_dir=str(Path(snapshot_dir)),
            initial_scope_folders=initial_scope_folders,
            exclude_rules=exclude_rules,
        )
        return self.save_project(project)

    def project_storage_dir(self, project_id: str) -> Path:
        path = self._project_dir(project_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def export_project(self, project_id: str, target_json_path: str) -> str:
        project = self.load_project(project_id)
        payload = {
            "project": project.to_dict(),
            "storage_dir": str(self.project_storage_dir(project_id)),
        }
        target = Path(target_json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return str(target)
