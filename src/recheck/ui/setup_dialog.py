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
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(600, 240)

        values = initial_values or {}
        default_root = values.get("root_folder") or str(Path.home())
        default_snapshot = values.get("snapshot_dir") or str(Path.home() / "AppData" / "Local" / "ReCheck" / "snapshots")

        layout = QVBoxLayout(self)
        helper = QLabel("Configure project settings for Re:Check v0.1.")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        form = QFormLayout()
        layout.addLayout(form)

        self.project_name = QLineEdit(values.get("name", ""))
        form.addRow("Project Name", self.project_name)

        self.root_folder = QLineEdit(default_root)
        form.addRow("Root Folder", self._with_browse(self.root_folder, self._browse_root))

        self.snapshot_dir = QLineEdit(default_snapshot)
        form.addRow("Snapshot Directory", self._with_browse(self.snapshot_dir, self._browse_snapshot))

        self.initial_scope = QLineEdit(values.get("initial_scope_folders", ""))
        self.initial_scope.setPlaceholderText("folderA, folderB")
        form.addRow("Initial Compare Folders", self.initial_scope)

        self.exclude_rules = QLineEdit(values.get("exclude_rules", ""))
        self.exclude_rules.setPlaceholderText("*.tmp, *.bak, __pycache__")
        form.addRow("Exclude Rules", self.exclude_rules)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_checked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _with_browse(self, line_edit: QLineEdit, callback) -> QWidget:
        wrapper = QWidget(self)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line_edit, 1)
        browse = QPushButton("Browse")
        browse.clicked.connect(callback)
        row.addWidget(browse)
        return wrapper

    def _browse_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Root Folder", self.root_folder.text())
        if selected:
            self.root_folder.setText(selected)

    def _browse_snapshot(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Snapshot Directory", self.snapshot_dir.text())
        if selected:
            self.snapshot_dir.setText(selected)

    def _accept_checked(self) -> None:
        if not self.project_name.text().strip():
            QMessageBox.warning(self, "Validation", "Project name is required.")
            return
        if not self.root_folder.text().strip():
            QMessageBox.warning(self, "Validation", "Root folder is required.")
            return
        if not self.snapshot_dir.text().strip():
            QMessageBox.warning(self, "Validation", "Snapshot directory is required.")
            return
        if not Path(self.root_folder.text().strip()).exists():
            QMessageBox.warning(self, "Validation", "Root folder does not exist.")
            return
        self.accept()

    def values(self) -> dict[str, object]:
        scope_folders = [item.strip() for item in self.initial_scope.text().split(",") if item.strip()]
        exclude_rules = [item.strip() for item in self.exclude_rules.text().split(",") if item.strip()]
        return {
            "name": self.project_name.text().strip(),
            "root_folder": self.root_folder.text().strip(),
            "snapshot_dir": self.snapshot_dir.text().strip(),
            "initial_scope_folders": scope_folders,
            "exclude_rules": exclude_rules,
        }
