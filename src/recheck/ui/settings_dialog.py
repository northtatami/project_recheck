from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from recheck.core.models import AppSettings
from recheck.utils.filetype_utils import normalize_extensions


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, *, settings: AppSettings, tr) -> None:
        super().__init__(parent)
        self._tr = tr
        self.setWindowTitle(self._tr("settings.dialog.title"))
        self.resize(520, 260)
        self.setModal(True)

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.language_combo = QComboBox()
        self.language_combo.addItem(self._tr("language.ja"), "ja")
        self.language_combo.addItem(self._tr("language.en"), "en")
        idx = max(0, self.language_combo.findData(settings.language))
        self.language_combo.setCurrentIndex(idx)
        form.addRow(self._tr("settings.language"), self.language_combo)

        self.max_generations = QSpinBox()
        self.max_generations.setRange(1, 9999)
        self.max_generations.setValue(int(settings.preview_cache_max_generations))
        form.addRow(self._tr("settings.cache_generations"), self.max_generations)

        self.max_size_gb = QDoubleSpinBox()
        self.max_size_gb.setRange(0.1, 1024.0)
        self.max_size_gb.setDecimals(1)
        self.max_size_gb.setSingleStep(0.5)
        self.max_size_gb.setValue(float(settings.preview_cache_max_total_size_gb))
        form.addRow(self._tr("settings.cache_size_gb"), self.max_size_gb)

        self.extensions = QLineEdit(",".join(settings.preview_cache_target_extensions))
        form.addRow(self._tr("settings.cache_exts"), self.extensions)

        hint = QLabel(self._tr("settings.cache_exts.help"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        root.addLayout(actions)

    def build_settings(self, base: AppSettings) -> AppSettings:
        base.language = str(self.language_combo.currentData())
        base.preview_cache_max_generations = int(self.max_generations.value())
        base.preview_cache_max_total_size_gb = float(self.max_size_gb.value())
        base.preview_cache_target_extensions = normalize_extensions(self.extensions.text().split(","))
        return base
