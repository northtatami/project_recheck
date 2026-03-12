from __future__ import annotations

import copy
import csv
import logging
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

from PySide6.QtCore import QObject, QModelIndex, QRunnable, QThreadPool, QTimer, Qt, Signal
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
    QProgressDialog,
    QProgressBar,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QTableView,
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
from recheck.ui.diff_table_model import DiffFilterProxyModel, DiffTableModel
from recheck.ui.settings_dialog import SettingsDialog
from recheck.ui.setup_dialog import SetupDialog
from recheck.utils.filetype_utils import detect_preview_type
from recheck.utils.open_external import open_external
from recheck.utils.path_utils import normalize_relpath, safe_slug

STATUSES = ("added", "removed", "modified", "unchanged")
JST = timezone(timedelta(hours=9))
LOGGER = logging.getLogger(__name__)


def format_display_timestamp(value: str | None) -> str:
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


def write_compare_csv_file(
    *,
    project_storage_dir: Path,
    project_name: str,
    base_snapshot_id: str,
    compare_snapshot_id: str,
    entries: list[DiffEntry],
) -> str:
    export_dir = project_storage_dir / "compare_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    project_slug = safe_slug(project_name)
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
                    format_display_timestamp(entry.base_modified_time),
                    format_display_timestamp(entry.compare_modified_time),
                    "" if entry.base_size is None else entry.base_size,
                    "" if entry.compare_size is None else entry.compare_size,
                ]
            )
    return str(csv_path)


class _TaskSignals(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)


