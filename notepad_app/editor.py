"""Plain-text editing surface with per-tab zoom and word wrap."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

ZOOM_MIN = 10
ZOOM_MAX = 500
ZOOM_STEP = 10
ZOOM_DEFAULT = 100


class Editor(QPlainTextEdit):
    filesDropped = Signal(list)
    zoomChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.file_path: str | None = None
        self.encoding = "utf-8"
        self.newline = "CRLF"
        self.zoom_percent = ZOOM_DEFAULT
        self.untitled_name = "Untitled"
        self.discard_from_session = False
        self._base_font = QFont("Consolas", 11)
        self._base_font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setUndoRedoEnabled(True)
        self._apply_zoom()
        self.document().setModified(False)

    def apply_base_font(self, font: QFont) -> None:
        base = QFont(font)
        if base.pointSizeF() <= 0:
            base.setPointSize(11)
        family = base.family()
        size = base.pointSizeF()
        weight = base.weight()
        italic = base.italic()
        base.setStyleHint(QFont.StyleHint.TypeWriter)
        base.setFamily(family)
        base.setPointSizeF(size if size > 0 else 11.0)
        base.setWeight(weight)
        base.setItalic(italic)
        self._base_font = base
        self._apply_zoom()

    def set_zoom(self, percent: int) -> None:
        self.zoom_percent = max(ZOOM_MIN, min(ZOOM_MAX, int(percent)))
        self._apply_zoom()
        self.zoomChanged.emit(self.zoom_percent)

    def zoom_in(self) -> None:
        self.set_zoom(self.zoom_percent + ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self.zoom_percent - ZOOM_STEP)

    def reset_zoom(self) -> None:
        self.set_zoom(ZOOM_DEFAULT)

    def set_word_wrap(self, enabled: bool) -> None:
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.setLineWrapMode(mode)

    def _apply_zoom(self) -> None:
        font = QFont(self._base_font)
        size = self._base_font.pointSizeF()
        if size <= 0:
            size = 11.0
        font.setPointSizeF(max(1.0, size * self.zoom_percent / 100.0))
        self.setFont(font)
        self.document().setDefaultFont(font)
        width = self.fontMetrics().horizontalAdvance(" ") * 8
        self.setTabStopDistance(float(max(1, width)))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def dragEnterEvent(self, event) -> None:
        if _has_local_files(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if _has_local_files(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = paths_from_mime(event.mimeData())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


def paths_from_mime(mime) -> list[str]:
    if mime is None or not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if url.isLocalFile():
            local = url.toLocalFile()
            if local:
                paths.append(local)
    return paths


def _has_local_files(event) -> bool:
    mime = event.mimeData()
    return bool(paths_from_mime(mime))
