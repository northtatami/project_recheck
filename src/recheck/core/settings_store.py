from __future__ import annotations

import json
import locale
from pathlib import Path

from recheck.core.models import AppSettings
from recheck.utils.filetype_utils import PREVIEW_CACHE_DEFAULT_EXTENSIONS, normalize_extensions
from recheck.utils.path_utils import utc_now_iso


def _detect_default_language() -> str:
    preferred = "ja"
    try:
        loc = locale.getdefaultlocale()[0]
    except Exception:
        loc = None
    if loc and loc.lower().startswith("en"):
        preferred = "en"
    elif loc and loc.lower().startswith("ja"):
        preferred = "ja"
    return preferred


class AppSettingsStore:
    def __init__(self, app_data_dir: Path) -> None:
        self.app_data_dir = Path(app_data_dir)
        self.settings_path = self.app_data_dir / "settings.json"
        self.app_data_dir.mkdir(parents=True, exist_ok=True)

    def default_settings(self) -> AppSettings:
        return AppSettings(
            language=_detect_default_language(),
            preview_cache_max_generations=5,
            preview_cache_max_total_size_gb=10.0,
            preview_cache_target_extensions=list(PREVIEW_CACHE_DEFAULT_EXTENSIONS),
            preview_pane_visible=True,
        )

    def load(self) -> AppSettings:
        if not self.settings_path.exists():
            settings = self.default_settings()
            self.save(settings)
            return settings

        with self.settings_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        settings = AppSettings.from_dict(payload)
        if not settings.preview_cache_target_extensions:
            settings.preview_cache_target_extensions = list(PREVIEW_CACHE_DEFAULT_EXTENSIONS)
        settings.preview_cache_target_extensions = normalize_extensions(settings.preview_cache_target_extensions)
        if settings.language not in {"ja", "en"}:
            settings.language = "ja"
        settings.preview_pane_visible = bool(settings.preview_pane_visible)
        return settings

    def save(self, settings: AppSettings) -> AppSettings:
        now = utc_now_iso()
        if not settings.created_at:
            settings.created_at = now
        settings.updated_at = now
        settings.preview_cache_target_extensions = normalize_extensions(settings.preview_cache_target_extensions)
        with self.settings_path.open("w", encoding="utf-8") as handle:
            json.dump(settings.to_dict(), handle, ensure_ascii=False, indent=2)
        return settings