class _TaskRunner(QRunnable):
    def __init__(self, task_id: str, fn) -> None:
        super().__init__()
        self.task_id = task_id
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception:
            try:
                self.signals.failed.emit(self.task_id, traceback.format_exc())
            except RuntimeError:
                pass
            return
        try:
            self.signals.finished.emit(self.task_id, result)
        except RuntimeError:
            pass


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
        self.thread_pool = QThreadPool.globalInstance()

        self.current_project: ProjectConfig | None = None
        self.snapshots: list[SnapshotRecord] = []
        self.compare_logs: list[CompareLogRecord] = []
        self.diff_entries: list[DiffEntry] = []
        self.visible_entries: list[DiffEntry] = []
        self.current_entry: DiffEntry | None = None
        self.current_status_filter = "all"
        self._scope_dataset_model_key: int | None = None
        self._suppress_selection_events = False
        self.latest_counts = {status: 0 for status in STATUSES}
        self.base_manifest: SnapshotManifest | None = None
        self.compare_manifest: SnapshotManifest | None = None
        self._scope_checked_paths: set[str] = set()
        self.main_splitter: QSplitter | None = None
        self.preview_panel: QFrame | None = None
        self.preview_content: QWidget | None = None
        self.preview_collapsed_hint: QLabel | None = None
        self._last_splitter_sizes = self._default_splitter_sizes()
        self.last_compare_csv_path: str | None = None
        self._shortcuts: list[QShortcut] = []
        self._task_callbacks: dict[str, tuple[callable, callable | None]] = {}
        self._task_messages: dict[str, str] = {}
        self._task_progress_dialogs: dict[str, QProgressDialog] = {}
        self._task_counter = 0
        self._busy_task_id: str | None = None
        self._history_dirty = True
        self._scope_build_token = 0
        self._scope_build_queue: deque[str] = deque()
        self._scope_build_rel_to_item: dict[str, QTreeWidgetItem] = {}
        self._scope_build_total = 0
        self._scope_build_done = 0
        self._scope_build_root_name = ""
        self._scope_build_active = False
        self._scope_children_map: dict[str, list[str]] = {}
        self._scope_materialized_paths: set[str] = set()
        self._scope_expand_token = 0
        self._search_apply_timer = QTimer(self)
        self._search_apply_timer.setSingleShot(True)
        self._search_apply_timer.setInterval(180)
        self._search_apply_timer.timeout.connect(self._apply_filters_to_table)
        self._last_apply_duration_ms = 0.0
        self._diff_dataset_version = 0
        self._scope_filter_cache_key: tuple[int, str, tuple[str, ...]] | None = None
        self._scope_filter_cache_entries: list[DiffEntry] = []
        self._scope_filter_status_groups: dict[str, list[DiffEntry]] = {status: [] for status in STATUSES}
        self._scope_filter_counts: dict[str, int] = {status: 0 for status in STATUSES}
        self._pending_initial_snapshot_project_id: str | None = None

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
        self.busy_progress = QProgressBar(self)
        self.busy_progress.setRange(0, 0)
        self.busy_progress.setFixedWidth(180)
        self.busy_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.busy_progress)
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
        self.scope_tree.setUniformRowHeights(True)
        self.scope_tree.itemChanged.connect(self._on_scope_item_changed)
        self.scope_tree.itemExpanded.connect(self._on_scope_item_expanded)
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
        self.summary_group.setExclusive(False)

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
        self.search_box.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_box)

        self.diff_table_model = DiffTableModel(
            status_label=self._status_label,
            format_timestamp=self._format_table_timestamp,
            parent_path_display=self._parent_path_display,
        )
        self.diff_proxy_model = DiffFilterProxyModel()
        self.diff_proxy_model.setSourceModel(self.diff_table_model)

        self.diff_table = QTableView()
        self.diff_table.setModel(self.diff_proxy_model)
        self.diff_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.diff_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.diff_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.diff_table.verticalHeader().setVisible(False)
        self.diff_table.verticalHeader().setDefaultSectionSize(self._diff_row_height())
        self.diff_table.setWordWrap(False)
        self.diff_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diff_table.horizontalHeader().setFixedHeight(44)
        self._configure_diff_table_columns()
        self.diff_table.setSortingEnabled(True)
        self.diff_table.selectionModel().selectionChanged.connect(self._on_diff_selection_changed)
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
            QLineEdit, QComboBox, QTreeWidget, QTableView, QListWidget, QPlainTextEdit {{
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
        self._update_scope_path_label()
        self.search_box.setPlaceholderText(self._t("search.placeholder"))
        self.diff_table_model.set_headers(
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
        self.diff_table.verticalHeader().setDefaultSectionSize(self._diff_row_height())

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

    def _is_busy(self) -> bool:
        return self._busy_task_id is not None or self._scope_build_active

    def _set_primary_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.compare_button,
            self.snapshot_button,
            self.history_button,
            self.project_selector,
            self.project_menu_button,
            self.base_selector,
            self.compare_selector,
            self.date_compare_button,
        ):
            widget.setEnabled(enabled)

    def _set_busy(self, active: bool, message: str = "") -> None:
        self.busy_progress.setVisible(active)
        self._set_primary_controls_enabled(not active)
        if active and message:
            self.statusBar().showMessage(message)

    def _start_background_task(
        self,
        *,
        task_name: str,
        status_message: str,
        fn,
        on_success: Callable[[object], None],
        on_failure: Callable[[str], None] | None = None,
        allow_when_busy: bool = False,
        modal_title: str | None = None,
        modal_label: str | None = None,
    ) -> bool:
        if self._is_busy() and not allow_when_busy:
            self.statusBar().showMessage(self._t("msg.busy_wait"), 3000)
            return False

        self._task_counter += 1
        task_id = f"{task_name}_{self._task_counter}"
        self._task_callbacks[task_id] = (on_success, on_failure)
        self._task_messages[task_id] = status_message
        self._busy_task_id = task_id
        self._set_busy(True, status_message)
        if modal_title:
            progress = QProgressDialog(modal_label or status_message, "", 0, 0, self)
            progress.setWindowTitle(modal_title)
            progress.setCancelButton(None)
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setValue(0)
            progress.show()
            self._task_progress_dialogs[task_id] = progress

        runner = _TaskRunner(task_id, fn)
        runner.signals.finished.connect(self._on_background_task_finished)
        runner.signals.failed.connect(self._on_background_task_failed)
        self.thread_pool.start(runner)
        return True

    def _close_task_progress_dialog(self, task_id: str) -> None:
        dialog = self._task_progress_dialogs.pop(task_id, None)
        if dialog is None:
            return
        dialog.close()
        dialog.deleteLater()

    def _on_background_task_finished(self, task_id: str, payload: object) -> None:
        callbacks = self._task_callbacks.pop(task_id, None)
        self._task_messages.pop(task_id, None)
        self._close_task_progress_dialog(task_id)
        if self._busy_task_id == task_id:
            self._busy_task_id = None
            self._set_busy(False)
        if not callbacks:
            return
        on_success, _on_failure = callbacks
        on_success(payload)

    def _on_background_task_failed(self, task_id: str, error_text: str) -> None:
        callbacks = self._task_callbacks.pop(task_id, None)
        status_message = self._task_messages.pop(task_id, self._t("msg.processing_error"))
        self._close_task_progress_dialog(task_id)
        if self._busy_task_id == task_id:
            self._busy_task_id = None
            self._set_busy(False)

        if callbacks and callbacks[1]:
            callbacks[1](error_text)
        else:
            QMessageBox.warning(self, self._t("dialog.validation"), f"{status_message}\n\n{error_text.splitlines()[-1]}")

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

    @staticmethod
    def _scan_scope_paths(root_folder: str) -> list[str]:
        root_path = Path(root_folder)
        if not root_path.exists():
            return []
        paths: list[str] = []
        for directory in root_path.rglob("*"):
            if not directory.is_dir():
                continue
            paths.append(normalize_relpath(str(directory.relative_to(root_path))))
        paths.sort()
        return paths

    def _task_load_project_bundle(self, project_id: str) -> dict[str, object]:
        project = self.project_store.load_project(project_id)
        snapshots = self.snapshot_store.list_snapshots(project)
        scope_paths = self._scan_scope_paths(project.root_folder)
        return {"project": project, "snapshots": snapshots, "scope_paths": scope_paths}

    def _task_load_history_bundle(self, project_id: str) -> dict[str, object]:
        project = self.project_store.load_project(project_id)
        snapshots = self.snapshot_store.list_snapshots(project)
        storage_dir = self.project_store.project_storage_dir(project.project_id)
        compare_logs = self.compare_log_store.list_compare_logs(storage_dir)
        return {"project_id": project.project_id, "snapshots": snapshots, "compare_logs": compare_logs}

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
            if (not self.current_project or self.current_project.project_id != project.project_id) and not self._is_busy():
                self._select_project(project.project_id)
            if self.base_selector.count() == 0:
                self.base_selector.setCurrentIndex(-1)
            if self.compare_selector.count() == 0:
                self.compare_selector.setCurrentIndex(-1)
            self._pending_initial_snapshot_project_id = project.project_id
            created_message = self._t("msg.project_created_no_snapshot", name=project.name)
            QTimer.singleShot(0, lambda msg=created_message: self.statusBar().showMessage(msg, 8000))
            QTimer.singleShot(200, self._maybe_prompt_initial_snapshot_save)
            return

        if initial:
            retry = QMessageBox.question(
                self,
                self._t("dialog.setup.initial"),
                self._t("msg.setup_required"),
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close,
                QMessageBox.StandardButton.Retry,
            )
            if retry == QMessageBox.StandardButton.Retry:
                QTimer.singleShot(0, lambda: self._create_project_with_dialog(initial=True))
            else:
                self.close()

    def _maybe_prompt_initial_snapshot_save(self) -> None:
        project_id = self._pending_initial_snapshot_project_id
        if not project_id:
            return
        if self._is_busy():
            QTimer.singleShot(200, self._maybe_prompt_initial_snapshot_save)
            return
        if not self.current_project or self.current_project.project_id != project_id:
            if self.project_selector.currentData() != project_id:
                self._pending_initial_snapshot_project_id = None
                return
            QTimer.singleShot(200, self._maybe_prompt_initial_snapshot_save)
            return
        if self.snapshots:
            self._pending_initial_snapshot_project_id = None
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle(self._t("dialog.initial_snapshot.title"))
        message.setText(self._t("dialog.initial_snapshot.text"))
        save_button = message.addButton(self._t("dialog.initial_snapshot.save"), QMessageBox.ButtonRole.AcceptRole)
        later_button = message.addButton(self._t("dialog.initial_snapshot.later"), QMessageBox.ButtonRole.RejectRole)
        message.setDefaultButton(save_button)
        message.exec()

        clicked = message.clickedButton()
        self._pending_initial_snapshot_project_id = None
        if clicked == save_button:
            self._start_snapshot_save(
                name=self.current_project.name,
                source_folder=None,
                set_compare=True,
                set_base=True,
            )
            return
        self.base_selector.setCurrentIndex(-1)
        self.compare_selector.setCurrentIndex(-1)
        self.statusBar().showMessage(self._t("msg.project_created_no_snapshot", name=self.current_project.name), 8000)

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
        self.base_selector.setEnabled(False)
        self.compare_selector.setEnabled(False)

        requested_project_id = str(project_id)

        def _on_loaded(payload: object) -> None:
            bundle = payload if isinstance(payload, dict) else {}
            project = bundle.get("project")
            if not isinstance(project, ProjectConfig):
                return
            if self.project_selector.currentData() != project.project_id:
                return
            self.current_project = project

            scope_paths = bundle.get("scope_paths", [])
            if isinstance(scope_paths, list):
                self._apply_scope_tree_paths([str(item) for item in scope_paths])

            snapshots = bundle.get("snapshots", [])
            if isinstance(snapshots, list):
                self._apply_snapshot_records([item for item in snapshots if isinstance(item, SnapshotRecord)])
            self.compare_logs = []
            self.history_panel.set_compares([])
            self._history_dirty = True

            if not self.snapshots:
                self.statusBar().showMessage(self._t("msg.project_loaded_empty", name=project.name), 8000)
                self._maybe_prompt_initial_snapshot_save()
                return
            self.statusBar().showMessage(self._t("msg.project_loaded", name=project.name))
            self._maybe_prompt_initial_snapshot_save()

        self._start_background_task(
            task_name="project_load",
            status_message=self._t("msg.loading_project"),
            fn=lambda pid=requested_project_id: self._task_load_project_bundle(pid),
            on_success=_on_loaded,
        )

    def _apply_snapshot_records(self, snapshots: list[SnapshotRecord]) -> None:
        self.snapshots = snapshots
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

        if self.current_project and self.current_project.last_base_snapshot_id:
            self._set_combo_value(self.base_selector, self.current_project.last_base_snapshot_id)
        if self.current_project and self.current_project.last_compare_snapshot_id:
            self._set_combo_value(self.compare_selector, self.current_project.last_compare_snapshot_id)
        if self.base_selector.count() == 0:
            self.base_selector.setCurrentIndex(-1)
        if self.compare_selector.count() == 0:
            self.compare_selector.setCurrentIndex(-1)
        if not self._is_busy():
            self.base_selector.setEnabled(True)
            self.compare_selector.setEnabled(True)
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
        self.current_status_filter = "all"
        self._scope_dataset_model_key = None
        self._suppress_selection_events = True
        self.filter_all_button.setChecked(True)
        for button in self.summary_buttons.values():
            button.setChecked(False)
        self._suppress_selection_events = False
        self.latest_counts = {status: 0 for status in STATUSES}
        self._invalidate_diff_dataset_cache()
        self.base_manifest = None
        self.compare_manifest = None
        self.current_path_label.setText(self._t("label.path_whole"))
        self.preview_info.setText(self._t("preview.info.empty"))
        self.base_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
        self.compare_preview.show_file(None, empty_message=self._t("preview.none"), modified_time=None, size=None)
        self.diff_proxy_model.set_scope("whole", tuple())
        self.diff_proxy_model.set_status_mode("all")
        self.diff_proxy_model.set_search_text("")
        self.diff_table_model.set_entries([])
        self._update_summary_counts(self.latest_counts)

    def _reset_project_view_state(self) -> None:
        self.current_project = None
        self.snapshots = []
        self.compare_logs = []
        self.base_manifest = None
        self.compare_manifest = None
        self._scope_checked_paths = set()
        self._scope_children_map = {}
        self._scope_materialized_paths = set()
        self._scope_expand_token += 1
        self._history_dirty = True
        self.last_compare_csv_path = None
        self.base_selector.blockSignals(True)
        self.compare_selector.blockSignals(True)
        self.base_selector.clear()
        self.compare_selector.clear()
        self.base_selector.setCurrentIndex(-1)
        self.compare_selector.setCurrentIndex(-1)
        self.base_selector.blockSignals(False)
        self.compare_selector.blockSignals(False)
        self.scope_tree.clear()
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
        self._start_snapshot_save(
            name=name,
            source_folder=None,
            set_compare=True,
            set_base=len(self.snapshots) == 0,
        )

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
        self._start_snapshot_save(
            name=snapshot_name,
            source_folder=picked,
            set_compare=True,
            set_base=len(self.snapshots) == 0,
        )

    def _task_save_snapshot(self, project_id: str, name: str, source_folder: str | None) -> dict[str, object]:
        project = self.project_store.load_project(project_id)
        settings_copy = copy.deepcopy(self.settings)
        snapshot = self.snapshot_store.save_snapshot(
            project,
            settings=settings_copy,
            name=name,
            source_folder=source_folder,
        )
        snapshots = self.snapshot_store.list_snapshots(project)
        root_path = Path(project.root_folder).resolve()
        source_path = Path(source_folder or project.root_folder).resolve()
        scope_paths: list[str] | None = None
        if source_path == root_path:
            scope_paths = self._scan_scope_paths(project.root_folder)
        return {
            "project_id": project_id,
            "snapshot": snapshot,
            "snapshots": snapshots,
            "scope_paths": scope_paths,
            "is_external_source": source_path != root_path,
        }

    def _start_snapshot_save(
        self,
        *,
        name: str,
        source_folder: str | None,
        set_compare: bool,
        set_base: bool = False,
    ) -> None:
        if not self.current_project:
            return
        project_id = self.current_project.project_id
        message_key = "msg.saving_snapshot"
        self._start_background_task(
            task_name="snapshot_save",
            status_message=self._t(message_key),
            fn=lambda pid=project_id, snap_name=name, src=source_folder: self._task_save_snapshot(pid, snap_name, src),
            on_success=lambda payload, assign=set_compare, assign_base=set_base: self._on_snapshot_save_finished(payload, assign, assign_base),
            modal_title=self._t("dialog.snapshot_progress.title"),
            modal_label=self._t("dialog.snapshot_progress.text"),
        )

    def _on_snapshot_save_finished(self, payload: object, set_compare: bool, set_base: bool) -> None:
        bundle = payload if isinstance(payload, dict) else {}
        if not self.current_project:
            return
        if bundle.get("project_id") != self.current_project.project_id:
            return
        snapshot = bundle.get("snapshot")
        if not isinstance(snapshot, SnapshotRecord):
            return
        previous_base_id = self.base_selector.currentData()
        had_snapshots_before = len(self.snapshots) > 0
        snapshots = bundle.get("snapshots", [])
        if isinstance(snapshots, list):
            self._apply_snapshot_records([item for item in snapshots if isinstance(item, SnapshotRecord)])
        if set_base:
            self._set_combo_value(self.base_selector, snapshot.snapshot_id)
        elif not had_snapshots_before:
            self._set_combo_value(self.base_selector, snapshot.snapshot_id)
        elif previous_base_id:
            self._set_combo_value(self.base_selector, str(previous_base_id))
        if set_compare:
            self._set_combo_value(self.compare_selector, snapshot.snapshot_id)

        scope_paths = bundle.get("scope_paths")
        if isinstance(scope_paths, list):
            self._apply_scope_tree_paths([str(item) for item in scope_paths])

        self._history_dirty = True
        if bool(bundle.get("is_external_source")):
            self.statusBar().showMessage(self._t("msg.external_snapshot_created", name=snapshot.name))
            return
        self.statusBar().showMessage(self._t("msg.snapshot_saved", name=snapshot.name))

    def _current_scope_mode(self) -> str:
        if self.mode_selected.isChecked():
            return "selected"
        return "whole"

    def _selected_scope_folders(self) -> list[str]:
        mode = self._current_scope_mode()
        if mode == "whole":
            return []
        selected = self._capture_scope_checks()
        preserved_unmaterialized = {path for path in self._scope_checked_paths if path not in self._scope_materialized_paths}
        normalized = {normalize_relpath(item) for item in selected.union(preserved_unmaterialized)}
        if "" in normalized:
            unique = [""]
        else:
            unique = sorted({item for item in normalized if item.strip()})
        self._scope_checked_paths = set(unique)
        return unique

    def _update_scope_path_label(self) -> None:
        mode = self._current_scope_mode()
        if mode == "whole":
            self.current_path_label.setText(self._t("label.path_whole"))
            return
        selected = self._selected_scope_folders()
        if selected:
            if "" in selected:
                self.current_path_label.setText(self._t("label.path_whole"))
                return
            self.current_path_label.setText(f"Path: {', '.join(selected)}")
            return
        self.current_path_label.setText(f"Path: {self._t('msg.scope_selected_none')}")

    def _capture_scope_checks(self) -> set[str]:
        checked: set[str] = set()
        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel = item.data(0, Qt.ItemDataRole.UserRole)
            if item.data(0, Qt.ItemDataRole.CheckStateRole) is not None:
                if item.checkState(0) == Qt.CheckState.Checked:
                    checked.add("" if rel is None else normalize_relpath(str(rel)))
            iterator += 1
        return checked

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

        project_id = self.current_project.project_id
        selected_base_id = str(base_id)
        selected_compare_id = str(compare_id)
        scope_mode = self._current_scope_mode()
        scope_folders = self._selected_scope_folders()

        self._start_background_task(
            task_name="compare_preflight",
            status_message=self._t("msg.preparing_compare"),
            fn=lambda pid=project_id: self._task_is_current_root_unsaved(pid),
            on_success=lambda payload, pid=project_id, b=selected_base_id, c=selected_compare_id, mode=scope_mode, folders=scope_folders: self._on_compare_preflight_finished(
                pid,
                b,
                c,
                mode,
                folders,
                bool(payload),
            ),
        )

    def _on_compare_preflight_finished(
        self,
        project_id: str,
        base_id: str,
        compare_id: str,
        scope_mode: str,
        scope_folders: list[str],
        unsaved: bool,
    ) -> None:
        if not self.current_project or self.current_project.project_id != project_id:
            return
        if unsaved:
            decision = self._ask_compare_with_unsaved_state()
            if decision == "cancel":
                return
            if decision == "save":
                self._start_save_and_compare_task(project_id, base_id, scope_mode, scope_folders)
                return
        self._start_compare_task(project_id, base_id, compare_id, scope_mode, scope_folders)

    def _task_is_current_root_unsaved(self, project_id: str) -> bool:
        project = self.project_store.load_project(project_id)
        root = Path(project.root_folder).resolve()
        try:
            current_scan = scan_folder(str(root), project.exclude_rules)
        except Exception:
            return False
        current_map = {item.relative_path: (item.size, item.modified_time) for item in current_scan}
        snapshots = self.snapshot_store.list_snapshots(project)

        latest_root_snapshot: SnapshotRecord | None = None
        for snapshot in snapshots:
            if Path(snapshot.source_folder).resolve() == root:
                latest_root_snapshot = snapshot
                break

        if latest_root_snapshot is None:
            return len(current_map) > 0

        manifest = self.snapshot_store.load_manifest(project, latest_root_snapshot.snapshot_id)
        snapshot_map = {item.relative_path: (item.size, item.modified_time) for item in manifest.files}
        return current_map != snapshot_map

    def _task_compare(
        self,
        project_id: str,
        base_id: str,
        compare_id: str,
        scope_mode: str,
        scope_folders: list[str],
    ) -> dict[str, object]:
        project = self.project_store.load_project(project_id)
        base_manifest = self.snapshot_store.load_manifest(project, base_id)
        compare_manifest = self.snapshot_store.load_manifest(project, compare_id)
        result = compare_snapshots(
            base_manifest,
            compare_manifest,
            scope_mode="whole",
            scope_folders=[],
        )

        storage_dir = self.project_store.project_storage_dir(project.project_id)
        self.compare_log_store.save_compare_log(
            project=project,
            project_storage_dir=storage_dir,
            base_snapshot_id=base_id,
            compare_snapshot_id=compare_id,
            scope_mode=scope_mode,
            scope_folders=scope_folders,
            result=result,
        )
        csv_path = write_compare_csv_file(
            project_storage_dir=storage_dir,
            project_name=project.name,
            base_snapshot_id=base_id,
            compare_snapshot_id=compare_id,
            entries=result.entries,
        )
        project.last_base_snapshot_id = base_id
        project.last_compare_snapshot_id = compare_id
        self.project_store.save_project(project)
        return {
            "project_id": project_id,
            "base_id": base_id,
            "compare_id": compare_id,
            "base_manifest": base_manifest,
            "compare_manifest": compare_manifest,
            "entries": result.entries,
            "csv_path": csv_path,
        }

    def _task_save_and_compare(
        self,
        project_id: str,
        base_id: str,
        scope_mode: str,
        scope_folders: list[str],
    ) -> dict[str, object]:
        project = self.project_store.load_project(project_id)
        settings_copy = copy.deepcopy(self.settings)
        snapshot = self.snapshot_store.save_snapshot(
            project,
            settings=settings_copy,
            name=f"compare_{project.name}",
            source_folder=project.root_folder,
        )
        payload = self._task_compare(project_id, base_id, snapshot.snapshot_id, scope_mode, scope_folders)
        payload["saved_snapshot_id"] = snapshot.snapshot_id
        payload["snapshots"] = self.snapshot_store.list_snapshots(project)
        payload["scope_paths"] = self._scan_scope_paths(project.root_folder)
        return payload

    def _start_compare_task(
        self,
        project_id: str,
        base_id: str,
        compare_id: str,
        scope_mode: str,
        scope_folders: list[str],
    ) -> None:
        self._start_background_task(
            task_name="compare_run",
            status_message=self._t("msg.comparing"),
            fn=lambda pid=project_id, b=base_id, c=compare_id, mode=scope_mode, folders=list(scope_folders): self._task_compare(
                pid,
                b,
                c,
                mode,
                folders,
            ),
            on_success=self._on_compare_task_finished,
        )

    def _start_save_and_compare_task(
        self,
        project_id: str,
        base_id: str,
        scope_mode: str,
        scope_folders: list[str],
    ) -> None:
        self._start_background_task(
            task_name="save_and_compare",
            status_message=self._t("msg.saving_and_comparing"),
            fn=lambda pid=project_id, b=base_id, mode=scope_mode, folders=list(scope_folders): self._task_save_and_compare(
                pid,
                b,
                mode,
                folders,
            ),
            on_success=self._on_compare_task_finished,
            modal_title=self._t("dialog.snapshot_progress.title"),
            modal_label=self._t("dialog.snapshot_progress.save_compare"),
        )

    def _on_compare_task_finished(self, payload: object) -> None:
        bundle = payload if isinstance(payload, dict) else {}
        if not self.current_project:
            return
        if bundle.get("project_id") != self.current_project.project_id:
            return

        base_manifest = bundle.get("base_manifest")
        compare_manifest = bundle.get("compare_manifest")
        entries = bundle.get("entries", [])
        csv_path = bundle.get("csv_path")
        if not isinstance(base_manifest, SnapshotManifest) or not isinstance(compare_manifest, SnapshotManifest):
            return
        if not isinstance(entries, list):
            return

        self.base_manifest = base_manifest
        self.compare_manifest = compare_manifest
        self.diff_entries = [item for item in entries if isinstance(item, DiffEntry)]
        self._invalidate_diff_dataset_cache()
        self._set_default_changed_filter_state()
        self._update_scope_badges(self.diff_entries)

        base_id = bundle.get("base_id")
        compare_id = bundle.get("compare_id")
        if isinstance(base_id, str):
            self._set_combo_value(self.base_selector, base_id)
            self.current_project.last_base_snapshot_id = base_id
        if isinstance(compare_id, str):
            self._set_combo_value(self.compare_selector, compare_id)
            self.current_project.last_compare_snapshot_id = compare_id

        saved_snapshot_id = bundle.get("saved_snapshot_id")
        snapshots = bundle.get("snapshots")
        if isinstance(snapshots, list):
            self._apply_snapshot_records([item for item in snapshots if isinstance(item, SnapshotRecord)])
        if isinstance(saved_snapshot_id, str):
            self._set_combo_value(self.compare_selector, saved_snapshot_id)

        scope_paths = bundle.get("scope_paths")
        if isinstance(scope_paths, list):
            self._apply_scope_tree_paths([str(item) for item in scope_paths])

        if isinstance(csv_path, str):
            self.last_compare_csv_path = csv_path
            self.statusBar().showMessage(
                self._t("msg.compare_done_csv_path", name=Path(csv_path).name, path=csv_path),
                12000,
            )
        else:
            self.statusBar().showMessage(self._t("msg.compare_done"), 5000)
        self._history_dirty = True
        if self.history_dock.isVisible() and not self._scope_build_active:
            self._ensure_history_loaded(force=True)

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

    def _status_label(self, status: str) -> str:
        return self._t(f"status.{status}")

    @staticmethod
    def _status_sort_rank(status: str) -> int:
        order = {
            "added": 0,
            "removed": 1,
            "modified": 2,
            "unchanged": 3,
        }
        return order.get(status, 99)

    def _format_table_timestamp(self, value: str | None) -> str:
        return format_display_timestamp(value)

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

    def _ordered_entries_for_view(self, entries: list[DiffEntry]) -> list[DiffEntry]:
        # Keep compare semantics unchanged and adjust only UI-visible grouping order.
        return sorted(
            entries,
            key=lambda item: (self._status_sort_rank(item.status), item.relative_path, item.file_name),
        )

    @staticmethod
    def _entry_key(entry: DiffEntry) -> tuple[str, str, str]:
        return (entry.relative_path, entry.status, entry.file_name)

    def _invalidate_diff_dataset_cache(self) -> None:
        self._diff_dataset_version += 1
        self._scope_filter_cache_key = None
        self._scope_dataset_model_key = None
        self._scope_filter_cache_entries = []
        self._scope_filter_status_groups = {status: [] for status in STATUSES}
        self._scope_filter_counts = {status: 0 for status in STATUSES}

    def _resolve_scope_filter_bundle(
        self,
        *,
        scope_mode: str,
        scope_folders: tuple[str, ...],
    ) -> tuple[list[DiffEntry], dict[str, list[DiffEntry]], dict[str, int]]:
        mode = scope_mode if scope_mode == "selected" else "whole"
        folders = scope_folders if mode == "selected" else tuple()
        cache_key = (self._diff_dataset_version, mode, folders)
        if self._scope_filter_cache_key == cache_key:
            return self._scope_filter_cache_entries, self._scope_filter_status_groups, self._scope_filter_counts

        if mode == "whole" or not folders or "" in folders:
            scope_entries = list(self.diff_entries)
        else:
            folder_list = list(folders)
            scope_entries = []
            for entry in self.diff_entries:
                rel = normalize_relpath(entry.relative_path)
                for folder in folder_list:
                    if rel == folder or rel.startswith(f"{folder}/"):
                        scope_entries.append(entry)
                        break

        status_groups = {status: [] for status in STATUSES}
        for entry in scope_entries:
            bucket = status_groups.get(entry.status)
            if bucket is not None:
                bucket.append(entry)
        counts = {status: len(status_groups.get(status, [])) for status in STATUSES}

        self._scope_filter_cache_key = cache_key
        self._scope_filter_cache_entries = scope_entries
        self._scope_filter_status_groups = status_groups
        self._scope_filter_counts = counts
        return scope_entries, status_groups, counts

    def _set_status_filter(self, status: str) -> None:
        self.current_status_filter = status
        self._sync_status_buttons(status)
        self._apply_filters_to_table()

    def _sync_status_buttons(self, status: str) -> None:
        if status == "all":
            self.filter_all_button.setChecked(True)
            for button in self.summary_buttons.values():
                button.setChecked(False)
            return
        if status == "changed_default":
            self.filter_all_button.setChecked(False)
            for key, button in self.summary_buttons.items():
                button.setChecked(key in {"added", "removed", "modified"})
            return
        self.filter_all_button.setChecked(False)
        for key, button in self.summary_buttons.items():
            button.setChecked(key == status)

    def _set_default_changed_filter_state(self) -> None:
        self.current_status_filter = "changed_default"
        self._sync_status_buttons("changed_default")
        self._apply_filters_to_table()

    def _on_search_text_changed(self) -> None:
        # Debounce search-triggered rebinding for large datasets.
        self._search_apply_timer.start()

    def _apply_filters_to_table(self) -> None:
        apply_start = perf_counter()
        current_key = None
        if self.current_entry:
            current_key = (self.current_entry.relative_path, self.current_entry.status, self.current_entry.file_name)

        scope_mode = self._current_scope_mode()
        scope_folders = tuple(self._selected_scope_folders()) if scope_mode == "selected" else tuple()
        _scope_entries, _status_groups, scope_counts = self._resolve_scope_filter_bundle(
            scope_mode=scope_mode,
            scope_folders=scope_folders,
        )
        self.latest_counts = dict(scope_counts)
        self._update_summary_counts(self.latest_counts)
        self._update_scope_path_label()

        if self._scope_dataset_model_key != self._diff_dataset_version:
            self.diff_table_model.set_entries(self._ordered_entries_for_view(self.diff_entries))
            self._scope_dataset_model_key = self._diff_dataset_version

        self.diff_proxy_model.set_scope(scope_mode, scope_folders)
        self.diff_proxy_model.set_status_mode(self.current_status_filter)
        self.diff_proxy_model.set_search_text(self.search_box.text())
        if self.current_status_filter in {"all", "changed_default"}:
            self.diff_table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        visible_count = self.diff_proxy_model.rowCount()
        self.visible_entries = []

        if visible_count <= 0:
            self.current_entry = None
            self._update_preview(None)
            self._last_apply_duration_ms = (perf_counter() - apply_start) * 1000.0
            LOGGER.debug("diff table apply complete: rows=%d elapsed_ms=%.2f", 0, self._last_apply_duration_ms)
            return

        target_row = self._find_proxy_row_for_key(current_key) if current_key else None
        if target_row is None:
            target_row = 0
        self._suppress_selection_events = True
        self.diff_table.selectRow(target_row)
        self._suppress_selection_events = False
        selected_entry = self._entry_from_proxy_row(target_row)
        self.current_entry = selected_entry
        self._update_preview(selected_entry)
        self._last_apply_duration_ms = (perf_counter() - apply_start) * 1000.0
        LOGGER.debug(
            "diff table apply complete: rows=%d elapsed_ms=%.2f filter=%s",
            visible_count,
            self._last_apply_duration_ms,
            self.current_status_filter,
        )

    def _entry_from_proxy_index(self, proxy_index: QModelIndex) -> DiffEntry | None:
        if not proxy_index.isValid():
            return None
        source_index = self.diff_proxy_model.mapToSource(proxy_index)
        if not source_index.isValid():
            return None
        entry = source_index.data(DiffTableModel.ENTRY_ROLE)
        if isinstance(entry, DiffEntry):
            return entry
        return self.diff_table_model.entry_at(source_index.row())

    def _entry_from_proxy_row(self, row: int) -> DiffEntry | None:
        return self._entry_from_proxy_index(self.diff_proxy_model.index(row, 0))

    def _find_proxy_row_for_key(self, key: tuple[str, str, str] | None) -> int | None:
        if key is None:
            return None
        source_index = self.diff_table_model.source_index_for_key(key)
        if not source_index.isValid():
            return None
        proxy_index = self.diff_proxy_model.mapFromSource(source_index)
        if not proxy_index.isValid():
            return None
        return proxy_index.row()

    def _on_diff_selection_changed(self, *_args) -> None:
        if self._suppress_selection_events:
            return
        selection_model = self.diff_table.selectionModel()
        if selection_model is None:
            return
        selected = selection_model.selectedRows()
        if not selected:
            return
        entry = self._entry_from_proxy_index(selected[0])
        if entry is None:
            return
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

    def _apply_scope_tree_paths(self, scope_paths: list[str]) -> None:
        checked_paths: set[str] = set(self._scope_checked_paths)
        checked_paths.update(self._capture_scope_checks())
        self._scope_checked_paths = {normalize_relpath(path) for path in checked_paths}

        self._scope_build_token += 1
        token = self._scope_build_token
        self._scope_expand_token += 1
        self._scope_build_active = True
        self._set_busy(True, self._t("msg.loading_scope_tree"))

        children_map: dict[str, list[str]] = {}
        for raw_rel in scope_paths:
            rel = normalize_relpath(str(raw_rel))
            if not rel or rel == ".":
                continue
            parent_rel = normalize_relpath(str(Path(rel).parent)) if "/" in rel else ""
            if parent_rel == ".":
                parent_rel = ""
            children_map.setdefault(parent_rel, []).append(rel)
        self._scope_children_map = children_map

        self.scope_tree.blockSignals(True)
        self.scope_tree.clear()
        if not self.current_project:
            self.scope_tree.blockSignals(False)
            self._scope_build_active = False
            self._set_busy(False)
            return

        root_path = Path(self.current_project.root_folder)
        self._scope_build_root_name = root_path.name or str(root_path)
        root_item = QTreeWidgetItem([self._scope_build_root_name])
        root_item.setData(0, Qt.ItemDataRole.UserRole, "")
        root_item.setData(0, Qt.ItemDataRole.UserRole + 1, self._scope_build_root_name)
        root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        root_item.setCheckState(0, Qt.CheckState.Checked if "" in self._scope_checked_paths else Qt.CheckState.Unchecked)
        root_item.setData(0, Qt.ItemDataRole.UserRole + 2, True)
        self.scope_tree.addTopLevelItem(root_item)

        self._scope_build_rel_to_item = {"": root_item}
        self._scope_materialized_paths = {""}
        self._scope_build_queue = deque(self._scope_children_map.get("", []))
        self._scope_build_total = len(self._scope_build_queue)
        self._scope_build_done = 0
        self.scope_tree.setEnabled(False)
        QTimer.singleShot(0, lambda t=token: self._process_scope_tree_chunk(t))

    def _process_scope_tree_chunk(self, token: int) -> None:
        if token != self._scope_build_token:
            return
        chunk_size = 500
        processed = 0
        root_item = self._scope_build_rel_to_item.get("")
        if root_item is None:
            return
        while self._scope_build_queue and processed < chunk_size:
            rel = normalize_relpath(self._scope_build_queue.popleft())
            if not rel or rel == ".":
                processed += 1
                continue
            self._create_scope_tree_item(parent_item=root_item, rel=rel)
            processed += 1
            self._scope_build_done += 1

        if self._scope_build_queue:
            self.statusBar().showMessage(
                self._t("msg.loading_scope_tree_progress", done=self._scope_build_done, total=self._scope_build_total)
            )
            QTimer.singleShot(0, lambda t=token: self._process_scope_tree_chunk(t))
            return

        root_item.setExpanded(True)
        self._apply_scope_tree_mode_visuals()
        self.scope_tree.blockSignals(False)
        self.scope_tree.setEnabled(True)
        self._scope_build_active = False
        self._set_busy(False)
        self._update_scope_path_label()
        self._update_scope_badges(self.diff_entries)
        if self.history_dock.isVisible() and self._history_dirty:
            self._ensure_history_loaded()

    def _create_scope_tree_item(self, *, parent_item: QTreeWidgetItem, rel: str) -> QTreeWidgetItem | None:
        rel_normalized = normalize_relpath(rel)
        if rel_normalized in self._scope_materialized_paths:
            return self._scope_build_rel_to_item.get(rel_normalized)

        item = QTreeWidgetItem([Path(rel_normalized).name])
        item.setCheckState(0, Qt.CheckState.Checked if rel_normalized in self._scope_checked_paths else Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, rel_normalized)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, Path(rel_normalized).name)

        child_paths = self._scope_children_map.get(rel_normalized, [])
        children_loaded = len(child_paths) == 0
        item.setData(0, Qt.ItemDataRole.UserRole + 2, children_loaded)
        parent_item.addChild(item)

        if not children_loaded:
            placeholder = QTreeWidgetItem([""])
            placeholder.setData(0, Qt.ItemDataRole.UserRole + 3, True)
            item.addChild(placeholder)

        self._scope_build_rel_to_item[rel_normalized] = item
        self._scope_materialized_paths.add(rel_normalized)
        return item

    def _on_scope_item_expanded(self, item: QTreeWidgetItem) -> None:
        if self._scope_build_active:
            return
        rel = item.data(0, Qt.ItemDataRole.UserRole)
        if rel is None:
            return
        rel_normalized = normalize_relpath(str(rel))
        if rel_normalized == ".":
            rel_normalized = ""
        if item.data(0, Qt.ItemDataRole.UserRole + 2) is True:
            return

        children = self._scope_children_map.get(rel_normalized, [])
        if not children:
            item.setData(0, Qt.ItemDataRole.UserRole + 2, True)
            return

        item.setData(0, Qt.ItemDataRole.UserRole + 2, "loading")
        for idx in range(item.childCount() - 1, -1, -1):
            child = item.child(idx)
            if child.data(0, Qt.ItemDataRole.UserRole + 3):
                item.removeChild(child)

        self._scope_expand_token += 1
        expand_token = self._scope_expand_token
        QTimer.singleShot(
            0,
            lambda t=expand_token, parent=item, child_rels=list(children), start=0: self._append_scope_children_chunk(
                t,
                parent,
                child_rels,
                start,
            ),
        )

    def _append_scope_children_chunk(
        self,
        token: int,
        parent_item: QTreeWidgetItem,
        children: list[str],
        start: int,
    ) -> None:
        if token != self._scope_expand_token:
            return
        if parent_item.treeWidget() is None:
            return
        if self.current_project is None:
            return

        chunk_size = 300
        end = min(len(children), start + chunk_size)
        for rel in children[start:end]:
            self._create_scope_tree_item(parent_item=parent_item, rel=rel)

        if end < len(children):
            QTimer.singleShot(
                0,
                lambda t=token, parent=parent_item, child_rels=children, next_start=end: self._append_scope_children_chunk(
                    t,
                    parent,
                    child_rels,
                    next_start,
                ),
            )
            return

        parent_item.setData(0, Qt.ItemDataRole.UserRole + 2, True)
        self._apply_scope_tree_mode_visuals()
        self._update_scope_badges(self.diff_entries)

    def _request_scope_tree_refresh(self) -> None:
        if not self.current_project:
            return
        project_id = self.current_project.project_id
        root_folder = self.current_project.root_folder

        def _on_loaded(payload: object) -> None:
            if not self.current_project or self.current_project.project_id != project_id:
                return
            paths = payload if isinstance(payload, list) else []
            self._apply_scope_tree_paths([str(item) for item in paths])

        self._start_background_task(
            task_name="scope_refresh",
            status_message=self._t("msg.loading_scope_tree"),
            fn=lambda root=root_folder: self._scan_scope_paths(root),
            on_success=_on_loaded,
        )

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
        if self._current_scope_mode() == "whole":
            self._scope_checked_paths.update(self._capture_scope_checks())
        self._apply_scope_tree_mode_visuals()
        self._update_scope_path_label()
        self._apply_filters_to_table()
        if self._current_scope_mode() == "selected" and not self._selected_scope_folders() and self.diff_entries:
            self.statusBar().showMessage(self._t("msg.scope_need_checked"), 4000)

    def _on_scope_item_changed(self, changed: QTreeWidgetItem, _column: int) -> None:
        if self._current_scope_mode() != "selected":
            return
        rel = changed.data(0, Qt.ItemDataRole.UserRole)
        if rel is None:
            return
        current = self._capture_scope_checks()
        preserved_unmaterialized = {path for path in self._scope_checked_paths if path not in self._scope_materialized_paths}
        self._scope_checked_paths = {normalize_relpath(path) for path in current.union(preserved_unmaterialized)}
        self._update_scope_path_label()
        self._apply_filters_to_table()
        if not self._selected_scope_folders() and self.diff_entries:
            self.statusBar().showMessage(self._t("msg.scope_need_checked"), 4000)

    def _apply_scope_tree_mode_visuals(self) -> None:
        selected_mode = self._current_scope_mode() == "selected"
        was_blocked = self.scope_tree.signalsBlocked()
        if not was_blocked:
            self.scope_tree.blockSignals(True)
        iterator = QTreeWidgetItemIterator(self.scope_tree)
        while iterator.value():
            item = iterator.value()
            rel = item.data(0, Qt.ItemDataRole.UserRole)
            flags = item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
            if selected_mode and rel is not None:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setData(
                    0,
                    Qt.ItemDataRole.CheckStateRole,
                    Qt.CheckState.Checked if normalize_relpath(str(rel)) in self._scope_checked_paths else Qt.CheckState.Unchecked,
                )
            elif rel is not None:
                # Remove the checkbox indicator entirely in whole mode.
                item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
            item.setFlags(flags)
            iterator += 1
        if not was_blocked:
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
            self._ensure_history_loaded()

    def _ensure_history_loaded(self, *, force: bool = False) -> None:
        if not self.current_project:
            return
        if not force and not self._history_dirty:
            return
        project_id = self.current_project.project_id
        self._start_background_task(
            task_name="history_load",
            status_message=self._t("msg.loading_history"),
            fn=lambda pid=project_id: self._task_load_history_bundle(pid),
            on_success=self._on_history_loaded,
        )

    def _on_history_loaded(self, payload: object) -> None:
        bundle = payload if isinstance(payload, dict) else {}
        if not self.current_project:
            return
        if bundle.get("project_id") != self.current_project.project_id:
            return
        snapshots = bundle.get("snapshots", [])
        if isinstance(snapshots, list):
            self.snapshots = [item for item in snapshots if isinstance(item, SnapshotRecord)]
            self.history_panel.set_snapshots(self.snapshots)
        compare_logs = bundle.get("compare_logs", [])
        if isinstance(compare_logs, list):
            self.compare_logs = [item for item in compare_logs if isinstance(item, CompareLogRecord)]
            self.history_panel.set_compares(self.compare_logs)
        self._history_dirty = False

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
        self.mode_whole.blockSignals(True)
        self.mode_selected.blockSignals(True)
        self.mode_selected.setChecked(record.scope_mode == "selected")
        self.mode_whole.setChecked(record.scope_mode != "selected")
        self.mode_whole.blockSignals(False)
        self.mode_selected.blockSignals(False)
        self._scope_checked_paths = {normalize_relpath(path) for path in record.scope_folders}
        self._apply_scope_tree_mode_visuals()
        self.diff_entries = record.entries
        self._invalidate_diff_dataset_cache()
        self._apply_filters_to_table()

    def _open_project_menu(self) -> None:
        if not self.current_project and self.project_selector.count() == 0:
            self._create_project_with_dialog(initial=True)
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu::separator {
                height: 1px;
                background: #d6e0ea;
                margin: 6px 10px 6px 10px;
            }
            """
        )
        create_action = QAction(self._t("project.menu.create"), self)
        create_action.triggered.connect(lambda: self._create_project_with_dialog(initial=False))
        menu.addAction(create_action)

        rename_action = QAction(self._t("project.menu.rename"), self)
        rename_action.triggered.connect(self._rename_project)
        menu.addAction(rename_action)

        menu.addSeparator()

        settings_action = QAction(self._t("project.menu.settings"), self)
        settings_action.triggered.connect(self._edit_project_settings)
        menu.addAction(settings_action)

        root_action = QAction(self._t("project.menu.change_root"), self)
        root_action.triggered.connect(self._change_root_folder)
        menu.addAction(root_action)

        exclude_action = QAction(self._t("project.menu.edit_exclude"), self)
        exclude_action.triggered.connect(self._edit_exclude_rules)
        menu.addAction(exclude_action)

        import_action = QAction(self._t("project.menu.import_external_snapshot"), self)
        import_action.triggered.connect(self._import_external_folder_as_snapshot)
        menu.addAction(import_action)

        menu.addSeparator()

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

        menu.addSeparator()

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
        self._request_scope_tree_refresh()

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
        return write_compare_csv_file(
            project_storage_dir=project_storage_dir,
            project_name=self.current_project.name if self.current_project else "project",
            base_snapshot_id=base_snapshot_id,
            compare_snapshot_id=compare_snapshot_id,
            entries=entries,
        )

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
        self.diff_table.verticalHeader().setDefaultSectionSize(self._diff_row_height())
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
