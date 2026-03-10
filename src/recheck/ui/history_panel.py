from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from recheck.core.models import CompareLogRecord, SnapshotRecord


class HistoryPanel(QWidget):
    set_base_requested = Signal(str)
    set_compare_requested = Signal(str)
    open_compare_requested = Signal(str)
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot_by_id: dict[str, SnapshotRecord] = {}
        self._compare_by_id: dict[str, CompareLogRecord] = {}

        layout = QVBoxLayout(self)
        title_row = QHBoxLayout()
        title = QLabel("History")
        title.setObjectName("historyTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close_requested.emit)
        title_row.addWidget(close_button)
        layout.addLayout(title_row)

        layout.addWidget(QLabel("Snapshots"))
        self.snapshot_list = QListWidget()
        layout.addWidget(self.snapshot_list, 1)

        snapshot_actions = QHBoxLayout()
        self.base_button = QPushButton("Set Base")
        self.base_button.clicked.connect(self._emit_set_base)
        snapshot_actions.addWidget(self.base_button)
        self.compare_button = QPushButton("Set Compare")
        self.compare_button.clicked.connect(self._emit_set_compare)
        snapshot_actions.addWidget(self.compare_button)
        snapshot_actions.addStretch(1)
        layout.addLayout(snapshot_actions)

        layout.addWidget(QLabel("Saved Compares"))
        self.compare_list = QListWidget()
        layout.addWidget(self.compare_list, 1)

        compare_actions = QHBoxLayout()
        self.open_compare_button = QPushButton("Open Result")
        self.open_compare_button.clicked.connect(self._emit_open_compare)
        compare_actions.addWidget(self.open_compare_button)
        compare_actions.addStretch(1)
        layout.addLayout(compare_actions)

    def set_snapshots(self, snapshots: list[SnapshotRecord]) -> None:
        self._snapshot_by_id = {item.snapshot_id: item for item in snapshots}
        self.snapshot_list.clear()
        for snapshot in snapshots:
            label = f"{snapshot.created_at[:19]} | {snapshot.name} ({snapshot.file_count})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, snapshot.snapshot_id)
            self.snapshot_list.addItem(item)

    def set_compares(self, compares: list[CompareLogRecord]) -> None:
        self._compare_by_id = {item.compare_id: item for item in compares}
        self.compare_list.clear()
        for compare in compares:
            counts = compare.counts
            label = (
                f"{compare.created_at[:19]} | "
                f"{compare.base_snapshot_id} -> {compare.compare_snapshot_id} | "
                f"A:{counts.get('added', 0)} R:{counts.get('removed', 0)} M:{counts.get('modified', 0)} U:{counts.get('unchanged', 0)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, compare.compare_id)
            self.compare_list.addItem(item)

    def _selected_snapshot_id(self) -> str | None:
        item = self.snapshot_list.currentItem()
        if not item:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _selected_compare_id(self) -> str | None:
        item = self.compare_list.currentItem()
        if not item:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _emit_set_base(self) -> None:
        snapshot_id = self._selected_snapshot_id()
        if snapshot_id:
            self.set_base_requested.emit(snapshot_id)

    def _emit_set_compare(self) -> None:
        snapshot_id = self._selected_snapshot_id()
        if snapshot_id:
            self.set_compare_requested.emit(snapshot_id)

    def _emit_open_compare(self) -> None:
        compare_id = self._selected_compare_id()
        if compare_id:
            self.open_compare_requested.emit(compare_id)
