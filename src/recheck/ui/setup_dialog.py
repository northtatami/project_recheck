from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SetupDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Initial Setup",
        initial_values: dict[str, str] | None = None,
        tr=None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr or (lambda key, **kwargs: key)
        self._title = title
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(600, 240)

        values = initial_values or {}
        default_root = values.get("root_folder") or str(Path.home())
        default_snapshot = values.get("snapshot_dir") or str(Path.home() / "AppData" / "Local" / "ReCheck" / "snapshots")

        layout = QVBoxLayout(self)
        self.helper = QLabel()
        self.helper.setWordWrap(True)
        layout.addWidget(self.helper)

        form = QFormLayout()
        layout.addLayout(form)
        self.form = form

        self.project_name = QLineEdit(values.get("name", ""))
        form.addRow("", self.project_name)

        self.root_folder = QLineEdit(default_root)
        form.addRow("", self._with_browse(self.root_folder, self._browse_root))

        self.snapshot_dir = QLineEdit(default_snapshot)
        form.addRow("", self._with_browse(self.snapshot_dir, self._browse_snapshot))

        self.exclude_rules = QLineEdit(values.get("exclude_rules", ""))
        self.exclude_rules.setPlaceholderText("*.tmp, *.bak, __pycache__")
        form.addRow("", self.exclude_rules)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_checked)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._retranslate()

    def _with_browse(self, line_edit: QLineEdit, callback) -> QWidget:
        wrapper = QWidget(self)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit, 1)
        browse = QPushButton(self._tr("dialog.setup.browse"))
        browse.clicked.connect(callback)
        row.addWidget(browse)
        return wrapper

    def _browse_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._tr("dialog.setup.root_folder"), self.root_folder.text())
        if selected:
            self.root_folder.setText(selected)

    def _browse_snapshot(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self._tr("dialog.setup.snapshot_dir"),
            self.snapshot_dir.text(),
        )
        if selected:
            self.snapshot_dir.setText(selected)

    def _accept_checked(self) -> None:
        if not self.project_name.text().strip():
            QMessageBox.warning(self, self._tr("dialog.validation"), self._tr("dialog.validation.project_required"))
            return
        if not self.root_folder.text().strip():
            QMessageBox.warning(self, self._tr("dialog.validation"), self._tr("dialog.validation.root_required"))
            return
        if not self.snapshot_dir.text().strip():
            QMessageBox.warning(self, self._tr("dialog.validation"), self._tr("dialog.validation.snapshot_required"))
            return
        if not Path(self.root_folder.text().strip()).exists():
            QMessageBox.warning(self, self._tr("dialog.validation"), self._tr("dialog.validation.root_missing"))
            return
        self.accept()

    def values(self) -> dict[str, object]:
        exclude_rules = [item.strip() for item in self.exclude_rules.text().split(",") if item.strip()]
        return {
            "name": self.project_name.text().strip(),
            "root_folder": self.root_folder.text().strip(),
            "snapshot_dir": self.snapshot_dir.text().strip(),
            "exclude_rules": exclude_rules,
        }

    def _retranslate(self) -> None:
        self.setWindowTitle(self._title)
        self.helper.setText(self._tr("dialog.setup.helper"))
        self.form.setWidget(0, QFormLayout.ItemRole.LabelRole, QLabel(self._tr("dialog.setup.project_name")))
        self.form.setWidget(1, QFormLayout.ItemRole.LabelRole, QLabel(self._tr("dialog.setup.root_folder")))
        self.form.setWidget(2, QFormLayout.ItemRole.LabelRole, QLabel(self._tr("dialog.setup.snapshot_dir")))
        self.form.setWidget(3, QFormLayout.ItemRole.LabelRole, QLabel(self._tr("dialog.setup.exclude")))
