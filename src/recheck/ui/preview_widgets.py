from __future__ import annotations

import wave
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
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


def _downsample(values: list[float], bins: int) -> list[float]:
    if not values:
        return [0.0] * bins
    chunk = max(1, len(values) // bins)
    reduced: list[float] = []
    for i in range(0, len(values), chunk):
        part = values[i : i + chunk]
        reduced.append(sum(abs(v) for v in part) / max(1, len(part)))
        if len(reduced) >= bins:
            break
    if len(reduced) < bins:
        reduced.extend([0.0] * (bins - len(reduced)))
    return reduced[:bins]


def build_waveform_samples(path: str, bins: int = 220) -> list[float]:
    target = Path(path)
    if not target.exists():
        return [0.0] * bins

    if target.suffix.lower() == ".wav":
        try:
            with wave.open(str(target), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                channels = max(1, wav_file.getnchannels())
                sample_width = wav_file.getsampwidth()
                read_frames = min(frame_count, 300000)
                raw = wav_file.readframes(read_frames)
        except Exception:
            raw = b""
            channels = 1
            sample_width = 1

        if sample_width == 2 and raw:
            amplitudes: list[float] = []
            step = sample_width * channels
            for offset in range(0, len(raw) - step + 1, step):
                frame = raw[offset : offset + step]
                total = 0.0
                for c in range(channels):
                    base = c * sample_width
                    sample = int.from_bytes(frame[base : base + sample_width], byteorder="little", signed=True)
                    total += abs(sample) / 32768.0
                amplitudes.append(total / channels)
            return _downsample(amplitudes, bins)

    try:
        payload = target.read_bytes()[:2_000_000]
    except Exception:
        payload = b""
    if not payload:
        return [0.0] * bins
    rough = [abs(byte - 128) / 128.0 for byte in payload]
    return _downsample(rough, bins)


class AudioWaveformWidget(QWidget):
    seek_ratio_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples = [0.0] * 220
        self._position_ratio = 0.0
        self.setMinimumHeight(84)

    def set_samples(self, samples: list[float]) -> None:
        self._samples = samples or [0.0] * 220
        self.update()

    def set_position_ratio(self, ratio: float) -> None:
        self._position_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def _emit_seek(self, x: int) -> None:
        if self.width() <= 0:
            return
        self.seek_ratio_requested.emit(max(0.0, min(1.0, x / self.width())))

    def mousePressEvent(self, event) -> None:
        self._emit_seek(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._emit_seek(event.position().x())
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#eef4fa"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = max(1, self.width())
        h = max(1, self.height())
        mid = h // 2

        pen = QPen(QColor("#7aa4ca"))
        pen.setWidth(1)
        painter.setPen(pen)

        count = len(self._samples)
        if count > 0:
            stride = w / count
            for idx, value in enumerate(self._samples):
                x = int(idx * stride)
                bar_half = int(max(1.0, (h * 0.45) * min(1.0, value)))
                painter.drawLine(x, mid - bar_half, x, mid + bar_half)

        play_x = int(self._position_ratio * w)
        play_pen = QPen(QColor("#1f5d92"))
        play_pen.setWidth(2)
        painter.setPen(play_pen)
        painter.drawLine(play_x, 0, play_x, h)
        painter.end()
        super().paintEvent(event)


class PdfFirstPageWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.label)
        layout.addWidget(self.scroll)

    def clear(self) -> None:
        self.label.setText("")
        self.label.setPixmap(QPixmap())

    def show_pdf_first_page(self, path: str) -> bool:
        self.clear()
        if not HAS_QT_PDF:
            return False
        doc = QPdfDocument()
        if doc.load(path) != QPdfDocument.Error.None_:
            return False
        if doc.pageCount() < 1:
            doc.close()
            return False

        page_size = doc.pagePointSize(0)
        width = max(700, int(page_size.width() * 1.7))
        height = max(900, int(page_size.height() * 1.7))
        width = min(width, 1800)
        height = min(height, 2200)
        image = doc.render(0, QSize(width, height))
        doc.close()
        if image.isNull():
            return False
        self.label.setPixmap(QPixmap.fromImage(image))
        return True


class AudioPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, *, tr=None) -> None:
        super().__init__(parent)
        self._tr = tr or (lambda key, **kwargs: key)
        self._updating_slider = False

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.play_button = QPushButton(self._tr("audio.play"))
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

        self.waveform = AudioWaveformWidget()
        self.waveform.seek_ratio_requested.connect(self._seek_ratio)
        layout.addWidget(self.waveform)

        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.positionChanged.connect(self._on_position_changed)

    def retranslate(self, tr) -> None:
        self._tr = tr
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText(self._tr("audio.pause"))
        else:
            self.play_button.setText(self._tr("audio.play"))

    def clear(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.play_button.setText(self._tr("audio.play"))
        self.time_label.setText("0:00:00 / 0:00:00")
        self.waveform.set_samples([0.0] * 220)
        self.waveform.set_position_ratio(0.0)

    def set_file(self, path: str) -> None:
        self.clear()
        self.waveform.set_samples(build_waveform_samples(path))
        self.player.setSource(QUrl.fromLocalFile(path))

    def _on_duration_changed(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self.time_label.setText(f"{_format_ms(self.player.position())} / {_format_ms(duration)}")

    def _on_position_changed(self, position: int) -> None:
        self._updating_slider = True
        self.slider.setValue(position)
        self._updating_slider = False
        duration = max(1, self.player.duration())
        self.waveform.set_position_ratio(position / duration)
        self.time_label.setText(f"{_format_ms(position)} / {_format_ms(self.player.duration())}")

    def _seek(self, value: int) -> None:
        if self._updating_slider:
            return
        self.player.setPosition(value)

    def _seek_ratio(self, ratio: float) -> None:
        duration = self.player.duration()
        if duration <= 0:
            return
        self.player.setPosition(int(duration * ratio))

    def _toggle_play_pause(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.play_button.setText(self._tr("audio.play"))
            return
        self.player.play()
        self.play_button.setText(self._tr("audio.pause"))


class FilePreviewColumn(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None, *, tr=None) -> None:
        super().__init__(parent)
        self._tr = tr or (lambda key, **kwargs: key)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.current_path: str | None = None
        self._title_text = title

        layout = QVBoxLayout(self)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("previewColumnTitle")
        layout.addWidget(self.title_label)

        self.info_label = QLabel(self._tr("preview.no_file_selected"))
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, 1)

        self.none_label = QLabel(self._tr("preview.none"))
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

        self.pdf_widget = PdfFirstPageWidget()
        self.stack.addWidget(self.pdf_widget)

        self.audio_widget = AudioPreviewWidget(tr=self._tr)
        self.stack.addWidget(self.audio_widget)

        self.unsupported_label = QLabel(self._tr("preview.unsupported"))
        self.unsupported_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.unsupported_label.setWordWrap(True)
        self.stack.addWidget(self.unsupported_label)

        footer = QHBoxLayout()
        self.meta_label = QLabel(self._tr("preview.size_modified_empty"))
        footer.addWidget(self.meta_label)
        footer.addStretch(1)
        self.open_button = QPushButton(self._tr("preview.open_external"))
        self.open_button.setEnabled(False)
        footer.addWidget(self.open_button)
        layout.addLayout(footer)

        self._page_none = 0
        self._page_image = 1
        self._page_text = 2
        self._page_pdf = 3
        self._page_audio = 4
        self._page_unsupported = 5
        self._show_none(self._tr("preview.none"))

    def retranslate(self, tr, *, title: str) -> None:
        self._tr = tr
        self._title_text = title
        self.title_label.setText(title)
        self.open_button.setText(tr("preview.open_external"))
        self.audio_widget.retranslate(tr)
        if self.current_path is None:
            self.info_label.setText(tr("preview.no_file_selected"))
            self.meta_label.setText(tr("preview.size_modified_empty"))

    def stop_media(self) -> None:
        self.audio_widget.clear()

    def _show_none(self, message: str) -> None:
        self.stop_media()
        self.current_path = None
        self.none_label.setText(message)
        self.info_label.setText(message)
        self.meta_label.setText(self._tr("preview.size_modified_empty"))
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
            self._show_none(self._tr("preview.not_found"))
            return

        self.current_path = str(file_path)
        self.open_button.setEnabled(True)
        self.info_label.setText(file_path.name)
        self.meta_label.setText(
            self._tr("preview.size_modified", size=_format_bytes(size), modified=modified_time or "-")
        )

        preview_type = detect_preview_type(str(file_path))
        if preview_type == "image":
            self.stop_media()
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                self._show_none("Image preview failed")
                return
            self.image_label.setPixmap(
                pixmap.scaled(
                    700,
                    700,
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
            if self.pdf_widget.show_pdf_first_page(str(file_path)):
                self.stack.setCurrentIndex(self._page_pdf)
            else:
                if not HAS_QT_PDF:
                    self.unsupported_label.setText(self._tr("preview.pdf_unavailable"))
                else:
                    self.unsupported_label.setText(self._tr("preview.pdf_failed"))
                self.stack.setCurrentIndex(self._page_unsupported)
            return

        if preview_type == "audio":
            self.audio_widget.set_file(str(file_path))
            self.stack.setCurrentIndex(self._page_audio)
            return

        self.stop_media()
        if preview_type == "video":
            self.unsupported_label.setText(self._tr("preview.video_optional"))
        elif preview_type == "office":
            self.unsupported_label.setText(self._tr("preview.office_external"))
        else:
            self.unsupported_label.setText(self._tr("preview.unsupported"))
        self.stack.setCurrentIndex(self._page_unsupported)
