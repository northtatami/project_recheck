from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from recheck.core.preview_service import read_text_preview
from recheck.utils.filetype_utils import detect_preview_type

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    HAS_QT_PDF = True
except Exception:
    HAS_QT_PDF = False


def _format_bytes(size: int | None) -> str:
    if size is None:
        return "-"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        idx += 1
        value /= 1024.0
    return f"{value:.1f} {units[idx]}"


def _format_ms(ms: int) -> str:
    seconds = max(0, ms // 1000)
    return str(timedelta(seconds=seconds))


class AudioPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._updating_slider = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self._toggle_play_pause)
        controls.addWidget(self.play_button)
        self.time_label = QLabel("0:00:00 / 0:00:00")
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._seek)
        layout.addWidget(self.slider)

        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)

    def clear(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.play_button.setText("Play")
        self.time_label.setText("0:00:00 / 0:00:00")

    def set_file(self, path: str) -> None:
        self.clear()
        self.player.setSource(QUrl.fromLocalFile(path))

    def _on_duration_changed(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self.time_label.setText(f"{_format_ms(self.player.position())} / {_format_ms(duration)}")

    def _on_position_changed(self, position: int) -> None:
        self._updating_slider = True
        self.slider.setValue(position)
        self._updating_slider = False
        self.time_label.setText(f"{_format_ms(position)} / {_format_ms(self.player.duration())}")

    def _seek(self, value: int) -> None:
        if self._updating_slider:
            return
        self.player.setPosition(value)

    def _toggle_play_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText("Play")
            return
        self.player.play()
        self.play_button.setText("Pause")


class FilePreviewColumn(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.current_path: str | None = None

        layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("previewColumnTitle")
        layout.addWidget(self.title_label)

        self.info_label = QLabel("No file selected")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, 1)

        self.none_label = QLabel("none")
        self.none_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.none_label)

        image_container = QWidget()
        image_layout = QVBoxLayout(image_container)
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setWidget(self.image_label)
        image_layout.addWidget(self.image_scroll)
        self.stack.addWidget(image_container)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.stack.addWidget(self.text_view)

        if HAS_QT_PDF:
            pdf_container = QWidget()
            pdf_layout = QVBoxLayout(pdf_container)
            self.pdf_document = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setDocument(self.pdf_document)
            pdf_layout.addWidget(self.pdf_view)
            self.stack.addWidget(pdf_container)
        else:
            self.pdf_document = None
            self.pdf_view = None
            self.pdf_fallback_label = QLabel("PDF preview is unavailable in this environment.")
            self.pdf_fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stack.addWidget(self.pdf_fallback_label)

        self.audio_widget = AudioPreviewWidget()
        self.stack.addWidget(self.audio_widget)

        self.unsupported_label = QLabel("Preview is not available for this file type.")
        self.unsupported_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unsupported_label.setWordWrap(True)
        self.stack.addWidget(self.unsupported_label)

        footer = QHBoxLayout()
        self.meta_label = QLabel("Size: - | Modified: -")
        footer.addWidget(self.meta_label)
        footer.addStretch(1)
        self.open_button = QPushButton("Open External")
        self.open_button.setEnabled(False)
        footer.addWidget(self.open_button)
        layout.addLayout(footer)

        self._page_none = 0
        self._page_image = 1
        self._page_text = 2
        self._page_pdf = 3
        self._page_audio = 4
        self._page_unsupported = 5
        self._show_none("none")

    def stop_media(self) -> None:
        self.audio_widget.clear()

    def _show_none(self, message: str) -> None:
        self.stop_media()
        self.current_path = None
        self.none_label.setText(message)
        self.info_label.setText(message)
        self.meta_label.setText("Size: - | Modified: -")
        self.stack.setCurrentIndex(self._page_none)
        self.open_button.setEnabled(False)

    def show_file(
        self,
        path: str | None,
        *,
        empty_message: str,
        modified_time: str | None,
        size: int | None,
    ) -> None:
        if not path:
            self._show_none(empty_message)
            return
        file_path = Path(path)
        if not file_path.exists():
            self._show_none("File not found")
            return

        self.current_path = str(file_path)
        self.open_button.setEnabled(True)
        self.info_label.setText(file_path.name)
        self.meta_label.setText(f"Size: {_format_bytes(size)} | Modified: {modified_time or '-'}")

        preview_type = detect_preview_type(str(file_path))
        if preview_type == "image":
            self.stop_media()
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                self._show_none("Image preview failed")
                return
            self.image_label.setPixmap(
                pixmap.scaled(
                    620,
                    620,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.stack.setCurrentIndex(self._page_image)
            return

        if preview_type == "text":
            self.stop_media()
            self.text_view.setPlainText(read_text_preview(str(file_path)))
            self.stack.setCurrentIndex(self._page_text)
            return

        if preview_type == "pdf":
            self.stop_media()
            if HAS_QT_PDF and self.pdf_document is not None:
                self.pdf_document.load(str(file_path))
            self.stack.setCurrentIndex(self._page_pdf)
            return

        if preview_type == "audio":
            self.audio_widget.set_file(str(file_path))
            self.stack.setCurrentIndex(self._page_audio)
            return

        self.stop_media()
        if preview_type == "video":
            self.unsupported_label.setText("Video preview is optional in v0.1. Open externally.")
        elif preview_type == "office":
            self.unsupported_label.setText("Office files are external-open only in v0.1.")
        else:
            self.unsupported_label.setText("Preview is not available for this file type.")
        self.stack.setCurrentIndex(self._page_unsupported)
