from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from recheck import __version__
from recheck.core.compare_service import CompareLogStore, compare_snapshots
from recheck.core.models import CompareLogRecord, DiffEntry, ProjectConfig, SnapshotRecord
from recheck.core.project_store import ProjectStore
from recheck.core.snapshot_store import SnapshotStore
from recheck.ui.history_panel import HistoryPanel
from recheck.ui.preview_widgets import FilePreviewColumn
from recheck.ui.setup_dialog import SetupDialog
from recheck.utils.filetype_utils import detect_preview_type
from recheck.utils.open_external import open_external
from recheck.utils.path_utils import normalize_relpath

STATUS_JA = {
    "added": "Added",
    "removed": "Removed",
    "modified": "Modified",
    "unchanged": "Unchanged",
}


class RecheckMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Re:Check - Diff Review for folders")
        self.resize(1540, 900)

        self.project_store = ProjectStore()
        self.snapshot_store = SnapshotStore()
        self.compare_log_store = CompareLogStore()

        self.current_project: ProjectConfig | None = None
        self.snapshots: list[SnapshotRecord] = []
        self.compare_logs: list[CompareLogRecord] = []
        self.diff_entries: list[DiffEntry] = []
        self.visible_entries: list[DiffEntry] = []
        self.current_entry: DiffEntry | None = None
        self.current_status_filter: str = "all"

        self._build_ui()
        self._apply_style()
        self._load_projects()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(10)
        self.setCentralWidget(central)

        root.addWidget(self._build_header())

        body = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(self._build_scope_pane())
        body.addWidget(self._build_diff_pane())
        body.addWidget(self._build_preview_pane())
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 2)
        body.setStretchFactor(2, 2)
        body.setSizes([280, 520, 560])
        root.addWidget(body, 1)

        self.history_panel = HistoryPanel(self)
        self.history_panel.set_base_requested.connect(self._set_base_from_history)
        self.history_panel.set_compare_requested.connect(self._set_compare_from_history)
        self.history_panel.open_compare_requested.connect(self._open_compare_from_history)
        self.history_panel.close_requested.connect(self._toggle_history_panel)

        self.history_dock = QDockWidget("History", self)
        self.history_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.history_dock.setWidget(self.history_panel)
        self.history_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.history_dock)
        self.history_dock.hide()

        self.statusBar().showMessage("Ready")

        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.activated.connect(self._show_command_palette_stub)

    def _build_header(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setObjectName("headerPanel")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        name = QLabel("Re:Check")
        name.setObjectName("appTitle")
        title_row.addWidget(name)
        subtitle = QLabel("Diff Review for folders")
        subtitle.setObjectName("appSubtitle")
        title_row.addWidget(subtitle)
        title_row.addStretch(1)

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedWidth(36)
        self.settings_button.clicked.connect(self._open_settings_menu)
        title_row.addWidget(self.settings_button)
        layout.addLayout(title_row)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(QLabel("Project"))
        self.project_selector = QComboBox()
        self.project_selector.currentIndexChanged.connect(self._on_project_changed)
        self.project_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        controls.addWidget(self.project_selector, 2)

        self.project_menu_button = QPushButton("...")
        self.project_menu_button.setFixedWidth(36)
        self.project_menu_button.clicked.connect(self._open_project_menu)
        controls.addWidget(self.project_menu_button)

        controls.addSpacing(8)
        controls.addWidget(QLabel("Base"))
        self.base_selector = QComboBox()
        controls.addWidget(self.base_selector, 1)
        controls.addWidget(QLabel("Compare"))
        self.compare_selector = QComboBox()
        controls.addWidget(self.compare_selector, 1)

        self.compare_button = QPushButton("Compare")
        self.compare_button.clicked.connect(self._execute_compare)
        controls.addWidget(self.compare_button)

        self.project_switch_button = QPushButton("Project Switch")
        self.project_switch_button.clicked.connect(self._switch_project_focus)
        controls.addWidget(self.project_switch_button)

        self.snapshot_button = QPushButton("Save Snapshot")
        self.snapshot_button.clicked.connect(self._save_snapshot)
        controls.addWidget(self.snapshot_button)

        self.history_button = QPushButton("History")
        self.history_button.clicked.connect(self._toggle_history_panel)
        controls.addWidget(self.history_button)

        self.date_compare_button = QPushButton("Compare by Date")
        self.date_compare_button.clicked.connect(self._select_snapshots_by_date)
        controls.addWidget(self.date_compare_button)

        self.command_palette_button = QPushButton("Ctrl+K")
        self.command_palette_button.clicked.connect(self._show_command_palette_stub)
        controls.addWidget(self.command_palette_button)

        layout.addLayout(controls)
        return wrapper

    def _build_scope_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("scopePane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Scope")
        title.setObjectName("paneTitle")
        layout.addWidget(title)
        helper = QLabel("Choose where to compare")
        helper.setObjectName("paneHelp")
        layout.addWidget(helper)

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_whole = QRadioButton("Whole")
        self.mode_selected = QRadioButton("Selected")
        self.mode_multiple = QRadioButton("Multiple")
        self.mode_whole.setChecked(True)
        self.mode_group.addButton(self.mode_whole)
        self.mode_group.addButton(self.mode_selected)
        self.mode_group.addButton(self.mode_multiple)
        self.mode_whole.toggled.connect(self._on_scope_mode_changed)
        self.mode_selected.toggled.connect(self._on_scope_mode_changed)
        self.mode_multiple.toggled.connect(self._on_scope_mode_changed)
        mode_row.addWidget(self.mode_whole)
        mode_row.addWidget(self.mode_selected)
        mode_row.addWidget(self.mode_multiple)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.scope_tree = QTreeWidget()
        self.scope_tree.setHeaderLabels(["Folders"])
        self.scope_tree.itemChanged.connect(self._on_scope_item_changed)
        layout.addWidget(self.scope_tree, 1)
        return panel

    def _build_diff_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("diffPane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Diff Results")
        title.setObjectName("paneTitle")
        layout.addWidget(title)
        helper = QLabel("Review what changed")
        helper.setObjectName("paneHelp")
        layout.addWidget(helper)
        self.current_path_label = QLabel("Path: (whole project)")
        layout.addWidget(self.current_path_label)

        cards = QHBoxLayout()
        self.summary_group = QButtonGroup(self)
        self.summary_group.setExclusive(True)
        self.filter_all_button = QPushButton("All 0")
        self.filter_all_button.setCheckable(True)
        self.filter_all_button.setChecked(True)
        self.filter_all_button.clicked.connect(lambda: self._set_status_filter("all"))
        cards.addWidget(self.filter_all_button)

        self.summary_buttons: dict[str, QPushButton] = {}
        for status in ("added", "removed", "modified", "unchanged"):
            button = QPushButton(f"{STATUS_JA[status]} 0")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, s=status: self._set_status_filter(s))
            cards.addWidget(button)
            self.summary_buttons[status] = button
            self.summary_group.addButton(button)
        self.summary_group.addButton(self.filter_all_button)
        layout.addLayout(cards)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by filename or relative path")
        self.search_box.textChanged.connect(self._apply_filters_to_table)
        layout.addWidget(self.search_box)

        self.diff_table = QTableWidget(0, 7)
        self.diff_table.setHorizontalHeaderLabels(
            [
                "Type",
                "File Name",
                "Relative Path",
                "Base Modified",
                "Compare Modified",
                "Base Size",
                "Compare Size",
            ]
        )
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.diff_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.diff_table.setSortingEnabled(True)
        self.diff_table.itemSelectionChanged.connect(self._on_diff_selection_changed)
        layout.addWidget(self.diff_table, 1)
        return panel

    def _build_preview_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("previewPane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Preview")
        title.setObjectName("paneTitle")
        layout.addWidget(title)
        helper = QLabel("Compare Base and Compare side by side")
        helper.setObjectName("paneHelp")
        layout.addWidget(helper)

        self.preview_info = QLabel("File: - | Type: - | Path: -")
        self.preview_info.setWordWrap(True)
        layout.addWidget(self.preview_info)

        sides = QSplitter(Qt.Orientation.Horizontal)
        self.base_preview = FilePreviewColumn("Base")
        self.compare_preview = FilePreviewColumn("Compare")
        sides.addWidget(self.base_preview)
        sides.addWidget(self.compare_preview)
        sides.setSizes([1, 1])
        layout.addWidget(sides, 1)

        action_row = QHBoxLayout()
        self.open_base_button = QPushButton("Open Base")
        self.open_base_button.clicked.connect(self._open_base_file)
        action_row.addWidget(self.open_base_button)
        self.open_compare_button = QPushButton("Open Compare")
        self.open_compare_button.clicked.connect(self._open_compare_file)
        action_row.addWidget(self.open_compare_button)
        self.open_explorer_button = QPushButton("Show in Explorer")
        self.open_explorer_button.clicked.connect(self._open_in_explorer)
        action_row.addWidget(self.open_explorer_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.base_preview.open_button.clicked.connect(lambda: self._open_path(self.base_preview.current_path))
        self.compare_preview.open_button.clicked.connect(lambda: self._open_path(self.compare_preview.current_path))
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { font-family: "Segoe UI"; font-size: 13px; color: #25374a; }
            QFrame#headerPanel, QFrame#scopePane, QFrame#diffPane, QFrame#previewPane {
                background: #f7fafc;
                border: 1px solid #d6e0ea;
                border-radius: 10px;
            }
            QLabel#appTitle { font-size: 21px; font-weight: 700; color: #153954; }
            QLabel#appSubtitle { color: #5f7387; padding-top: 3px; }
            QLabel#paneTitle { font-size: 15px; font-weight: 700; color: #20455f; }
            QLabel#paneHelp { color: #607487; }
            QLabel#historyTitle { font-size: 16px; font-weight: 700; }
            QPushButton {
                background: #e7edf3;
                border: 1px solid #ccdae7;
                border-radius: 8px;
                padding: 6px 10px;
            }
            QPushButton:hover { background: #dfe8f1; }
            QPushButton:checked { background: #d3e8ff; border-color: #84b4e8; color: #16364f; }
            QLineEdit, QComboBox, QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit {
                border: 1px solid #c9d7e5;
                border-radius: 7px;
                background: white;
                padding: 4px;
            }
            QHeaderView::section {
                background: #edf3f8;
                padding: 5px;
                border: 0px;
                border-bottom: 1px solid #d5e0ea;
            }
            """
        )

    def _load_projects(self) -> None:
        projects = self.project_store.list_projects()
        self.project_selector.blockSignals(True)
        self.project_selector.clear()
        for project in projects:
            self.project_selector.addItem(project.name, project.project_id)
        self.project_selector.blockSignals(False)

        if not projects:
            self._create_project_with_dialog(initial=True)
            return
        self.project_selector.setCurrentIndex(0)
        self._on_project_changed(0)

    def _create_project_with_dialog(self, *, initial: bool = False) -> None:
        title = "Initial Setup" if initial else "Create Project"
        dialog = SetupDialog(self, title=title)
        if dialog.exec() == SetupDialog.DialogCode.Accepted:
            values = dialog.values()
            project = self.project_store.create_project(
                name=str(values["name"]),
                root_folder=str(values["root_folder"]),
                snapshot_dir=str(values["snapshot_dir"]),
                initial_scope_folders=list(values["initial_scope_folders"]),
                exclude_rules=list(values["exclude_rules"]),
            )
            self._load_projects()
            self._select_project(project.project_id)
            return

        if initial:
            QMessageBox.information(self, "Setup Required", "Project setup is required before using Re:Check.")

    def _select_project(self, project_id: str) -> None:
        for index in range(self.project_selector.count()):
            if self.project_selector.itemData(index) == project_id:
                self.project_selector.setCurrentIndex(index)
                self._on_project_changed(index)
                return

    def _on_project_changed(self, index: int) -> None:
        project_id = self.project_selector.itemData(index)
        if not project_id:
            return
        project = self.project_store.load_project(str(project_id))
        self.current_project = project

        self._refresh_scope_tree()
        self._refresh_snapshots()
        self._refresh_compare_logs()
        self._clear_results()
        self.statusBar().showMessage(f"Project loaded: {project.name}")

    def _refresh_snapshots(self) -> None:
        if not self.current_project:
            return
        self.snapshots = self.snapshot_store.list_snapshots(self.current_project)

        self.base_selector.blockSignals(True)
        self.compare_selector.blockSignals(True)
        self.base_selector.clear()
        self.compare_selector.clear()

        for snapshot in self.snapshots:
            label = f"{snapshot.created_at[:19]} | {snapshot.name}"
            self.base_selector.addItem(label, snapshot.snapshot_id)
            self.compare_selector.addItem(label, snapshot.snapshot_id)

        self.base_selector.blockSignals(False)
        self.compare_selector.blockSignals(False)

        if self.current_project.last_base_snapshot_id:
            self._set_combo_value(self.base_selector, self.current_project.last_base_snapshot_id)
        if self.current_project.last_compare_snapshot_id:
            self._set_combo_value(self.compare_selector, self.current_project.last_compare_snapshot_id)

        self.history_panel.set_snapshots(self.snapshots)

    def _refresh_compare_logs(self) -> None:
        if not self.current_project:
            return
        storage_dir = self.project_store.project_storage_dir(self.current_project.project_id)
        self.compare_logs = self.compare_log_store.list_compare_logs(storage_dir)
        self.history_panel.set_compares(self.compare_logs)

    def _set_combo_value(self, combo: QComboBox, target_value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == target_value:
                combo.setCurrentIndex(index)
                return

    def _clear_results(self) -> None:
        self.diff_entries = []
        self.visible_entries = []
        self.current_entry = None
        self.preview_info.setText("File: - | Type: - | Path: -")
        self.base_preview.show_file(None, empty_message="none", modified_time=None, size=None)
        self.compare_preview.show_file(None, empty_message="none", modified_time=None, size=None)
        self.diff_table.setRowCount(0)
        self._update_summary_counts({"added": 0, "removed": 0, "modified": 0, "unchanged": 0})

    def _save_snapshot(self) -> None:
        if not self.current_project:
            return
        default_name = self.current_project.name
        name, ok = QInputDialog.getText(self, "Save Snapshot", "Snapshot name", text=default_name)
        if not ok:
            return
        snapshot = self.snapshot_store.save_snapshot(self.current_project, name=name)
        self._refresh_snapshots()
        if self.base_selector.count() == 1:
            self.base_selector.setCurrentIndex(0)
        self._set_combo_value(self.compare_selector, snapshot.snapshot_id)
        self.statusBar().showMessage(f"Snapshot saved: {snapshot.name}")

    def _current_scope_mode(self) -> str:
        if self.mode_selected.isChecked():
            return "selected"
        if self.mode_multiple.isChecked():
            return "multiple"
        return "whole"

    def _selected_scope_folders(self) -> list[str]:
        mode = self._current_scope_mode()
        if mode == "whole":
            return []

        selected: list[str] = []
        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel_path = item.data(0, Qt.ItemDataRole.UserRole)
            if rel_path and item.checkState(0) == Qt.CheckState.Checked:
                selected.append(str(rel_path))
            iterator += 1

        if mode == "selected":
            if selected:
                return [selected[0]]
            current = self.scope_tree.currentItem()
            if current:
                rel_path = current.data(0, Qt.ItemDataRole.UserRole)
                if rel_path:
                    return [str(rel_path)]
            if self.current_project and self.current_project.initial_scope_folders:
                return [self.current_project.initial_scope_folders[0]]
            return []

        return selected

    def _execute_compare(self) -> None:
        if not self.current_project:
            return
        base_id = self.base_selector.currentData()
        compare_id = self.compare_selector.currentData()
        if not base_id or not compare_id:
            QMessageBox.warning(self, "Compare", "Select both Base and Compare snapshots.")
            return

        base_manifest = self.snapshot_store.load_manifest(self.current_project, str(base_id))
        compare_manifest = self.snapshot_store.load_manifest(self.current_project, str(compare_id))
        scope_mode = self._current_scope_mode()
        scope_folders = self._selected_scope_folders()

        result = compare_snapshots(
            base_manifest,
            compare_manifest,
            scope_mode=scope_mode,
            scope_folders=scope_folders,
        )
        self.diff_entries = result.entries
        self._update_summary_counts(result.counts)
        self._apply_filters_to_table()
        self._update_scope_badges(result.entries)

        storage_dir = self.project_store.project_storage_dir(self.current_project.project_id)
        self.compare_log_store.save_compare_log(
            project=self.current_project,
            project_storage_dir=storage_dir,
            base_snapshot_id=str(base_id),
            compare_snapshot_id=str(compare_id),
            scope_mode=scope_mode,
            scope_folders=scope_folders,
            result=result,
        )
        self._refresh_compare_logs()

        self.current_project.last_base_snapshot_id = str(base_id)
        self.current_project.last_compare_snapshot_id = str(compare_id)
        self.project_store.save_project(self.current_project)

        scope_label = ", ".join(scope_folders) if scope_folders else "(whole project)"
        self.current_path_label.setText(f"Path: {scope_label}")
        self.statusBar().showMessage("Compare completed and compare-log saved.")

    def _update_summary_counts(self, counts: dict[str, int]) -> None:
        total = sum(counts.values())
        self.filter_all_button.setText(f"All {total}")
        for status, button in self.summary_buttons.items():
            button.setText(f"{STATUS_JA[status]} {counts.get(status, 0)}")

    def _set_status_filter(self, status: str) -> None:
        self.current_status_filter = status
        if status == "all":
            self.filter_all_button.setChecked(True)
            for button in self.summary_buttons.values():
                button.setChecked(False)
        else:
            self.filter_all_button.setChecked(False)
            for key, button in self.summary_buttons.items():
                button.setChecked(key == status)
        self._apply_filters_to_table()

    def _apply_filters_to_table(self) -> None:
        search = self.search_box.text().strip().lower()
        filtered = self.diff_entries
        if self.current_status_filter != "all":
            filtered = [entry for entry in filtered if entry.status == self.current_status_filter]
        if search:
            filtered = [
                entry
                for entry in filtered
                if search in entry.file_name.lower() or search in entry.relative_path.lower()
            ]

        self.visible_entries = filtered
        self.diff_table.setSortingEnabled(False)
        self.diff_table.setRowCount(len(filtered))

        for row, entry in enumerate(filtered):
            row_items = [
                entry.status,
                entry.file_name,
                entry.relative_path,
                entry.base_modified_time or "-",
                entry.compare_modified_time or "-",
                "-" if entry.base_size is None else str(entry.base_size),
                "-" if entry.compare_size is None else str(entry.compare_size),
            ]
            for col, value in enumerate(row_items):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, asdict(entry))
                self.diff_table.setItem(row, col, item)
        self.diff_table.setSortingEnabled(True)

        if filtered:
            self.diff_table.selectRow(0)
        else:
            self.current_entry = None
            self._update_preview(None)

    def _on_diff_selection_changed(self) -> None:
        selected = self.diff_table.selectedItems()
        if not selected:
            return
        payload = selected[0].data(Qt.ItemDataRole.UserRole)
        if not payload:
            return
        entry = DiffEntry.from_dict(payload)
        self.current_entry = entry
        self._update_preview(entry)

    def _update_preview(self, entry: DiffEntry | None) -> None:
        if not entry:
            self.preview_info.setText("File: - | Type: - | Path: -")
            self.base_preview.show_file(None, empty_message="none", modified_time=None, size=None)
            self.compare_preview.show_file(None, empty_message="none", modified_time=None, size=None)
            return

        display_type = detect_preview_type(entry.compare_file_path or entry.base_file_path)
        self.preview_info.setText(
            f"File: {entry.file_name} | Type: {entry.status} ({display_type}) | Path: {entry.relative_path}"
        )

        base_message = "none" if entry.status == "added" else "No base preview"
        compare_message = "none" if entry.status == "removed" else "No compare preview"

        self.base_preview.show_file(
            entry.base_file_path,
            empty_message=base_message,
            modified_time=entry.base_modified_time,
            size=entry.base_size,
        )
        self.compare_preview.show_file(
            entry.compare_file_path,
            empty_message=compare_message,
            modified_time=entry.compare_modified_time,
            size=entry.compare_size,
        )

    def _open_base_file(self) -> None:
        if not self.current_entry or not self.current_entry.base_file_path:
            return
        self._open_path(self.current_entry.base_file_path)

    def _open_compare_file(self) -> None:
        if not self.current_entry or not self.current_entry.compare_file_path:
            return
        self._open_path(self.current_entry.compare_file_path)

    def _open_in_explorer(self) -> None:
        if not self.current_entry:
            return
        target = self.current_entry.compare_file_path or self.current_entry.base_file_path
        if not target:
            return
        self._open_path(str(Path(target).parent))

    def _open_path(self, path: str | None) -> None:
        if not path:
            return
        target = Path(path)
        if not target.exists():
            QMessageBox.warning(self, "Open", f"Path does not exist: {path}")
            return
        open_external(str(target))

    def _refresh_scope_tree(self) -> None:
        self.scope_tree.blockSignals(True)
        self.scope_tree.clear()
        if not self.current_project:
            self.scope_tree.blockSignals(False)
            return

        root_path = Path(self.current_project.root_folder)
        root_item = QTreeWidgetItem([root_path.name or str(root_path)])
        root_item.setData(0, Qt.ItemDataRole.UserRole, "")
        root_item.setData(0, Qt.ItemDataRole.UserRole + 1, root_path.name or str(root_path))
        root_item.setFlags(root_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, Qt.CheckState.Unchecked)
        self.scope_tree.addTopLevelItem(root_item)

        rel_to_item: dict[str, QTreeWidgetItem] = {"": root_item}
        if root_path.exists():
            for directory in sorted([p for p in root_path.rglob("*") if p.is_dir()]):
                rel = normalize_relpath(str(directory.relative_to(root_path)))
                parent_rel = normalize_relpath(str(Path(rel).parent)) if "/" in rel else ""
                if parent_rel == ".":
                    parent_rel = ""
                parent_item = rel_to_item.get(parent_rel, root_item)
                item = QTreeWidgetItem([directory.name])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, rel)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, directory.name)
                parent_item.addChild(item)
                rel_to_item[rel] = item

        for rel in self.current_project.initial_scope_folders:
            item = rel_to_item.get(normalize_relpath(rel))
            if item:
                item.setCheckState(0, Qt.CheckState.Checked)

        self.scope_tree.expandToDepth(1)
        self.scope_tree.blockSignals(False)

    def _update_scope_badges(self, entries: list[DiffEntry]) -> None:
        folder_counts: dict[str, int] = {}
        for entry in entries:
            if entry.status == "unchanged":
                continue
            rel = normalize_relpath(str(Path(entry.relative_path).parent))
            if rel == ".":
                rel = ""
            while True:
                folder_counts[rel] = folder_counts.get(rel, 0) + 1
                if not rel:
                    break
                parent = normalize_relpath(str(Path(rel).parent))
                rel = "" if parent == "." else parent

        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel = item.data(0, Qt.ItemDataRole.UserRole) or ""
            base_name = item.data(0, Qt.ItemDataRole.UserRole + 1) or item.text(0)
            count = folder_counts.get(str(rel), 0)
            item.setText(0, f"{base_name} [{count}]" if count > 0 else str(base_name))
            iterator += 1

    def _on_scope_mode_changed(self) -> None:
        if not self.mode_selected.isChecked():
            return
        checked_items = self._checked_scope_items()
        if len(checked_items) <= 1:
            return
        first = checked_items[0]
        self.scope_tree.blockSignals(True)
        for item in checked_items[1:]:
            item.setCheckState(0, Qt.CheckState.Unchecked)
        first.setCheckState(0, Qt.CheckState.Checked)
        self.scope_tree.blockSignals(False)

    def _on_scope_item_changed(self, changed: QTreeWidgetItem, _column: int) -> None:
        if not self.mode_selected.isChecked():
            return
        if changed.checkState(0) != Qt.CheckState.Checked:
            return
        self.scope_tree.blockSignals(True)
        for item in self._checked_scope_items():
            if item is not changed:
                item.setCheckState(0, Qt.CheckState.Unchecked)
        self.scope_tree.blockSignals(False)

    def _checked_scope_items(self) -> list[QTreeWidgetItem]:
        checked: list[QTreeWidgetItem] = []
        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel = item.data(0, Qt.ItemDataRole.UserRole)
            if rel and item.checkState(0) == Qt.CheckState.Checked:
                checked.append(item)
            iterator += 1
        return checked

    def _toggle_history_panel(self) -> None:
        if self.history_dock.isVisible():
            self.history_dock.hide()
        else:
            self.history_dock.show()
            self.history_dock.raise_()

    def _set_base_from_history(self, snapshot_id: str) -> None:
        self._set_combo_value(self.base_selector, snapshot_id)

    def _set_compare_from_history(self, snapshot_id: str) -> None:
        self._set_combo_value(self.compare_selector, snapshot_id)

    def _open_compare_from_history(self, compare_id: str) -> None:
        record = next((item for item in self.compare_logs if item.compare_id == compare_id), None)
        if not record:
            return
        self._set_combo_value(self.base_selector, record.base_snapshot_id)
        self._set_combo_value(self.compare_selector, record.compare_snapshot_id)
        self.diff_entries = record.entries
        self._update_summary_counts(record.counts)
        self._apply_filters_to_table()
        scope_label = ", ".join(record.scope_folders) if record.scope_folders else "(whole project)"
        self.current_path_label.setText(f"Path: {scope_label}")
        self.statusBar().showMessage(f"Opened saved compare: {record.compare_id}")

    def _switch_project_focus(self) -> None:
        self.project_selector.showPopup()

    def _open_project_menu(self) -> None:
        if not self.current_project and self.project_selector.count() == 0:
            self._create_project_with_dialog(initial=True)
            return

        menu = QMenu(self)
        create_action = QAction("Create Project", self)
        create_action.triggered.connect(lambda: self._create_project_with_dialog(initial=False))
        menu.addAction(create_action)

        settings_action = QAction("Project Settings", self)
        settings_action.triggered.connect(self._edit_project_settings)
        menu.addAction(settings_action)

        rename_action = QAction("Rename Project", self)
        rename_action.triggered.connect(self._rename_project)
        menu.addAction(rename_action)

        root_action = QAction("Change Root Folder", self)
        root_action.triggered.connect(self._change_root_folder)
        menu.addAction(root_action)

        scope_action = QAction("Edit Compare Folders", self)
        scope_action.triggered.connect(self._edit_initial_scope)
        menu.addAction(scope_action)

        exclude_action = QAction("Edit Exclude Rules", self)
        exclude_action.triggered.connect(self._edit_exclude_rules)
        menu.addAction(exclude_action)

        open_storage = QAction("Open Storage Folder", self)
        open_storage.triggered.connect(self._open_storage_folder)
        menu.addAction(open_storage)

        export_action = QAction("Export Project", self)
        export_action.triggered.connect(self._export_project)
        menu.addAction(export_action)

        menu.exec(self.project_menu_button.mapToGlobal(self.project_menu_button.rect().bottomLeft()))

    def _edit_project_settings(self) -> None:
        if not self.current_project:
            return
        dialog = SetupDialog(
            self,
            title="Project Settings",
            initial_values={
                "name": self.current_project.name,
                "root_folder": self.current_project.root_folder,
                "snapshot_dir": self.current_project.snapshot_dir,
                "initial_scope_folders": ", ".join(self.current_project.initial_scope_folders),
                "exclude_rules": ", ".join(self.current_project.exclude_rules),
            },
        )
        if dialog.exec() != SetupDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.current_project.name = str(values["name"])
        self.current_project.root_folder = str(values["root_folder"])
        self.current_project.snapshot_dir = str(values["snapshot_dir"])
        self.current_project.initial_scope_folders = list(values["initial_scope_folders"])
        self.current_project.exclude_rules = list(values["exclude_rules"])
        self.project_store.save_project(self.current_project)
        self._load_projects()
        self._select_project(self.current_project.project_id)

    def _rename_project(self) -> None:
        if not self.current_project:
            return
        value, ok = QInputDialog.getText(self, "Rename Project", "Project name", text=self.current_project.name)
        if not ok or not value.strip():
            return
        self.current_project.name = value.strip()
        self.project_store.save_project(self.current_project)
        self._load_projects()
        self._select_project(self.current_project.project_id)

    def _change_root_folder(self) -> None:
        if not self.current_project:
            return
        path = QFileDialog.getExistingDirectory(self, "Select Root Folder", self.current_project.root_folder)
        if not path:
            return
        self.current_project.root_folder = path
        self.project_store.save_project(self.current_project)
        self._refresh_scope_tree()

    def _edit_initial_scope(self) -> None:
        if not self.current_project:
            return
        existing = ", ".join(self.current_project.initial_scope_folders)
        value, ok = QInputDialog.getText(self, "Edit Compare Folders", "Comma separated folders", text=existing)
        if not ok:
            return
        self.current_project.initial_scope_folders = [item.strip() for item in value.split(",") if item.strip()]
        self.project_store.save_project(self.current_project)
        self._refresh_scope_tree()

    def _edit_exclude_rules(self) -> None:
        if not self.current_project:
            return
        existing = ", ".join(self.current_project.exclude_rules)
        value, ok = QInputDialog.getText(self, "Edit Exclude Rules", "Comma separated patterns", text=existing)
        if not ok:
            return
        self.current_project.exclude_rules = [item.strip() for item in value.split(",") if item.strip()]
        self.project_store.save_project(self.current_project)

    def _open_storage_folder(self) -> None:
        if not self.current_project:
            return
        storage = self.project_store.project_storage_dir(self.current_project.project_id)
        self._open_path(str(storage))

    def _export_project(self) -> None:
        if not self.current_project:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export Project",
            f"{self.current_project.name}_export.json",
            "JSON (*.json)",
        )
        if not target:
            return
        exported = self.project_store.export_project(self.current_project.project_id, target)
        self.statusBar().showMessage(f"Project exported: {exported}")

    def _open_settings_menu(self) -> None:
        menu = QMenu(self)
        for label in ("Appearance", "Theme", "Default Save Location", "Preview Settings", "Shortcuts"):
            action = QAction(label, self)
            action.triggered.connect(self._show_settings_stub)
            menu.addAction(action)
        version_action = QAction("Version Info", self)
        version_action.triggered.connect(lambda: QMessageBox.information(self, "Version", f"Re:Check {__version__}"))
        menu.addAction(version_action)
        menu.exec(self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft()))

    def _show_settings_stub(self) -> None:
        QMessageBox.information(self, "Settings", "App-level settings menu is scaffolded for v0.1.")

    def _show_command_palette_stub(self) -> None:
        QMessageBox.information(self, "Command Palette", "Ctrl+K entry is available in v0.1.")

    def _select_snapshots_by_date(self) -> None:
        if not self.snapshots:
            QMessageBox.information(self, "Compare by Date", "No snapshots are available.")
            return
        labels = [f"{s.created_at[:19]} | {s.name} | {s.snapshot_id}" for s in self.snapshots]
        base_label, ok = QInputDialog.getItem(self, "Base Snapshot", "Choose Base", labels, 0, False)
        if not ok:
            return
        compare_label, ok = QInputDialog.getItem(self, "Compare Snapshot", "Choose Compare", labels, 0, False)
        if not ok:
            return
        base_id = base_label.split("|")[-1].strip()
        compare_id = compare_label.split("|")[-1].strip()
        self._set_combo_value(self.base_selector, base_id)
        self._set_combo_value(self.compare_selector, compare_id)
