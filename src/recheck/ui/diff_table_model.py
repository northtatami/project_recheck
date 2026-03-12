from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor

from recheck.core.models import DiffEntry


class DiffTableModel(QAbstractTableModel):
    ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 2
    SEARCH_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(
        self,
        *,
        status_label: Callable[[str], str],
        format_timestamp: Callable[[str | None], str],
        parent_path_display: Callable[[str], str],
    ) -> None:
        super().__init__()
        self._status_label = status_label
        self._format_timestamp = format_timestamp
        self._parent_path_display = parent_path_display
        self._entries: list[DiffEntry] = []
        self._headers: list[str] = ["", "", "", "", "", "", ""]
        self._status_backgrounds: dict[str, QBrush] = {
            "added": QBrush(QColor("#e9f6ed")),
            "removed": QBrush(QColor("#faecec")),
            "modified": QBrush(QColor("#ecf3fa")),
            "unchanged": QBrush(QColor("#f2f3f5")),
        }
        self._path_foreground = QBrush(QColor("#5f7387"))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 7

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None
        entry = self._entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return self._status_label(entry.status)
            if col == 1:
                return entry.file_name
            if col == 2:
                return self._parent_path_display(entry.relative_path)
            if col == 3:
                return self._format_timestamp(entry.base_modified_time)
            if col == 4:
                return self._format_timestamp(entry.compare_modified_time)
            if col == 5:
                return "-" if entry.base_size is None else str(entry.base_size)
            if col == 6:
                return "-" if entry.compare_size is None else str(entry.compare_size)
            return None

        if role == Qt.ItemDataRole.ToolTipRole:
            if col in {1, 2}:
                return entry.relative_path
            if col == 3 and entry.base_modified_time:
                return entry.base_modified_time
            if col == 4 and entry.compare_modified_time:
                return entry.compare_modified_time
            return None

        if role == Qt.ItemDataRole.BackgroundRole and col == 0:
            return self._status_backgrounds.get(entry.status)

        if role == Qt.ItemDataRole.ForegroundRole and col == 2:
            return self._path_foreground

        if role == Qt.ItemDataRole.TextAlignmentRole and col in {0, 3, 4, 5, 6}:
            return int(Qt.AlignmentFlag.AlignCenter)

        if role == self.ENTRY_ROLE:
            return entry

        if role == self.STATUS_ROLE:
            return entry.status

        if role == self.SEARCH_ROLE:
            return f"{entry.file_name.lower()}\n{entry.relative_path.lower()}"

        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

    def set_entries(self, entries: list[DiffEntry]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def set_headers(self, headers: list[str]) -> None:
        if len(headers) != 7:
            return
        self._headers = list(headers)
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self._headers) - 1)

    def entry_at(self, row: int) -> DiffEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None


class DiffFilterProxyModel(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self._status_mode = "all"
        self._search_text = ""
        self.setDynamicSortFilter(True)

    def set_status_mode(self, mode: str) -> None:
        if self._status_mode == mode:
            return
        self._status_mode = mode
        self.invalidateFilter()

    def set_search_text(self, text: str) -> None:
        normalized = text.strip().lower()
        if self._search_text == normalized:
            return
        self._search_text = normalized
        self.invalidateFilter()

    def _status_visible(self, status: str) -> bool:
        if self._status_mode == "all":
            return True
        if self._status_mode == "changed_default":
            return status in {"added", "removed", "modified"}
        return status == self._status_mode

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_model = self.sourceModel()
        if source_model is None:
            return False
        index = source_model.index(source_row, 0, source_parent)
        status = index.data(DiffTableModel.STATUS_ROLE)
        if not isinstance(status, str):
            return False
        if not self._status_visible(status):
            return False
        if not self._search_text:
            return True
        search_blob = index.data(DiffTableModel.SEARCH_ROLE)
        if not isinstance(search_blob, str):
            return False
        return self._search_text in search_blob
