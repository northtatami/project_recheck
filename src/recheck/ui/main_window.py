from __future__ import annotations

import copy
import csv
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QGridLayout,
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
from recheck.core.file_scanner import scan_folder
from recheck.core.models import AppSettings, CompareLogRecord, DiffEntry, ProjectConfig, SnapshotManifest, SnapshotRecord
from recheck.core.preview_cache import PreviewCacheStore
from recheck.core.project_store import ProjectStore
from recheck.core.settings_store import AppSettingsStore
from recheck.core.snapshot_store import SnapshotStore
from recheck.ui.history_panel import HistoryPanel
from recheck.ui.i18n import I18n
from recheck.ui.preview_widgets import FilePreviewColumn
from recheck.ui.settings_dialog import SettingsDialog
from recheck.ui.setup_dialog import SetupDialog
from recheck.utils.filetype_utils import detect_preview_type
from recheck.utils.open_external import open_external
from recheck.utils.path_utils import normalize_relpath, safe_slug

STATUSES = ("added", "removed", "modified", "unchanged")
JST = timezone(timedelta(hours=9))


class RecheckMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.project_store = ProjectStore()
        self.settings_store = AppSettingsStore(self.project_store.app_data_dir)
        self.settings: AppSettings = self.settings_store.load()
        self.i18n = I18n(self.settings.language)

        self.preview_cache_store = PreviewCacheStore(self.project_store.app_data_dir)
        self.snapshot_store = SnapshotStore(self.preview_cache_store)
        self.compare_log_store = CompareLogStore()

        self.current_project: ProjectConfig | None = None
        self.snapshots: list[SnapshotRecord] = []
        self.compare_logs: list[CompareLogRecord] = []
        self.diff_entries: list[DiffEntry] = []
        self.visible_entries: list[DiffEntry] = []
        self.current_entry: DiffEntry | None = None
        self.current_status_filter = "all"
        self.latest_counts = {status: 0 for status in STATUSES}
        self.base_manifest: SnapshotManifest | None = None
        self.compare_manifest: SnapshotManifest | None = None
        self.main_splitter: QSplitter | None = None
        self.preview_panel: QFrame | None = None
        self.preview_content: QWidget | None = None
        self.preview_collapsed_hint: QLabel | None = None
        self._last_splitter_sizes = self._default_splitter_sizes()
        self.last_compare_csv_path: str | None = None
        self._shortcuts: list[QShortcut] = []

        self.setWindowTitle("Re:Check - Diff Review for folders")
        self.resize(1580, 920)

        self._build_ui()
        self._apply_style()
        self._retranslate_ui()
        self._load_projects()
        self.preview_cache_store.prune(self.settings)

    def _t(self, key: str, **kwargs: object) -> str:
        return self.i18n.t(key, **kwargs)

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(10)
        self.setCentralWidget(central)

        root.addWidget(self._build_header())

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self._build_scope_pane())
        self.main_splitter.addWidget(self._build_diff_pane())
        self.main_splitter.addWidget(self._build_preview_pane())
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 2)
        self.main_splitter.setStretchFactor(2, 2)
        self.main_splitter.setCollapsible(2, True)
        self.main_splitter.setSizes(self._last_splitter_sizes)
        root.addWidget(self.main_splitter, 1)

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

        shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        shortcut.activated.connect(self._show_command_palette_stub)
        self._shortcuts.append(shortcut)
        self._setup_shortcuts()
        self.statusBar().showMessage(self._t("msg.ready"))
        self._apply_preview_pane_visibility(self.settings.preview_pane_visible, persist=False, notify=False)

    def _default_splitter_sizes(self) -> list[int]:
        return [250, 640, 520]

    def _setup_shortcuts(self) -> None:
        bindings: list[tuple[str, callable]] = [
            ("Ctrl+Enter", self._execute_compare),
            ("Ctrl+Return", self._execute_compare),
            ("Ctrl+S", self._save_snapshot),
            ("Ctrl+H", self._toggle_history_panel),
            ("Ctrl+F", self._focus_diff_search),
            ("Esc", self._collapse_preview_from_shortcut),
            ("Ctrl+0", lambda: self._set_ui_text_size("medium")),
            ("Ctrl+=", self._increase_ui_text_size),
            ("Ctrl++", self._increase_ui_text_size),
            ("Ctrl+-", self._decrease_ui_text_size),
        ]
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _build_header(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("headerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        self.app_title = QLabel("Re:Check")
        self.app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel("Diff Review for folders")
        self.app_subtitle.setObjectName("appSubtitleInline")
        title_box.addWidget(self.app_title)
        title_box.addWidget(self.app_subtitle)
        title_box.addStretch(1)
        row1.addLayout(title_box)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.compare_button = QPushButton()
        self.compare_button.setObjectName("primaryButton")
        self.compare_button.clicked.connect(self._execute_compare)
        actions.addWidget(self.compare_button)

        self.history_button = QPushButton()
        self.history_button.clicked.connect(self._toggle_history_panel)
        actions.addWidget(self.history_button)

        self.settings_button = QPushButton()
        self.settings_button.setFixedWidth(40)
        self.settings_button.clicked.connect(self._open_settings_menu)
        actions.addWidget(self.settings_button)
        row1.addLayout(actions)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.project_label = QLabel()
        row2.addWidget(self.project_label)
        self.project_selector = QComboBox()
        self.project_selector.currentIndexChanged.connect(self._on_project_changed)
        self.project_selector.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.project_selector.setMinimumWidth(340)
        self.project_selector.setMaximumWidth(520)
        row2.addWidget(self.project_selector)

        self.project_menu_button = QPushButton("...")
        self.project_menu_button.setFixedWidth(36)
        self.project_menu_button.clicked.connect(self._open_project_menu)
        row2.addWidget(self.project_menu_button)
        row2.addStretch(1)
        layout.addLayout(row2)

        row3 = QGridLayout()
        row3.setHorizontalSpacing(8)
        row3.setVerticalSpacing(3)

        self.base_label = QLabel()
        row3.addWidget(self.base_label, 0, 0)
        self.base_selector = QComboBox()
        row3.addWidget(self.base_selector, 1, 0)

        self.base_compare_hint = QLabel()
        self.base_compare_hint.setObjectName("flowHint")
        self.base_compare_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        row3.addWidget(self.base_compare_hint, 1, 1)

        self.compare_label = QLabel()
        row3.addWidget(self.compare_label, 0, 2)
        self.compare_selector = QComboBox()
        row3.addWidget(self.compare_selector, 1, 2)

        self.snapshot_button = QPushButton()
        self.snapshot_button.clicked.connect(self._save_snapshot)
        row3.addWidget(self.snapshot_button, 1, 3)

        self.date_compare_button = QPushButton()
        self.date_compare_button.clicked.connect(self._select_snapshots_by_date)
        row3.addWidget(self.date_compare_button, 1, 4)

        row3.setColumnStretch(0, 4)
        row3.setColumnStretch(2, 4)
        layout.addLayout(row3)
        return panel

    def _build_scope_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("scopePane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.scope_title = QLabel()
        self.scope_title.setObjectName("paneTitle")
        layout.addWidget(self.scope_title)
        self.scope_helper = QLabel()
        self.scope_helper.setObjectName("paneHelp")
        layout.addWidget(self.scope_helper)

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_whole = QRadioButton()
        self.mode_selected = QRadioButton()
        self.mode_whole.setChecked(True)
        self.mode_group.addButton(self.mode_whole)
        self.mode_group.addButton(self.mode_selected)
        self.mode_whole.toggled.connect(self._on_scope_mode_changed)
        self.mode_selected.toggled.connect(self._on_scope_mode_changed)
        mode_row.addWidget(self.mode_whole)
        mode_row.addWidget(self.mode_selected)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.scope_tree = QTreeWidget()
        self.scope_tree.itemChanged.connect(self._on_scope_item_changed)
        layout.addWidget(self.scope_tree, 1)
        return panel

    def _build_diff_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("diffPane")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.diff_title = QLabel()
        self.diff_title.setObjectName("paneTitle")
        layout.addWidget(self.diff_title)
        self.diff_helper = QLabel()
        self.diff_helper.setObjectName("paneHelp")
        layout.addWidget(self.diff_helper)
        self.current_path_label = QLabel()
        layout.addWidget(self.current_path_label)

        cards = QHBoxLayout()
        self.summary_group = QButtonGroup(self)
        self.summary_group.setExclusive(True)

        self.filter_all_button = QPushButton()
        self.filter_all_button.setCheckable(True)
        self.filter_all_button.setChecked(True)
        self.filter_all_button.clicked.connect(lambda: self._set_status_filter("all"))
        cards.addWidget(self.filter_all_button)
        self.summary_group.addButton(self.filter_all_button)

        self.summary_buttons: dict[str, QPushButton] = {}
        for status in STATUSES:
            button = QPushButton()
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, s=status: self._set_status_filter(s))
            button.setObjectName(f"summary_{status}")
            cards.addWidget(button)
            self.summary_buttons[status] = button
            self.summary_group.addButton(button)
        layout.addLayout(cards)

        self.search_box = QLineEdit()
        self.search_box.textChanged.connect(self._apply_filters_to_table)
        layout.addWidget(self.search_box)

        self.diff_table = QTableWidget(0, 7)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.setWordWrap(False)
        self.diff_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diff_table.horizontalHeader().setFixedHeight(44)
        self._configure_diff_table_columns()
        self.diff_table.setSortingEnabled(True)
        self.diff_table.itemSelectionChanged.connect(self._on_diff_selection_changed)
        layout.addWidget(self.diff_table, 1)
        return panel

    def _configure_diff_table_columns(self) -> None:
        header = self.diff_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self.diff_table.setColumnWidth(1, 280)
        self.diff_table.setColumnWidth(2, 240)
        self.diff_table.setColumnWidth(3, 130)
        self.diff_table.setColumnWidth(4, 130)
        self.diff_table.setColumnWidth(5, 88)
        self.diff_table.setColumnWidth(6, 88)

    def _build_preview_pane(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("previewPane")
        self.preview_panel = panel
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        self.preview_title = QLabel()
        self.preview_title.setObjectName("paneTitle")
        title_row.addWidget(self.preview_title)
        title_row.addStretch(1)
        self.preview_collapse_button = QPushButton("<")
        self.preview_collapse_button.setObjectName("previewCollapseButton")
        self.preview_collapse_button.setFixedWidth(34)
        self.preview_collapse_button.clicked.connect(self._toggle_preview_pane)
        title_row.addWidget(self.preview_collapse_button)
        layout.addLayout(title_row)

        self.preview_collapsed_hint = QLabel()
        self.preview_collapsed_hint.setObjectName("previewCollapsedHint")
        self.preview_collapsed_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_collapsed_hint.hide()
        layout.addWidget(self.preview_collapsed_hint)

        self.preview_content = QWidget()
        content_layout = QVBoxLayout(self.preview_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        self.preview_helper = QLabel()
        self.preview_helper.setObjectName("paneHelp")
        content_layout.addWidget(self.preview_helper)

        self.preview_info = QLabel()
        self.preview_info.setWordWrap(True)
        content_layout.addWidget(self.preview_info)

        sides = QSplitter(Qt.Orientation.Horizontal)
        self.base_preview = FilePreviewColumn("Base", tr=self._t)
        self.compare_preview = FilePreviewColumn("Compare", tr=self._t)
        sides.addWidget(self.base_preview)
        sides.addWidget(self.compare_preview)
        sides.setSizes([1, 1])
        content_layout.addWidget(sides, 1)

        action_row = QHBoxLayout()
        self.open_base_button = QPushButton()
        self.open_base_button.clicked.connect(self._open_base_file)
        action_row.addWidget(self.open_base_button)
        self.open_compare_button = QPushButton()
        self.open_compare_button.clicked.connect(self._open_compare_file)
        action_row.addWidget(self.open_compare_button)
        self.open_explorer_button = QPushButton()
        self.open_explorer_button.clicked.connect(self._open_in_explorer)
        action_row.addWidget(self.open_explorer_button)
        action_row.addStretch(1)
        content_layout.addLayout(action_row)

        layout.addWidget(self.preview_content, 1)

        self.base_preview.open_button.clicked.connect(lambda: self._open_path(self.base_preview.current_path))
        self.compare_preview.open_button.clicked.connect(lambda: self._open_path(self.compare_preview.current_path))
        return panel

    def _apply_style(self) -> None:
        base_size = {"small": 12, "medium": 13, "large": 15}.get(getattr(self.settings, "ui_text_size", "medium"), 13)
        title_size = base_size + 8
        pane_title_size = base_size + 2
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ font-family: "Segoe UI"; font-size: {base_size}px; color: #25374a; }}
            QFrame#headerPanel, QFrame#scopePane, QFrame#diffPane, QFrame#previewPane {{
                background: #f7fafc;
                border: 1px solid #d6e0ea;
                border-radius: 10px;
            }}
            QLabel#appTitle {{ font-size: {title_size}px; font-weight: 700; color: #153954; }}
            QLabel#appSubtitleInline {{ color: #5f7387; padding-top: 2px; }}
            QLabel#paneTitle {{ font-size: {pane_title_size}px; font-weight: 700; color: #20455f; }}
            QLabel#paneHelp {{ color: #607487; }}
            QLabel#flowHint {{ color: #70879b; padding-left: 4px; padding-right: 4px; padding-bottom: 2px; }}
            QLabel#historyTitle {{ font-size: {base_size + 3}px; font-weight: 700; }}
            QLabel#previewCollapsedHint {{
                color: #5f7387;
                border: 1px dashed #c9d7e5;
                border-radius: 6px;
                background: #f2f6fa;
                padding: 6px;
            }}
            QPushButton {{
                background: #e7edf3;
                border: 1px solid #ccdae7;
                border-radius: 8px;
                padding: 6px 10px;
            }}
            QPushButton:hover {{ background: #dfe8f1; }}
            QPushButton#primaryButton {{
                background: #1f5d92;
                border: 1px solid #1a4e7a;
                color: #f8fcff;
                font-weight: 600;
            }}
            QPushButton#primaryButton:hover {{ background: #235f91; }}
            QPushButton#previewCollapseButton {{ padding: 4px 8px; font-weight: 700; }}
            QPushButton:checked {{ background: #d3e8ff; border-color: #84b4e8; color: #16364f; }}
            QPushButton#summary_added {{ background: #e9f6ed; border-color: #bcdcc6; }}
            QPushButton#summary_removed {{ background: #faecec; border-color: #e8c3c3; }}
            QPushButton#summary_modified {{ background: #ecf3fa; border-color: #c2d7ee; }}
            QPushButton#summary_unchanged {{ background: #f2f3f5; border-color: #d2d6dc; }}
            QPushButton#summary_added:checked {{ background: #cfead8; }}
            QPushButton#summary_removed:checked {{ background: #f2d8d8; }}
            QPushButton#summary_modified:checked {{ background: #d7e6f6; }}
            QPushButton#summary_unchanged:checked {{ background: #e5e7eb; }}
            QLineEdit, QComboBox, QTreeWidget, QTableWidget, QListWidget, QPlainTextEdit {{
                border: 1px solid #c9d7e5;
                border-radius: 7px;
                background: white;
                padding: 4px;
            }}
            QHeaderView::section {{
                background: #edf3f8;
                padding: 5px;
                border: 0px;
                border-bottom: 1px solid #d5e0ea;
            }}
            """
        )

    def _retranslate_ui(self) -> None:
        self.app_title.setText(self._t("app.title"))
        self.app_subtitle.setText(self._t("app.subtitle"))
        self.compare_button.setText(self._t("action.compare"))
        self.history_button.setText(self._t("action.history"))
        self.settings_button.setText(self._t("action.settings"))
        self.project_label.setText(self._t("label.project"))
        self.base_label.setText(self._t("label.base"))
        self.base_compare_hint.setText(self._t("label.base_compare_flow"))
        self.compare_label.setText(self._t("label.compare"))
        self.snapshot_button.setText(self._t("action.save_snapshot"))
        self.date_compare_button.setText(self._t("action.compare_by_date"))

        self.scope_title.setText(self._t("label.scope"))
        self.scope_helper.setText(self._t("helper.scope"))
        self.mode_whole.setText(self._t("scope.whole"))
        self.mode_selected.setText(self._t("scope.selected"))
        self.scope_tree.setHeaderLabels([self._t("label.scope")])

        self.diff_title.setText(self._t("label.diff_results"))
        self.diff_helper.setText(self._t("helper.diff"))
        self.current_path_label.setText(self._t("label.path_whole"))
        self.search_box.setPlaceholderText(self._t("search.placeholder"))
        self.diff_table.setHorizontalHeaderLabels(
            [
                self._t("table.type"),
                self._t("table.file_name"),
                self._t("table.relative_path"),
                self._t("table.base_modified_multiline"),
                self._t("table.compare_modified_multiline"),
                self._t("table.base_size_multiline"),
                self._t("table.compare_size_multiline"),
            ]
        )
        self._configure_diff_table_columns()

        self.preview_title.setText(self._t("label.preview"))
        self.preview_helper.setText(self._t("helper.preview"))
        self.preview_info.setText(self._t("preview.info.empty"))
        self.preview_collapsed_hint.setText(self._t("preview.collapsed_hint"))
        self.base_preview.retranslate(self._t, title=self._t("preview.base_column"))
        self.compare_preview.retranslate(self._t, title=self._t("preview.compare_column"))
        self.open_base_button.setText(self._t("action.open_base"))
        self.open_compare_button.setText(self._t("action.open_compare"))
        self.open_explorer_button.setText(self._t("action.open_explorer"))
        self.history_panel.retranslate(self._t)
        self._update_preview_collapse_control()

        self._update_summary_counts(self.latest_counts)

    def _load_projects(self, *, preferred_project_id: str | None = None) -> None:
        projects = self.project_store.list_projects()
        self.project_selector.blockSignals(True)
        self.project_selector.clear()
        for project in projects:
            self.project_selector.addItem(project.name, project.project_id)
        self.project_selector.blockSignals(False)

        if not projects:
            self._create_project_with_dialog(initial=True)
            return

        index = 0
        if preferred_project_id:
            for i in range(self.project_selector.count()):
                if self.project_selector.itemData(i) == preferred_project_id:
                    index = i
                    break
        self.project_selector.setCurrentIndex(index)
        self._on_project_changed(index)

    def _create_project_with_dialog(self, *, initial: bool = False) -> None:
        title_key = "dialog.setup.initial" if initial else "dialog.setup.create"
        dialog = SetupDialog(self, title=self._t(title_key), tr=self._t)
        if dialog.exec() == SetupDialog.DialogCode.Accepted:
            values = dialog.values()
            project = self.project_store.create_project(
                name=str(values["name"]),
                root_folder=str(values["root_folder"]),
                snapshot_dir=str(values["snapshot_dir"]),
                exclude_rules=list(values["exclude_rules"]),
            )
            self._reset_project_view_state()
            self._load_projects(preferred_project_id=project.project_id)
            if not self.current_project or self.current_project.project_id != project.project_id:
                self._select_project(project.project_id)
            if self.base_selector.count() == 0:
                self.base_selector.setCurrentIndex(-1)
            if self.compare_selector.count() == 0:
                self.compare_selector.setCurrentIndex(-1)
            created_message = self._t("msg.project_created_no_snapshot", name=project.name)
            QTimer.singleShot(0, lambda msg=created_message: self.statusBar().showMessage(msg, 8000))
            return

        if initial:
            QMessageBox.information(self, self._t("dialog.setup.initial"), self._t("msg.setup_required"))

    def _select_project(self, project_id: str) -> None:
        for index in range(self.project_selector.count()):
            if self.project_selector.itemData(index) == project_id:
                if self.project_selector.currentIndex() != index:
                    self.project_selector.setCurrentIndex(index)
                else:
                    self._on_project_changed(index)
                return

    def _on_project_changed(self, index: int) -> None:
        project_id = self.project_selector.itemData(index)
        if not project_id:
            return
        self._reset_project_view_state()

        project = self.project_store.load_project(str(project_id))
        self.current_project = project

        self._refresh_scope_tree()
        self._refresh_snapshots()
        self._refresh_compare_logs()
        if not self.snapshots:
            self.statusBar().showMessage(self._t("msg.project_loaded_empty", name=project.name), 8000)
            return
        self.statusBar().showMessage(self._t("msg.project_loaded", name=project.name))

    def _refresh_snapshots(self) -> None:
        if not self.current_project:
            return
        self.snapshots = self.snapshot_store.list_snapshots(self.current_project)

        self.base_selector.blockSignals(True)
        self.compare_selector.blockSignals(True)
        self.base_selector.clear()
        self.compare_selector.clear()

        for snapshot in self.snapshots:
            source_name = Path(snapshot.source_folder).name or snapshot.source_folder
            label = f"{self._format_table_timestamp(snapshot.created_at)} | {snapshot.name} | {source_name}"
            self.base_selector.addItem(label, snapshot.snapshot_id)
            self.compare_selector.addItem(label, snapshot.snapshot_id)

        self.base_selector.blockSignals(False)
        self.compare_selector.blockSignals(False)

        if self.current_project.last_base_snapshot_id:
            self._set_combo_value(self.base_selector, self.current_project.last_base_snapshot_id)
        if self.current_project.last_compare_snapshot_id:
            self._set_combo_value(self.compare_selector, self.current_project.last_compare_snapshot_id)
        if self.base_selector.count() == 0:
            self.base_selector.setCurrentIndex(-1)
        if self.compare_selector.count() == 0:
            self.compare_selector.setCurrentIndex(-1)
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
        self.latest_counts = {status: 0 for status in STATUSES}
        self.base_manifest = None
        self.compare_manifest = None
        self.current_path_label.setText(self._t("label.path_whole"))
        self.preview_info.setText(self._t("preview.info.empty"))
        self.base_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
        self.compare_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
        self.diff_table.setRowCount(0)
        self._update_summary_counts(self.latest_counts)

    def _reset_project_view_state(self) -> None:
        self.current_project = None
        self.snapshots = []
        self.compare_logs = []
        self.base_manifest = None
        self.compare_manifest = None
        self.last_compare_csv_path = None
        self.base_selector.blockSignals(True)
        self.compare_selector.blockSignals(True)
        self.base_selector.clear()
        self.compare_selector.clear()
        self.base_selector.setCurrentIndex(-1)
        self.compare_selector.setCurrentIndex(-1)
        self.base_selector.blockSignals(False)
        self.compare_selector.blockSignals(False)
        self.history_panel.set_snapshots([])
        self.history_panel.set_compares([])
        self._clear_results()

    def _save_snapshot(self) -> None:
        if not self.current_project:
            return
        default_name = self.current_project.name
        name, ok = QInputDialog.getText(self, self._t("dialog.snapshot.title"), self._t("dialog.snapshot.label"), text=default_name)
        if not ok:
            return
        snapshot = self.snapshot_store.save_snapshot(self.current_project, settings=self.settings, name=name)
        self._refresh_scope_tree()
        self._refresh_snapshots()
        self._set_combo_value(self.compare_selector, snapshot.snapshot_id)
        self.statusBar().showMessage(self._t("msg.snapshot_saved", name=snapshot.name))

    def _import_external_folder_as_snapshot(self) -> None:
        if not self.current_project:
            return
        picked = QFileDialog.getExistingDirectory(
            self,
            self._t("dialog.external_snapshot.title"),
            self.current_project.root_folder,
        )
        if not picked:
            return
        folder_name = Path(picked).name or "external"
        snapshot_name = f"external_{folder_name}"
        snapshot = self.snapshot_store.save_snapshot(
            self.current_project,
            settings=self.settings,
            name=snapshot_name,
            source_folder=picked,
        )
        self._refresh_snapshots()
        self._set_combo_value(self.compare_selector, snapshot.snapshot_id)
        self.statusBar().showMessage(self._t("msg.external_snapshot_created", name=snapshot.name))

    def _current_scope_mode(self) -> str:
        if self.mode_selected.isChecked():
            return "selected"
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

        unique = sorted({normalize_relpath(item) for item in selected if item.strip()})
        return unique

    def _execute_compare(self) -> None:
        if not self.current_project:
            return
        if len(self.snapshots) < 2:
            QMessageBox.information(self, self._t("action.compare"), self._t("msg.compare_need_snapshots"))
            return
        base_id = self.base_selector.currentData()
        compare_id = self.compare_selector.currentData()
        if not base_id or not compare_id:
            QMessageBox.warning(self, self._t("action.compare"), self._t("msg.compare_missing"))
            return
        if str(base_id) == str(compare_id):
            QMessageBox.information(self, self._t("action.compare"), self._t("msg.compare_need_distinct"))
            return
        if self._current_scope_mode() == "selected" and not self._selected_scope_folders():
            QMessageBox.information(self, self._t("action.compare"), self._t("msg.scope_need_checked"))
            return

        if self._is_current_root_state_unsaved():
            decision = self._ask_compare_with_unsaved_state()
            if decision == "cancel":
                return
            if decision == "save":
                selected_base_id = str(base_id)
                snapshot = self.snapshot_store.save_snapshot(
                    self.current_project,
                    settings=self.settings,
                    name=f"compare_{self.current_project.name}",
                    source_folder=self.current_project.root_folder,
                )
                self._refresh_scope_tree()
                self._refresh_snapshots()
                self._set_combo_value(self.base_selector, selected_base_id)
                self._set_combo_value(self.compare_selector, snapshot.snapshot_id)
                compare_id = snapshot.snapshot_id

        self._run_compare(str(base_id), str(compare_id))

    def _run_compare(self, base_id: str, compare_id: str) -> None:
        if not self.current_project:
            return

        self.base_manifest = self.snapshot_store.load_manifest(self.current_project, base_id)
        self.compare_manifest = self.snapshot_store.load_manifest(self.current_project, compare_id)
        scope_mode = self._current_scope_mode()
        scope_folders = self._selected_scope_folders()

        result = compare_snapshots(
            self.base_manifest,
            self.compare_manifest,
            scope_mode=scope_mode,
            scope_folders=scope_folders,
        )
        self.diff_entries = result.entries
        self.latest_counts = result.counts
        self._update_summary_counts(result.counts)
        self._apply_filters_to_table()
        self._update_scope_badges(result.entries)

        storage_dir = self.project_store.project_storage_dir(self.current_project.project_id)
        self.compare_log_store.save_compare_log(
            project=self.current_project,
            project_storage_dir=storage_dir,
            base_snapshot_id=base_id,
            compare_snapshot_id=compare_id,
            scope_mode=scope_mode,
            scope_folders=scope_folders,
            result=result,
        )
        self._refresh_compare_logs()
        csv_path = self._save_compare_csv(
            project_storage_dir=storage_dir,
            base_snapshot_id=base_id,
            compare_snapshot_id=compare_id,
            entries=result.entries,
        )
        self.last_compare_csv_path = csv_path

        self.current_project.last_base_snapshot_id = base_id
        self.current_project.last_compare_snapshot_id = compare_id
        self.project_store.save_project(self.current_project)

        scope_label = ", ".join(scope_folders) if scope_folders else self._t("msg.preview_scope_whole")
        self.current_path_label.setText(f"Path: {scope_label}")
        self.statusBar().showMessage(
            self._t("msg.compare_done_csv_path", name=Path(csv_path).name, path=csv_path),
            12000,
        )

    def _ask_compare_with_unsaved_state(self) -> str:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle(self._t("dialog.compare_prompt.title"))
        msg.setText(self._t("dialog.compare_prompt.text"))
        save_btn = msg.addButton(self._t("dialog.compare_prompt.save_compare"), QMessageBox.ButtonRole.AcceptRole)
        compare_btn = msg.addButton(self._t("dialog.compare_prompt.compare_only"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton(self._t("dialog.compare_prompt.cancel"), QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == save_btn:
            return "save"
        if clicked == compare_btn:
            return "compare_only"
        if clicked == cancel_btn:
            return "cancel"
        return "cancel"

    def _is_current_root_state_unsaved(self) -> bool:
        if not self.current_project:
            return False
        root = Path(self.current_project.root_folder).resolve()
        try:
            current_scan = scan_folder(str(root), self.current_project.exclude_rules)
        except Exception:
            return False
        current_map = {item.relative_path: (item.size, item.modified_time) for item in current_scan}

        latest_root_snapshot: SnapshotRecord | None = None
        for snapshot in self.snapshots:
            if Path(snapshot.source_folder).resolve() == root:
                latest_root_snapshot = snapshot
                break

        if latest_root_snapshot is None:
            return len(current_map) > 0

        manifest = self.snapshot_store.load_manifest(self.current_project, latest_root_snapshot.snapshot_id)
        snapshot_map = {item.relative_path: (item.size, item.modified_time) for item in manifest.files}
        return current_map != snapshot_map

    def _status_label(self, status: str) -> str:
        return self._t(f"status.{status}")

    def _format_table_timestamp(self, value: str | None) -> str:
        if not value:
            return "-"
        normalized = value.strip()
        if not normalized:
            return "-"
        try:
            dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(JST)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            if "T" in normalized:
                fallback = normalized.replace("T", " ")
                return fallback.split(".")[0][:19]
            return normalized

    def _parent_path_display(self, relative_path: str) -> str:
        parent = normalize_relpath(str(Path(relative_path).parent))
        if parent in {"", "."}:
            return self._t("label.path_root")
        return parent

    def _diff_row_height(self) -> int:
        size_key = getattr(self.settings, "ui_text_size", "medium")
        if size_key == "small":
            return 24
        if size_key == "large":
            return 30
        return 26

    def _update_summary_counts(self, counts: dict[str, int]) -> None:
        total = sum(counts.values())
        self.filter_all_button.setText(f"{self._t('filter.all')} {total}")
        for status, button in self.summary_buttons.items():
            button.setText(f"{self._status_label(status)} {counts.get(status, 0)}")

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
            file_display = entry.file_name
            parent_display = self._parent_path_display(entry.relative_path)
            row_items = [
                self._status_label(entry.status),
                file_display,
                parent_display,
                self._format_table_timestamp(entry.base_modified_time),
                self._format_table_timestamp(entry.compare_modified_time),
                "-" if entry.base_size is None else str(entry.base_size),
                "-" if entry.compare_size is None else str(entry.compare_size),
            ]
            for col, value in enumerate(row_items):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, asdict(entry))
                    status_colors = {
                        "added": QColor("#e9f6ed"),
                        "removed": QColor("#faecec"),
                        "modified": QColor("#ecf3fa"),
                        "unchanged": QColor("#f2f3f5"),
                    }
                    item.setBackground(QBrush(status_colors.get(entry.status, QColor("#ffffff"))))
                if col == 1:
                    item.setToolTip(entry.relative_path)
                if col == 2:
                    item.setToolTip(entry.relative_path)
                    item.setForeground(QBrush(QColor("#5f7387")))
                if col == 3 and entry.base_modified_time:
                    item.setToolTip(entry.base_modified_time)
                if col == 4 and entry.compare_modified_time:
                    item.setToolTip(entry.compare_modified_time)
                self.diff_table.setItem(row, col, item)
            self.diff_table.setRowHeight(row, self._diff_row_height())
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

    def _resolve_entry_preview_paths(self, entry: DiffEntry) -> tuple[str | None, str | None]:
        base_path = None
        compare_path = None
        if self.base_manifest and entry.base_size is not None:
            base_path = self.snapshot_store.resolve_preview_path(self.base_manifest, entry.relative_path)
        if self.compare_manifest and entry.compare_size is not None:
            compare_path = self.snapshot_store.resolve_preview_path(self.compare_manifest, entry.relative_path)
        return base_path, compare_path

    def _update_preview(self, entry: DiffEntry | None) -> None:
        if not entry:
            self.preview_info.setText(self._t("preview.info.empty"))
            self.base_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
            self.compare_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
            return

        base_path, compare_path = self._resolve_entry_preview_paths(entry)
        display_type = detect_preview_type(entry.relative_path)
        self.preview_info.setText(
            f"File: {entry.file_name} | Diff: {self._status_label(entry.status)} | Type: {display_type} | Path: {entry.relative_path}"
        )

        self.base_preview.show_file(
            base_path,
            empty_message=self._t("preview.none") if entry.status == "added" else self._t("preview.no_file_selected"),
            modified_time=entry.base_modified_time,
            size=entry.base_size,
            type_hint_path=entry.relative_path,
        )
        self.compare_preview.show_file(
            compare_path,
            empty_message=self._t("preview.none") if entry.status == "removed" else self._t("preview.no_file_selected"),
            modified_time=entry.compare_modified_time,
            size=entry.compare_size,
            type_hint_path=entry.relative_path,
        )

    def _open_base_file(self) -> None:
        if not self.current_entry:
            return
        base_path, _ = self._resolve_entry_preview_paths(self.current_entry)
        self._open_path(base_path)

    def _open_compare_file(self) -> None:
        if not self.current_entry:
            return
        _, compare_path = self._resolve_entry_preview_paths(self.current_entry)
        self._open_path(compare_path)

    def _open_in_explorer(self) -> None:
        if not self.current_entry:
            return
        base_path, compare_path = self._resolve_entry_preview_paths(self.current_entry)
        target = compare_path or base_path
        if not target:
            return
        self._open_path(str(Path(target).parent))

    def _open_path(self, path: str | None) -> None:
        if not path:
            return
        target = Path(path)
        if not target.exists():
            QMessageBox.warning(self, "Open", self._t("msg.path_missing", path=path))
            return
        open_external(str(target))

    def _refresh_scope_tree(self) -> None:
        checked_paths: set[str] = set()
        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel = item.data(0, Qt.ItemDataRole.UserRole)
            if rel and item.checkState(0) == Qt.CheckState.Checked:
                checked_paths.add(str(rel))
            iterator += 1

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
                item.setCheckState(0, Qt.CheckState.Checked if rel in checked_paths else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, rel)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, directory.name)
                parent_item.addChild(item)
                rel_to_item[rel] = item

        self.scope_tree.expandToDepth(1)
        self.scope_tree.blockSignals(False)

    def _update_scope_badges(self, entries: list[DiffEntry]) -> None:
        folder_counts: dict[str, int] = {}
        folder_has_added: set[str] = set()
        folder_has_modified: set[str] = set()
        for entry in entries:
            if entry.status == "unchanged":
                continue
            rel = normalize_relpath(str(Path(entry.relative_path).parent))
            if rel == ".":
                rel = ""
            while True:
                folder_counts[rel] = folder_counts.get(rel, 0) + 1
                if entry.status == "added":
                    folder_has_added.add(rel)
                elif entry.status == "modified":
                    folder_has_modified.add(rel)
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
            if str(rel) in folder_has_added:
                item.setForeground(0, QBrush(QColor("#2f7d45")))
            elif str(rel) in folder_has_modified:
                item.setForeground(0, QBrush(QColor("#2d5f90")))
            else:
                item.setForeground(0, QBrush(QColor("#25374a")))
            iterator += 1

    def _on_scope_mode_changed(self) -> None:
        return

    def _on_scope_item_changed(self, changed: QTreeWidgetItem, _column: int) -> None:
        return

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

    def _toggle_preview_pane(self) -> None:
        self._apply_preview_pane_visibility(not self.settings.preview_pane_visible)

    def _apply_preview_pane_visibility(self, visible: bool, *, persist: bool = True, notify: bool = True) -> None:
        if self.main_splitter is None or self.preview_panel is None or self.preview_content is None or self.preview_collapsed_hint is None:
            return
        collapsed_width = 56
        sizes = self.main_splitter.sizes()
        if visible:
            self.preview_content.show()
            self.preview_collapsed_hint.hide()
            self.preview_panel.setMinimumWidth(260)
            self.preview_panel.setMaximumWidth(16777215)
            if len(self._last_splitter_sizes) == 3 and self._last_splitter_sizes[2] > 0:
                self.main_splitter.setSizes(self._last_splitter_sizes)
            else:
                self.main_splitter.setSizes(self._default_splitter_sizes())
            if notify:
                self.statusBar().showMessage(self._t("msg.preview_shown"))
        else:
            if len(sizes) == 3 and sizes[2] > collapsed_width:
                self._last_splitter_sizes = sizes
            self.preview_content.hide()
            self.preview_collapsed_hint.show()
            self.preview_panel.setMinimumWidth(collapsed_width)
            self.preview_panel.setMaximumWidth(collapsed_width)

            defaults = self._default_splitter_sizes()
            left = sizes[0] if len(sizes) > 0 else defaults[0]
            center = sizes[1] if len(sizes) > 1 else defaults[1]
            total = sum(sizes) if sizes else sum(defaults)
            remaining = max(220, total - collapsed_width)
            left_ratio = left / max(1, left + center)
            left_new = int(remaining * left_ratio)
            center_new = max(120, remaining - left_new)
            left_new = max(120, left_new)
            self.main_splitter.setSizes([left_new, center_new, collapsed_width])
            if notify:
                self.statusBar().showMessage(self._t("msg.preview_hidden"))

        self.settings.preview_pane_visible = visible
        if persist:
            self.settings_store.save(self.settings)
        self._update_preview_collapse_control()

    def _update_preview_collapse_control(self) -> None:
        if self.settings.preview_pane_visible:
            self.preview_collapse_button.setText("<")
            self.preview_collapse_button.setToolTip(self._t("preview.collapse"))
        else:
            self.preview_collapse_button.setText(">")
            self.preview_collapse_button.setToolTip(self._t("preview.expand"))

    def _set_base_from_history(self, snapshot_id: str) -> None:
        self._set_combo_value(self.base_selector, snapshot_id)

    def _set_compare_from_history(self, snapshot_id: str) -> None:
        self._set_combo_value(self.compare_selector, snapshot_id)

    def _open_compare_from_history(self, compare_id: str) -> None:
        record = next((item for item in self.compare_logs if item.compare_id == compare_id), None)
        if not record or not self.current_project:
            return
        self._set_combo_value(self.base_selector, record.base_snapshot_id)
        self._set_combo_value(self.compare_selector, record.compare_snapshot_id)
        self.base_manifest = self.snapshot_store.load_manifest(self.current_project, record.base_snapshot_id)
        self.compare_manifest = self.snapshot_store.load_manifest(self.current_project, record.compare_snapshot_id)
        self.diff_entries = record.entries
        self.latest_counts = record.counts
        self._update_summary_counts(record.counts)
        self._apply_filters_to_table()
        scope_label = ", ".join(record.scope_folders) if record.scope_folders else self._t("msg.preview_scope_whole")
        self.current_path_label.setText(f"Path: {scope_label}")

    def _open_project_menu(self) -> None:
        if not self.current_project and self.project_selector.count() == 0:
            self._create_project_with_dialog(initial=True)
            return

        menu = QMenu(self)
        create_action = QAction(self._t("project.menu.create"), self)
        create_action.triggered.connect(lambda: self._create_project_with_dialog(initial=False))
        menu.addAction(create_action)

        settings_action = QAction(self._t("project.menu.settings"), self)
        settings_action.triggered.connect(self._edit_project_settings)
        menu.addAction(settings_action)

        rename_action = QAction(self._t("project.menu.rename"), self)
        rename_action.triggered.connect(self._rename_project)
        menu.addAction(rename_action)

        root_action = QAction(self._t("project.menu.change_root"), self)
        root_action.triggered.connect(self._change_root_folder)
        menu.addAction(root_action)

        exclude_action = QAction(self._t("project.menu.edit_exclude"), self)
        exclude_action.triggered.connect(self._edit_exclude_rules)
        menu.addAction(exclude_action)

        import_action = QAction(self._t("project.menu.import_external_snapshot"), self)
        import_action.triggered.connect(self._import_external_folder_as_snapshot)
        menu.addAction(import_action)

        open_exports = QAction(self._t("project.menu.open_compare_exports"), self)
        open_exports.triggered.connect(self._open_compare_exports_folder)
        menu.addAction(open_exports)

        open_last_csv = QAction(self._t("project.menu.open_last_compare_csv"), self)
        open_last_csv.setEnabled(bool(self.last_compare_csv_path))
        open_last_csv.triggered.connect(self._open_last_compare_csv)
        menu.addAction(open_last_csv)

        open_storage = QAction(self._t("project.menu.open_storage"), self)
        open_storage.triggered.connect(self._open_storage_folder)
        menu.addAction(open_storage)

        export_action = QAction(self._t("project.menu.export"), self)
        export_action.triggered.connect(self._export_project)
        menu.addAction(export_action)

        menu.exec(self.project_menu_button.mapToGlobal(self.project_menu_button.rect().bottomLeft()))

    def _edit_project_settings(self) -> None:
        if not self.current_project:
            return
        dialog = SetupDialog(
            self,
            title=self._t("dialog.setup.edit"),
            tr=self._t,
            initial_values={
                "name": self.current_project.name,
                "root_folder": self.current_project.root_folder,
                "snapshot_dir": self.current_project.snapshot_dir,
                "exclude_rules": ", ".join(self.current_project.exclude_rules),
            },
        )
        if dialog.exec() != SetupDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.current_project.name = str(values["name"])
        self.current_project.root_folder = str(values["root_folder"])
        self.current_project.snapshot_dir = str(values["snapshot_dir"])
        self.current_project.exclude_rules = list(values["exclude_rules"])
        self.project_store.save_project(self.current_project)
        self._load_projects(preferred_project_id=self.current_project.project_id)

    def _rename_project(self) -> None:
        if not self.current_project:
            return
        value, ok = QInputDialog.getText(
            self,
            self._t("dialog.rename.title"),
            self._t("dialog.rename.label"),
            text=self.current_project.name,
        )
        if not ok or not value.strip():
            return
        self.current_project.name = value.strip()
        self.project_store.save_project(self.current_project)
        self._load_projects(preferred_project_id=self.current_project.project_id)

    def _change_root_folder(self) -> None:
        if not self.current_project:
            return
        path = QFileDialog.getExistingDirectory(self, self._t("dialog.setup.root_folder"), self.current_project.root_folder)
        if not path:
            return
        self.current_project.root_folder = path
        self.project_store.save_project(self.current_project)
        self._refresh_scope_tree()

    def _edit_exclude_rules(self) -> None:
        if not self.current_project:
            return
        existing = ", ".join(self.current_project.exclude_rules)
        value, ok = QInputDialog.getText(
            self,
            self._t("dialog.exclude_edit.title"),
            self._t("dialog.exclude_edit.label"),
            text=existing,
        )
        if not ok:
            return
        self.current_project.exclude_rules = [item.strip() for item in value.split(",") if item.strip()]
        self.project_store.save_project(self.current_project)

    def _open_storage_folder(self) -> None:
        if not self.current_project:
            return
        storage = self.project_store.project_storage_dir(self.current_project.project_id)
        self._open_path(str(storage))

    def _open_compare_exports_folder(self) -> None:
        if not self.current_project:
            return
        storage = self.project_store.project_storage_dir(self.current_project.project_id)
        export_dir = storage / "compare_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(str(export_dir))

    def _open_last_compare_csv(self) -> None:
        if not self.last_compare_csv_path:
            return
        self._open_path(self.last_compare_csv_path)

    def _save_compare_csv(
        self,
        *,
        project_storage_dir: Path,
        base_snapshot_id: str,
        compare_snapshot_id: str,
        entries: list[DiffEntry],
    ) -> str:
        export_dir = project_storage_dir / "compare_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        project_slug = safe_slug(self.current_project.name if self.current_project else "project")
        base_slug = safe_slug(base_snapshot_id)[:24]
        compare_slug = safe_slug(compare_snapshot_id)[:24]
        file_name = f"{project_slug}_{stamp}_base-{base_slug}_compare-{compare_slug}.csv"
        csv_path = export_dir / file_name

        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "kind",
                    "filename",
                    "relative_path",
                    "base_modified",
                    "compare_modified",
                    "base_size",
                    "compare_size",
                ]
            )
            for entry in entries:
                writer.writerow(
                    [
                        entry.status,
                        entry.file_name,
                        entry.relative_path,
                        self._format_table_timestamp(entry.base_modified_time),
                        self._format_table_timestamp(entry.compare_modified_time),
                        "" if entry.base_size is None else entry.base_size,
                        "" if entry.compare_size is None else entry.compare_size,
                    ]
                )
        return str(csv_path)

    def _export_project(self) -> None:
        if not self.current_project:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            self._t("project.menu.export"),
            f"{self.current_project.name}_export.json",
            "JSON (*.json)",
        )
        if not target:
            return
        exported = self.project_store.export_project(self.current_project.project_id, target)
        self.statusBar().showMessage(exported)

    def _open_settings_menu(self) -> None:
        menu = QMenu(self)
        app_action = QAction(self._t("settings.menu"), self)
        app_action.triggered.connect(self._open_settings_dialog)
        menu.addAction(app_action)

        reset_layout_action = QAction(self._t("settings.reset_layout"), self)
        reset_layout_action.triggered.connect(self._reset_layout_defaults)
        menu.addAction(reset_layout_action)

        version_action = QAction(self._t("settings.version"), self)
        version_action.triggered.connect(lambda: QMessageBox.information(self, self._t("settings.version"), f"Re:Check {__version__}"))
        menu.addAction(version_action)
        menu.exec(self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft()))

    def _reset_layout_defaults(self) -> None:
        if self.main_splitter is None:
            return
        self._last_splitter_sizes = self._default_splitter_sizes()
        self._apply_preview_pane_visibility(True, persist=True, notify=False)
        self.main_splitter.setSizes(self._last_splitter_sizes)
        self.statusBar().showMessage(self._t("msg.layout_reset"), 5000)

    def _open_settings_dialog(self) -> None:
        draft = copy.deepcopy(self.settings)
        dialog = SettingsDialog(self, settings=draft, tr=self._t)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        updated = dialog.build_settings(draft)
        self.settings = self.settings_store.save(updated)
        self.i18n.set_language(self.settings.language)
        self.preview_cache_store.prune(self.settings)
        self._apply_style()
        self._apply_filters_to_table()
        self._retranslate_ui()
        self.statusBar().showMessage(self._t("settings.saved_restartless"))

    def _focus_diff_search(self) -> None:
        self.search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_box.selectAll()

    def _collapse_preview_from_shortcut(self) -> None:
        if self.settings.preview_pane_visible:
            self._apply_preview_pane_visibility(False)

    def _set_ui_text_size(self, size_key: str) -> None:
        if size_key not in {"small", "medium", "large"}:
            return
        if getattr(self.settings, "ui_text_size", "medium") == size_key:
            return
        self.settings.ui_text_size = size_key
        self.settings_store.save(self.settings)
        self._apply_style()
        self._apply_filters_to_table()
        self.statusBar().showMessage(self._t("msg.text_size_changed", size=self._t(f"text_size.{size_key}")), 4000)

    def _increase_ui_text_size(self) -> None:
        order = ["small", "medium", "large"]
        current = getattr(self.settings, "ui_text_size", "medium")
        idx = order.index(current) if current in order else 1
        if idx < len(order) - 1:
            self._set_ui_text_size(order[idx + 1])

    def _decrease_ui_text_size(self) -> None:
        order = ["small", "medium", "large"]
        current = getattr(self.settings, "ui_text_size", "medium")
        idx = order.index(current) if current in order else 1
        if idx > 0:
            self._set_ui_text_size(order[idx - 1])

    def _show_command_palette_stub(self) -> None:
        QMessageBox.information(self, "Ctrl+K", self._t("msg.command_palette_stub"))

    def _select_snapshots_by_date(self) -> None:
        if not self.snapshots:
            QMessageBox.information(self, self._t("action.compare_by_date"), self._t("msg.no_snapshots"))
            return
        labels = [f"{self._format_table_timestamp(s.created_at)} | {s.name} | {s.snapshot_id}" for s in self.snapshots]
        base_label, ok = QInputDialog.getItem(
            self,
            self._t("dialog.base_date.title"),
            self._t("dialog.base_date.label"),
            labels,
            0,
            False,
        )
        if not ok:
            return
        compare_label, ok = QInputDialog.getItem(
            self,
            self._t("dialog.compare_date.title"),
            self._t("dialog.compare_date.label"),
            labels,
            0,
            False,
        )
        if not ok:
            return
        base_id = base_label.split("|")[-1].strip()
        compare_id = compare_label.split("|")[-1].strip()
        self._set_combo_value(self.base_selector, base_id)
        self._set_combo_value(self.compare_selector, compare_id)
