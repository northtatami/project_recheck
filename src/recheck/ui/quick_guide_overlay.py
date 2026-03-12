from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


@dataclass
class QuickGuideStep:
    title: str
    message: str
    target_rect: Callable[[], QRect]


class QuickGuideOverlay(QWidget):
    finished = Signal(str)

    def __init__(
        self,
        *,
        parent: QWidget,
        steps: list[QuickGuideStep],
        tr: Callable[[str], str],
    ) -> None:
        super().__init__(parent)
        self._steps = steps
        self._tr = tr
        self._step_index = 0
        self._current_target = QRect()

        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._panel = QFrame(self)
        self._panel.setObjectName("quickGuidePanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        self._step_label = QLabel(self._panel)
        self._step_label.setObjectName("quickGuideStep")
        panel_layout.addWidget(self._step_label)

        self._title_label = QLabel(self._panel)
        self._title_label.setObjectName("quickGuideTitle")
        self._title_label.setWordWrap(True)
        panel_layout.addWidget(self._title_label)

        self._message_label = QLabel(self._panel)
        self._message_label.setObjectName("quickGuideMessage")
        self._message_label.setWordWrap(True)
        panel_layout.addWidget(self._message_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self._skip_button = QPushButton(self._panel)
        self._skip_button.clicked.connect(self._skip)
        button_row.addWidget(self._skip_button)

        button_row.addStretch(1)

        self._next_button = QPushButton(self._panel)
        self._next_button.clicked.connect(self._next)
        button_row.addWidget(self._next_button)

        panel_layout.addLayout(button_row)
        self._panel.setStyleSheet(
            """
            QFrame#quickGuidePanel {
                background: #f8fbff;
                border: 1px solid #b9cde2;
                border-radius: 10px;
            }
            QLabel#quickGuideStep {
                color: #5d7389;
                font-size: 12px;
            }
            QLabel#quickGuideTitle {
                color: #17354f;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#quickGuideMessage {
                color: #304b61;
                font-size: 13px;
            }
            """
        )

        parent.installEventFilter(self)
        self._sync_geometry()
        self._apply_step(0)

    def start(self) -> None:
        self._sync_geometry()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def eventFilter(self, obj: object, event: QEvent) -> bool:
        if obj is self.parentWidget() and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._skip()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        overlay = QColor(12, 22, 36, 122)
        if self._current_target.isValid() and not self._current_target.isNull():
            focus_rect = self._current_target.adjusted(-8, -8, 8, 8)
            # Use an odd-even path mask so the spotlight stays clear without
            # backend-dependent clear-composition artifacts.
            mask = QPainterPath()
            mask.setFillRule(Qt.FillRule.OddEvenFill)
            mask.addRect(self.rect())
            mask.addRoundedRect(focus_rect, 10, 10)
            painter.fillPath(mask, overlay)
            painter.setPen(QPen(QColor("#77b8ff"), 2))
            painter.drawRoundedRect(focus_rect, 10, 10)
            return

        painter.fillRect(self.rect(), overlay)

    def closeEvent(self, event) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        super().closeEvent(event)

    def _apply_step(self, index: int) -> None:
        if not self._steps:
            self.finished.emit("completed")
            self.close()
            return
        self._step_index = max(0, min(index, len(self._steps) - 1))
        step = self._steps[self._step_index]
        self._step_label.setText(
            self._tr("guide.step_counter", current=self._step_index + 1, total=len(self._steps))
        )
        self._title_label.setText(step.title)
        self._message_label.setText(step.message)
        is_last = self._step_index >= len(self._steps) - 1
        self._next_button.setText(self._tr("guide.action.finish") if is_last else self._tr("guide.action.next"))
        self._skip_button.setText(self._tr("guide.action.skip"))
        self._sync_geometry()

    def _next(self) -> None:
        if self._step_index >= len(self._steps) - 1:
            self.finished.emit("completed")
            self.close()
            return
        self._apply_step(self._step_index + 1)

    def _skip(self) -> None:
        self.finished.emit("skipped")
        self.close()

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        step = self._steps[self._step_index] if self._steps else None
        target = step.target_rect() if step else QRect()
        self._current_target = target.intersected(self.rect()) if target.isValid() else QRect()
        self._place_panel()
        self.update()

    def _place_panel(self) -> None:
        margin = 14
        panel_size = self._panel.sizeHint()
        if panel_size.width() < 340:
            panel_size.setWidth(340)
        if panel_size.height() < 150:
            panel_size.setHeight(150)

        if not self._current_target.isValid() or self._current_target.isNull():
            x = max(margin, self.width() - panel_size.width() - margin)
            y = max(margin, self.height() - panel_size.height() - margin)
            self._panel.setGeometry(x, y, panel_size.width(), panel_size.height())
            return

        target = self._current_target
        x = target.left()
        y = target.bottom() + 18
        if x + panel_size.width() > self.width() - margin:
            x = self.width() - panel_size.width() - margin
        if x < margin:
            x = margin

        if y + panel_size.height() > self.height() - margin:
            y = target.top() - panel_size.height() - 18
        if y < margin:
            y = margin

        self._panel.setGeometry(x, y, panel_size.width(), panel_size.height())


def rect_from_widgets(container: QWidget, widgets: list[QWidget], padding: int = 4) -> QRect:
    valid: list[QRect] = []
    for widget in widgets:
        if widget is None or not widget.isVisible():
            continue
        top_left = widget.mapTo(container, QPoint(0, 0))
        valid.append(QRect(top_left, widget.size()))
    if not valid:
        return QRect()
    merged = valid[0]
    for rect in valid[1:]:
        merged = merged.united(rect)
    return merged.adjusted(-padding, -padding, padding, padding)
