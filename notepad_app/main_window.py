"""Notepad main window: menus, tabs, status bar, files, and session restore."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QDateTime, QEvent, QLocale, QMarginsF, QRect, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QGuiApplication,
    QKeySequence,
    QMouseEvent,
    QPageLayout,
    QPageSize,
    QTextCursor,
)
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from notepad_app.dialogs import AboutDialog, GoToDialog, SettingsDialog, font_from_settings
from notepad_app.editor import Editor, paths_from_mime
from notepad_app.find_bar import FindReplaceBar
from notepad_app.storage import load_session, load_settings, save_session, save_settings
from notepad_app.textio import (
    ENCODINGS,
    NEWLINES,
    encode_text,
    encoding_label,
    load_bytes,
    newline_label,
    normalize_encoding,
    normalize_newline_name,
)
from notepad_app.theme import (
    add_theme_listener,
    install_theme,
    set_windows_titlebar_dark,
    theme_is_dark,
)

OPEN_WINDOWS: list["MainWindow"] = []
_settings: dict | None = None
_session_timer: QTimer | None = None
_quitting = False


def get_settings() -> dict:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def refresh_open_windows_theme() -> None:
    for window in OPEN_WINDOWS:
        window.apply_title_bar()


def schedule_session_save() -> None:
    global _session_timer
    if _quitting or not OPEN_WINDOWS:
        return
    if QApplication.instance() is None:
        return
    if _session_timer is None:
        _session_timer = QTimer()
        _session_timer.setSingleShot(True)
        _session_timer.setInterval(400)
        _session_timer.timeout.connect(save_open_session)
    _session_timer.start()


def stop_session_timer() -> None:
    if _session_timer is not None:
        _session_timer.stop()


def save_open_session() -> None:
    if _quitting or not OPEN_WINDOWS:
        return
    save_session({"windows": [window.snapshot() for window in list(OPEN_WINDOWS)]})


def _rect_dict(rect: QRect) -> dict:
    return {
        "x": int(rect.x()),
        "y": int(rect.y()),
        "width": int(rect.width()),
        "height": int(rect.height()),
    }


def _rect_from(value) -> QRect | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value["x"])
        y = int(value["y"])
        width = int(value["width"])
        height = int(value["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return QRect(x, y, width, height)


def _available_screen_rects() -> list[QRect]:
    return [QRect(screen.availableGeometry()) for screen in QGuiApplication.screens()]


def _title_bar_rect(frame: QRect) -> QRect:
    height = min(40, max(1, frame.height()))
    return QRect(frame.x(), frame.y(), max(1, frame.width()), height)


def _title_bar_visible(frame: QRect, availables: list[QRect]) -> bool:
    title = _title_bar_rect(frame)
    for available in availables:
        overlap = title.intersected(available)
        if overlap.width() >= min(80, title.width()) and overlap.height() >= min(16, title.height()):
            return True
    return False


def _nearest_available(frame: QRect, availables: list[QRect]) -> QRect:
    def distance(available: QRect) -> int:
        cx = min(max(frame.center().x(), available.left()), available.right())
        cy = min(max(frame.center().y(), available.top()), available.bottom())
        dx = frame.center().x() - cx
        dy = frame.center().y() - cy
        return dx * dx + dy * dy

    return min(availables, key=distance)


def fit_frame_to_screens(frame: QRect, availables: list[QRect] | None = None) -> QRect:
    """Keep a global frame, or move it fully onto the nearest screen.

    Coordinates stay in virtual-desktop space, so a window on a monitor to the
    left or above the primary screen is left there when that screen is present.
    """
    if availables is None:
        availables = _available_screen_rects()
    if not availables or frame.isNull():
        return QRect(frame)
    if _title_bar_visible(frame, availables):
        return QRect(frame)
    available = _nearest_available(frame, availables)
    width = frame.width()
    height = frame.height()
    if width > available.width():
        width = available.width()
    if height > available.height():
        height = available.height()
    width = max(1, width)
    height = max(1, height)
    x = frame.x()
    y = frame.y()
    if x < available.left():
        x = available.left()
    if y < available.top():
        y = available.top()
    if x + width > available.left() + available.width():
        x = available.left() + available.width() - width
    if y + height > available.top() + available.height():
        y = available.top() + available.height() - height
    if y < available.top():
        y = available.top()
    return QRect(int(x), int(y), int(width), int(height))


def open_initial_windows() -> None:
    settings = get_settings()
    session = load_session() if settings.get("restore_session", True) else None
    windows = []
    if isinstance(session, dict) and isinstance(session.get("windows"), list):
        windows = [item for item in session["windows"] if isinstance(item, dict)]
    opened = 0
    for snapshot in windows:
        tabs = snapshot.get("tabs")
        if not isinstance(tabs, list):
            continue
        window = MainWindow(start_blank=False)
        window.apply_snapshot(snapshot)
        window.show()
        opened += 1
    if opened == 0:
        window = MainWindow(start_blank=True)
        window.show()


def printer_from_settings(settings: dict) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
    setup = settings.get("page_setup") if isinstance(settings.get("page_setup"), dict) else {}
    try:
        layout = QPageLayout()
        size_id = setup.get("page_size_id")
        if isinstance(size_id, int):
            page_size = QPageSize(QPageSize.PageSizeId(size_id))
        else:
            page_size = QPageSize(QPageSize.PageSizeId.Letter)
        layout.setPageSize(page_size)
        if setup.get("orientation") == "landscape":
            layout.setOrientation(QPageLayout.Orientation.Landscape)
        else:
            layout.setOrientation(QPageLayout.Orientation.Portrait)
        layout.setUnits(QPageLayout.Unit.Millimeter)
        layout.setMargins(
            QMarginsF(
                float(setup.get("left", 12.7)),
                float(setup.get("top", 12.7)),
                float(setup.get("right", 12.7)),
                float(setup.get("bottom", 12.7)),
            )
        )
        printer.setPageLayout(layout)
    except Exception:
        return QPrinter(QPrinter.PrinterMode.ScreenResolution)
    return printer


def page_setup_from_printer(printer: QPrinter) -> dict:
    layout = printer.pageLayout()
    margins = layout.margins(QPageLayout.Unit.Millimeter)
    landscape = layout.orientation() == QPageLayout.Orientation.Landscape
    return {
        "page_size_id": int(layout.pageSize().id()),
        "orientation": "landscape" if landscape else "portrait",
        "left": margins.left(),
        "top": margins.top(),
        "right": margins.right(),
        "bottom": margins.bottom(),
    }


def find_editor_for_path(path: str) -> tuple["MainWindow", int] | None:
    target = os.path.normcase(os.path.abspath(path))
    for window in OPEN_WINDOWS:
        for index in range(window.tabs.count()):
            editor = window.tabs.widget(index)
            if isinstance(editor, Editor) and editor.file_path:
                if os.path.normcase(editor.file_path) == target:
                    return window, index
    return None


class EditorTabs(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDocumentMode(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabBar().setAcceptDrops(True)
        self.tabBar().installEventFilter(self)
        self.files_dropped = None

    def set_drop_handler(self, handler) -> None:
        self.files_dropped = handler

    def eventFilter(self, watched, event) -> bool:
        if watched is self.tabBar() and isinstance(event, QMouseEvent):
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.MiddleButton
            ):
                index = self.tabBar().tabAt(event.position().toPoint())
                if index >= 0:
                    self.tabCloseRequested.emit(index)
                return True
        if watched is self.tabBar() and event.type() in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            paths = paths_from_mime(event.mimeData())
            if paths:
                if event.type() == QEvent.Type.Drop and self.files_dropped is not None:
                    self.files_dropped(paths)
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = paths_from_mime(event.mimeData())
        if paths and self.files_dropped is not None:
            self.files_dropped(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, *, start_blank: bool = True) -> None:
        super().__init__()
        self._loading = False
        self._saved_normal_frame: QRect | None = None
        self._applying_geometry = False
        self._pending_maximize = False
        OPEN_WINDOWS.append(self)
        self.setWindowTitle("Notepad")
        self.resize(960, 640)
        self.setAcceptDrops(True)
        icon = QApplication.windowIcon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self._build_ui()
        self._build_menus()
        self._build_status()
        self.apply_preferences()
        if start_blank:
            self.add_blank_tab()
        self.update_status()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.find_bar = FindReplaceBar()
        self.find_bar.hide()
        self.find_bar.set_callbacks(self.current_editor, self.show_status_message)
        self.tabs = EditorTabs()
        self.tabs.set_drop_handler(self.open_paths)
        self.tabs.tabCloseRequested.connect(self.close_tab_index)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabBar().tabMoved.connect(lambda *_args: schedule_session_save())
        self.empty_state = QLabel("No document open\n\nCreate a new tab or open a file.")
        self.empty_state.setObjectName("EmptyDocument")
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.document_stack = QStackedWidget()
        self.document_stack.addWidget(self.empty_state)
        self.document_stack.addWidget(self.tabs)
        layout.addWidget(self.find_bar)
        layout.addWidget(self.document_stack, 1)
        self.setCentralWidget(central)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.setObjectName("fileMenu")
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.setObjectName("editMenu")
        view_menu = self.menuBar().addMenu("&View")
        view_menu.setObjectName("viewMenu")
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.setObjectName("helpMenu")

        self._add_action(file_menu, "&New tab", self.new_tab, QKeySequence.StandardKey.New)
        self._add_action(file_menu, "New &window", self.new_window, QKeySequence("Ctrl+Shift+N"))
        self._add_action(file_menu, "&Open...", self.open_dialog, QKeySequence.StandardKey.Open)
        self.save_action = self._add_action(file_menu, "&Save", self.save_current, QKeySequence.StandardKey.Save)
        self.save_as_action = self._add_action(
            file_menu, "Save &as...", self.save_current_as, QKeySequence("Ctrl+Shift+S")
        )
        self.save_all_action = self._add_action(file_menu, "Save a&ll", self.save_all)
        file_menu.addSeparator()
        self._add_action(file_menu, "Page set&up...", self.page_setup)
        self.print_action = self._add_action(
            file_menu, "&Print...", self.print_current, QKeySequence.StandardKey.Print
        )
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("&Recent files")
        self.recent_menu.aboutToShow.connect(self.rebuild_recent_menu)
        file_menu.addSeparator()
        self.close_tab_action = self._add_action(
            file_menu, "&Close tab", self.close_current_tab, QKeySequence("Ctrl+W")
        )
        self._add_action(file_menu, "E&xit", self.exit_application)

        self.undo_action = self._add_action(
            edit_menu, "&Undo", self.undo, QKeySequence.StandardKey.Undo
        )
        self.redo_action = self._add_action(
            edit_menu, "&Redo", self.redo, QKeySequence.StandardKey.Redo
        )
        edit_menu.addSeparator()
        self.cut_action = self._add_action(edit_menu, "Cu&t", self.cut, QKeySequence.StandardKey.Cut)
        self.copy_action = self._add_action(edit_menu, "&Copy", self.copy, QKeySequence.StandardKey.Copy)
        self.paste_action = self._add_action(edit_menu, "&Paste", self.paste, QKeySequence.StandardKey.Paste)
        self.delete_action = self._add_action(
            edit_menu, "&Delete", self.delete_text, QKeySequence(Qt.Key.Key_Delete)
        )
        edit_menu.addSeparator()
        self.select_all_action = self._add_action(
            edit_menu, "Select &all", self.select_all, QKeySequence.StandardKey.SelectAll
        )
        edit_menu.addSeparator()
        self.find_action = self._add_action(edit_menu, "&Find...", self.show_find, QKeySequence.StandardKey.Find)
        self.find_next_action = self._add_action(edit_menu, "Find &next", self.find_next, QKeySequence("F3"))
        self.find_previous_action = self._add_action(
            edit_menu, "Find pre&vious", self.find_previous, QKeySequence("Shift+F3")
        )
        self.replace_action = self._add_action(
            edit_menu, "&Replace...", self.show_replace, QKeySequence("Ctrl+H")
        )
        self.replace_all_action = self._add_action(edit_menu, "Replace &all", self.replace_all)
        self.go_to_action = self._add_action(edit_menu, "&Go to...", self.go_to, QKeySequence("Ctrl+G"))
        self.time_date_action = self._add_action(
            edit_menu, "Time/&Date", self.insert_time_date, QKeySequence("F5")
        )

        self.zoom_in_action = self._add_action(
            view_menu, "Zoom &in", self.zoom_in, QKeySequence.StandardKey.ZoomIn
        )
        self.zoom_out_action = self._add_action(
            view_menu, "Zoom &out", self.zoom_out, QKeySequence.StandardKey.ZoomOut
        )
        self.reset_zoom_action = self._add_action(
            view_menu, "&Reset zoom", self.reset_zoom, QKeySequence("Ctrl+0")
        )
        view_menu.addSeparator()
        self.word_wrap_action = self._add_action(
            view_menu,
            "&Word wrap",
            self.on_word_wrap_toggled,
            checkable=True,
        )
        self.status_action = self._add_action(
            view_menu,
            "&Status bar",
            self.on_status_bar_toggled,
            checkable=True,
        )
        view_menu.addSeparator()
        self._add_action(view_menu, "Se&ttings...", self.show_settings)

        self._add_action(help_menu, "&About Notepad", self.show_about)

    def _build_status(self) -> None:
        status = QStatusBar()
        self.setStatusBar(status)
        self.position_label = QLabel("Ln 1, Col 1")
        self.position_label.setMinimumWidth(110)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.newline_button = self._status_button("Line ending")
        self.encoding_button = self._status_button("Encoding")

        self.newline_menu = QMenu(self)
        for key, label in NEWLINES:
            action = self.newline_menu.addAction(label)
            action.triggered.connect(self._bind(self.set_current_newline, key))
        self.newline_button.setMenu(self.newline_menu)
        self.newline_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.encoding_menu = QMenu(self)
        for key, label in ENCODINGS:
            action = self.encoding_menu.addAction(label)
            action.triggered.connect(self._bind(self.set_current_encoding, key))
        self.encoding_button.setMenu(self.encoding_menu)
        self.encoding_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        status.addWidget(self.position_label, 1)
        status.addPermanentWidget(self.zoom_label)
        status.addPermanentWidget(self.newline_button)
        status.addPermanentWidget(self.encoding_button)

    def _status_button(self, tip: str) -> QToolButton:
        button = QToolButton()
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _add_action(
        self,
        menu: QMenu,
        text: str,
        slot,
        shortcut=None,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setCheckable(checkable)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QKeySequence(item) for item in shortcut])
            elif isinstance(shortcut, QKeySequence.StandardKey):
                action.setShortcut(QKeySequence(shortcut))
            else:
                action.setShortcut(shortcut)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(lambda checked=False, callback=slot: callback())
        menu.addAction(action)
        return action

    def _bind(self, func, *args):
        def slot(*_unused) -> None:
            func(*args)

        return slot

    def apply_preferences(self) -> None:
        settings = get_settings()
        font = font_from_settings(settings)
        wrap = bool(settings.get("word_wrap", True))
        show_status = bool(settings.get("status_bar", True))
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if isinstance(editor, Editor):
                editor.apply_base_font(font)
                editor.set_word_wrap(wrap)
        self.statusBar().setVisible(show_status)
        self.word_wrap_action.blockSignals(True)
        self.word_wrap_action.setChecked(wrap)
        self.word_wrap_action.blockSignals(False)
        self.status_action.blockSignals(True)
        self.status_action.setChecked(show_status)
        self.status_action.blockSignals(False)
        self.apply_title_bar()
        self.update_status()

    def apply_title_bar(self) -> None:
        set_windows_titlebar_dark(self, theme_is_dark())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_title_bar()
        if self._pending_maximize:
            self._pending_maximize = False
            QTimer.singleShot(0, self._enter_maximized)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._remember_normal_frame()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._remember_normal_frame()

    def _remember_normal_frame(self) -> None:
        if self._applying_geometry:
            return
        state = self.windowState()
        if state & (
            Qt.WindowState.WindowMaximized
            | Qt.WindowState.WindowMinimized
            | Qt.WindowState.WindowFullScreen
        ):
            return
        frame = self.frameGeometry()
        if frame.width() > 0 and frame.height() > 0:
            self._saved_normal_frame = QRect(frame)

    def geometry_state(self) -> dict:
        """Global frame geometry for this top-level window."""
        maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
        if maximized and self._saved_normal_frame is not None:
            normal = QRect(self._saved_normal_frame)
        elif maximized:
            normal = QRect(self.normalGeometry())
        else:
            normal = QRect(self.frameGeometry())
            self._saved_normal_frame = QRect(normal)
        if normal.width() <= 0 or normal.height() <= 0:
            normal = QRect(self.geometry())
        encoded = bytes(self.saveGeometry().toBase64()).decode("ascii")
        return {
            "save_geometry": encoded,
            "maximized": maximized,
            "normal_frame": _rect_dict(normal),
        }

    def apply_window_geometry(self, data: dict) -> None:
        """Restore a top-level frame, including another monitor or maximized."""
        if not isinstance(data, dict):
            return
        blob = data.get("save_geometry")
        if isinstance(blob, str) and blob.strip():
            try:
                self.restoreGeometry(QByteArray.fromBase64(blob.encode("ascii")))
            except Exception:
                pass
        normal = _rect_from(data.get("normal_frame"))
        if normal is None:
            normal = QRect(self.frameGeometry())
        fitted = fit_frame_to_screens(normal)
        maximized = bool(data.get("maximized"))
        self._applying_geometry = True
        try:
            self.setWindowState(Qt.WindowState.WindowNoState)
            self._place_frame(fitted)
            self._saved_normal_frame = QRect(self.frameGeometry())
            self._pending_maximize = maximized
        finally:
            self._applying_geometry = False
        if maximized and self.isVisible():
            self._pending_maximize = False
            self._enter_maximized()

    def _enter_maximized(self) -> None:
        """Maximize after the normal frame is on the target screen."""
        self._applying_geometry = True
        try:
            if self._saved_normal_frame is not None:
                self._place_frame(self._saved_normal_frame)
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        finally:
            self._applying_geometry = False

    def _place_frame(self, frame: QRect) -> None:
        """Move the window so its frame, including the title bar, lands on `frame`."""
        for _ in range(3):
            current = self.frameGeometry()
            if current == frame:
                return
            client = self.geometry()
            dx = client.x() - current.x()
            dy = client.y() - current.y()
            extra_width = current.width() - client.width()
            extra_height = current.height() - client.height()
            self.setGeometry(
                QRect(
                    frame.x() + dx,
                    frame.y() + dy,
                    max(1, frame.width() - extra_width),
                    max(1, frame.height() - extra_height),
                )
            )

    def current_editor(self) -> Editor | None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, Editor):
            return widget
        return None

    def create_editor(self) -> Editor:
        editor = Editor()
        settings = get_settings()
        editor.apply_base_font(font_from_settings(settings))
        editor.set_word_wrap(bool(settings.get("word_wrap", True)))
        editor.filesDropped.connect(self.open_paths)
        editor.zoomChanged.connect(lambda *_args: self.update_status())
        editor.cursorPositionChanged.connect(self.update_status)
        editor.textChanged.connect(lambda: schedule_session_save())
        editor.document().modificationChanged.connect(
            lambda _changed, current=editor: self.on_modified(current)
        )
        editor.undoAvailable.connect(lambda *_args: self.refresh_undo())
        editor.redoAvailable.connect(lambda *_args: self.refresh_undo())
        return editor

    def add_editor(self, editor: Editor) -> int:
        index = self.tabs.addTab(editor, self.tab_name(editor))
        self.tabs.setCurrentIndex(index)
        self.refresh_tab(editor)
        editor.setFocus()
        return index

    def add_blank_tab(self) -> Editor:
        editor = self.create_editor()
        editor.untitled_name = self.next_untitled_name()
        editor.encoding = "utf-8"
        editor.newline = "CRLF"
        editor.document().setModified(False)
        self.add_editor(editor)
        schedule_session_save()
        return editor

    def next_untitled_name(self) -> str:
        used: set[str] = set()
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if isinstance(editor, Editor) and editor.file_path is None:
                used.add(editor.untitled_name)
        number = 1
        while True:
            name = "Untitled" if number == 1 else f"Untitled {number}"
            if name not in used:
                return name
            number += 1

    def tab_name(self, editor: Editor) -> str:
        if editor.file_path:
            return os.path.basename(editor.file_path)
        return editor.untitled_name or "Untitled"

    def refresh_tab(self, editor: Editor) -> None:
        index = self.tabs.indexOf(editor)
        if index < 0:
            return
        name = self.tab_name(editor)
        shown = f"*{name}" if editor.document().isModified() else name
        self.tabs.setTabText(index, shown)
        self.tabs.setTabToolTip(index, editor.file_path or name)
        if self.tabs.currentWidget() is editor:
            self.setWindowTitle(f"{shown} - Notepad")

    def on_modified(self, editor: Editor) -> None:
        self.refresh_tab(editor)
        if self.tabs.currentWidget() is editor:
            self.update_status()

    def on_tab_changed(self, _index: int) -> None:
        editor = self.current_editor()
        if editor is not None:
            self.refresh_tab(editor)
        else:
            self.setWindowTitle("Notepad")
        self.update_status()

    def update_status(self) -> None:
        if not hasattr(self, "position_label"):
            return
        editor = self.current_editor()
        has_document = editor is not None
        self._show_document_area(has_document)
        self._set_document_actions_enabled(has_document)
        if not has_document:
            self.position_label.setText("")
            self.zoom_label.setText("")
            self.newline_button.setText("")
            self.encoding_button.setText("")
            self.newline_button.setEnabled(False)
            self.encoding_button.setEnabled(False)
            self.find_bar.hide()
            self.refresh_undo()
            return
        self.newline_button.setEnabled(True)
        self.encoding_button.setEnabled(True)
        cursor = editor.textCursor()
        self.position_label.setText(f"Ln {cursor.blockNumber() + 1}, Col {cursor.positionInBlock() + 1}")
        self.zoom_label.setText(f"{editor.zoom_percent}%")
        self.newline_button.setText(newline_label(editor.newline))
        self.encoding_button.setText(encoding_label(editor.encoding))
        self.refresh_undo()

    def _show_document_area(self, has_document: bool) -> None:
        if not hasattr(self, "document_stack"):
            return
        self.document_stack.setCurrentWidget(self.tabs if has_document else self.empty_state)

    def _set_document_actions_enabled(self, enabled: bool) -> None:
        if not hasattr(self, "save_action"):
            return
        for action in (
            self.save_action,
            self.save_as_action,
            self.save_all_action,
            self.print_action,
            self.close_tab_action,
            self.undo_action,
            self.redo_action,
            self.cut_action,
            self.copy_action,
            self.paste_action,
            self.delete_action,
            self.select_all_action,
            self.find_action,
            self.find_next_action,
            self.find_previous_action,
            self.replace_action,
            self.replace_all_action,
            self.go_to_action,
            self.time_date_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.reset_zoom_action,
        ):
            action.setEnabled(enabled)
        if enabled:
            self.refresh_undo()

    def refresh_undo(self) -> None:
        if not hasattr(self, "undo_action"):
            return
        editor = self.current_editor()
        document = editor.document() if editor is not None else None
        self.undo_action.setEnabled(document is not None and document.isUndoAvailable())
        self.redo_action.setEnabled(document is not None and document.isRedoAvailable())

    def show_status_message(self, text: str) -> None:
        self.statusBar().showMessage(text, 4000)

    def new_tab(self) -> Editor:
        return self.add_blank_tab()

    def new_window(self) -> "MainWindow":
        window = MainWindow(start_blank=True)
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def open_dialog(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "Open",
            self.suggested_directory(),
            "Text documents (*.txt);;All files (*.*)",
        )
        if paths:
            self.open_paths(paths)

    def open_paths(self, paths: list[str]) -> None:
        for path in paths:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        if not path:
            return False
        path = os.path.abspath(path)
        if os.path.isdir(path):
            self.show_status_message("Cannot open a folder.")
            return False
        located = find_editor_for_path(path)
        if located is not None:
            window, index = located
            window.tabs.setCurrentIndex(index)
            window.show()
            window.raise_()
            window.activateWindow()
            editor = window.tabs.widget(index)
            if isinstance(editor, Editor):
                editor.setFocus()
            return True
        if not os.path.isfile(path):
            self.remove_recent(path)
            QMessageBox.critical(self, "Notepad", f"Could not open the file:\n{path}")
            return False
        try:
            data = Path(path).read_bytes()
        except OSError as error:
            self.remove_recent(path)
            QMessageBox.critical(self, "Notepad", f"Could not open the file:\n{path}\n\n{error}")
            return False
        loaded = load_bytes(data)
        if loaded.binary and not self.confirm_binary(path):
            return False
        editor = self.reuse_blank_tab()
        if editor is None:
            editor = self.create_editor()
            editor.untitled_name = self.next_untitled_name()
            self.add_editor(editor)
        editor.file_path = path
        editor.encoding = loaded.encoding
        editor.newline = loaded.newline
        editor.setPlainText(loaded.text)
        editor.document().setModified(False)
        self.refresh_tab(editor)
        self.add_recent(path)
        self.update_status()
        editor.setFocus()
        schedule_session_save()
        return True

    def reuse_blank_tab(self) -> Editor | None:
        if self.tabs.count() != 1:
            return None
        editor = self.tabs.widget(0)
        if not isinstance(editor, Editor):
            return None
        if editor.file_path is None and not editor.document().isModified() and editor.toPlainText() == "":
            return editor
        return None

    def confirm_binary(self, path: str) -> bool:
        result = QMessageBox.question(
            self,
            "Notepad",
            f"This file may be binary — open anyway?\n\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def save_current(self) -> bool:
        editor = self.current_editor()
        if editor is None:
            return False
        return self.save_editor(editor)

    def save_current_as(self) -> bool:
        editor = self.current_editor()
        if editor is None:
            return False
        return self.save_editor_as(editor)

    def save_all(self) -> bool:
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if not isinstance(editor, Editor) or not editor.document().isModified():
                continue
            self.tabs.setCurrentIndex(index)
            if not self.save_editor(editor):
                return False
        return True

    def save_editor(self, editor: Editor) -> bool:
        if not editor.file_path:
            return self.save_editor_as(editor)
        return self.save_editor_to_path(editor, editor.file_path)

    def save_editor_as(self, editor: Editor) -> bool:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Save As",
            self.suggested_path(editor),
            "Text documents (*.txt);;All files (*.*)",
        )
        if not path:
            return False
        return self.save_editor_to_path(editor, path)

    def save_editor_to_path(self, editor: Editor, path: str) -> bool:
        path = os.path.abspath(path)
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            QMessageBox.critical(
                self,
                "Notepad",
                f"Could not save the file because the folder does not exist:\n{parent}",
            )
            return False
        other = find_editor_for_path(path)
        if other is not None:
            window, index = other
            if window.tabs.widget(index) is not editor:
                QMessageBox.warning(self, "Notepad", "This file is already open in another tab.")
                return False
        try:
            data = encode_text(editor.toPlainText(), editor.encoding, editor.newline)
        except UnicodeEncodeError:
            QMessageBox.critical(
                self,
                "Notepad",
                "This file contains characters that cannot be saved with the selected encoding.",
            )
            return False
        temporary = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temporary, "wb") as handle:
                handle.write(data)
            os.replace(temporary, path)
        except OSError as error:
            try:
                os.remove(temporary)
            except OSError:
                pass
            QMessageBox.critical(self, "Notepad", f"Could not save the file:\n{path}\n\n{error}")
            return False
        editor.file_path = path
        editor.document().setModified(False)
        self.add_recent(path)
        self.refresh_tab(editor)
        self.update_status()
        schedule_session_save()
        return True

    def suggested_path(self, editor: Editor) -> str:
        if editor.file_path:
            return editor.file_path
        name = editor.untitled_name or "Untitled"
        if not name.lower().endswith(".txt"):
            name = f"{name}.txt"
        documents = Path.home() / "Documents"
        folder = documents if documents.is_dir() else Path.home()
        return str(folder / name)

    def suggested_directory(self) -> str:
        editor = self.current_editor()
        if editor is not None and editor.file_path:
            return os.path.dirname(editor.file_path)
        documents = Path.home() / "Documents"
        if documents.is_dir():
            return str(documents)
        return str(Path.home())

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        settings = get_settings()
        target = os.path.normcase(path)
        recent = []
        for item in settings.get("recent_files", []):
            if isinstance(item, str) and os.path.normcase(os.path.abspath(item)) != target:
                recent.append(item)
        recent.insert(0, path)
        settings["recent_files"] = recent[:10]
        save_settings(settings)

    def remove_recent(self, path: str) -> None:
        settings = get_settings()
        try:
            target = os.path.normcase(os.path.abspath(path))
        except OSError:
            target = os.path.normcase(path)
        settings["recent_files"] = [
            item
            for item in settings.get("recent_files", [])
            if isinstance(item, str) and os.path.normcase(item) != target
        ]
        save_settings(settings)

    def rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = [item for item in get_settings().get("recent_files", []) if isinstance(item, str)]
        if not files:
            empty = self.recent_menu.addAction("(Empty)")
            empty.setEnabled(False)
            return
        for index, path in enumerate(files[:10]):
            label = f"&{index + 1} {path}" if index < 9 else path
            action = self.recent_menu.addAction(label)
            action.triggered.connect(self._bind(self.open_path, path))

    def set_current_encoding(self, encoding: str) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        encoding = normalize_encoding(encoding)
        if editor.encoding != encoding:
            editor.encoding = encoding
            editor.document().setModified(True)
            self.refresh_tab(editor)
            schedule_session_save()
        self.update_status()

    def set_current_newline(self, newline: str) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        newline = normalize_newline_name(newline)
        if editor.newline != newline:
            editor.newline = newline
            editor.document().setModified(True)
            self.refresh_tab(editor)
            schedule_session_save()
        self.update_status()

    def focused_text_input(self):
        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QPlainTextEdit)):
            return widget
        return self.current_editor()

    def undo(self) -> None:
        widget = self.focused_text_input()
        if widget is not None:
            widget.undo()

    def redo(self) -> None:
        widget = self.focused_text_input()
        if widget is not None and hasattr(widget, "redo"):
            widget.redo()

    def cut(self) -> None:
        widget = self.focused_text_input()
        if widget is not None:
            widget.cut()

    def copy(self) -> None:
        widget = self.focused_text_input()
        if widget is not None:
            widget.copy()

    def paste(self) -> None:
        widget = self.focused_text_input()
        if widget is not None:
            widget.paste()

    def delete_text(self) -> None:
        widget = self.focused_text_input()
        if isinstance(widget, QLineEdit):
            widget.del_()
            return
        if isinstance(widget, QPlainTextEdit):
            cursor = widget.textCursor()
            if cursor.hasSelection():
                cursor.removeSelectedText()
            else:
                cursor.deleteChar()
            widget.setTextCursor(cursor)

    def select_all(self) -> None:
        widget = self.focused_text_input()
        if widget is not None:
            widget.selectAll()

    def show_find(self) -> None:
        if self.current_editor() is None:
            return
        self.find_bar.show_find()

    def show_replace(self) -> None:
        if self.current_editor() is None:
            return
        self.find_bar.show_replace()

    def find_next(self) -> None:
        if self.current_editor() is None:
            return
        if not self.find_bar.find_edit.text():
            self.find_bar.show_find()
            return
        self.find_bar.find_next()

    def find_previous(self) -> None:
        if self.current_editor() is None:
            return
        if not self.find_bar.find_edit.text():
            self.find_bar.show_find()
            return
        self.find_bar.find_previous()

    def replace_all(self) -> None:
        if self.current_editor() is None:
            return
        if not self.find_bar.isVisible() or self.find_bar.replace_row.isHidden():
            self.find_bar.show_replace()
        if self.find_bar.find_edit.text():
            self.find_bar.replace_all()

    def go_to(self) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        maximum = max(1, editor.document().blockCount())
        current = editor.textCursor().blockNumber() + 1
        dialog = GoToDialog(current, maximum, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.go_to_line(dialog.line_number())

    def go_to_line(self, line: int) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        block = editor.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        editor.setTextCursor(cursor)
        editor.centerCursor()
        editor.setFocus()
        self.update_status()

    def insert_time_date(self) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        locale = QLocale.system()
        now = QDateTime.currentDateTime()
        text = (
            locale.toString(now.time(), QLocale.FormatType.ShortFormat)
            + " "
            + locale.toString(now.date(), QLocale.FormatType.ShortFormat)
        )
        editor.insertPlainText(text)

    def zoom_in(self) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.zoom_in()

    def zoom_out(self) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.zoom_out()

    def reset_zoom(self) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.reset_zoom()

    def on_word_wrap_toggled(self, checked: bool) -> None:
        settings = get_settings()
        settings["word_wrap"] = bool(checked)
        save_settings(settings)
        for window in OPEN_WINDOWS:
            window.apply_preferences()

    def on_status_bar_toggled(self, checked: bool) -> None:
        settings = get_settings()
        settings["status_bar"] = bool(checked)
        save_settings(settings)
        for window in OPEN_WINDOWS:
            window.apply_preferences()

    def show_settings(self) -> None:
        dialog = SettingsDialog(get_settings(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = get_settings()
        settings.update(dialog.result_settings())
        save_settings(settings)
        app = QApplication.instance()
        if app is not None:
            install_theme(app, str(settings.get("theme", "system")))
        for window in OPEN_WINDOWS:
            window.apply_preferences()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def page_setup(self) -> None:
        printer = printer_from_settings(get_settings())
        dialog = QPageSetupDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = get_settings()
        settings["page_setup"] = page_setup_from_printer(printer)
        save_settings(settings)

    def print_current(self) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        printer = printer_from_settings(get_settings())
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            editor.document().print_(printer)
        except Exception as error:
            QMessageBox.critical(self, "Notepad", f"Could not print.\n\n{error}")
            return
        settings = get_settings()
        settings["page_setup"] = page_setup_from_printer(printer)
        save_settings(settings)

    def close_current_tab(self) -> None:
        index = self.tabs.currentIndex()
        if index >= 0:
            self.close_tab_index(index)

    def close_tab_index(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if not isinstance(editor, Editor):
            return
        if not self.confirm_close_tab(editor):
            return
        self.tabs.removeTab(index)
        editor.deleteLater()
        schedule_session_save()
        if self.current_editor() is None:
            self.setWindowTitle("Notepad")
        self.update_status()

    def confirm_close_tab(self, editor: Editor) -> bool:
        if not editor.document().isModified():
            return True
        choice = self.ask_save(editor)
        if choice == "cancel":
            return False
        if choice == "save":
            return self.save_editor(editor)
        return True

    def ask_save(self, editor: Editor) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Notepad")
        box.setText(f"Do you want to save changes to {self.tab_name(editor)}?")
        save_button = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = box.addButton("Don't Save", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_button:
            return "save"
        if clicked is discard_button:
            return "discard"
        return "cancel"

    def confirm_for_exit(self, keep_in_session: bool) -> bool:
        if keep_in_session:
            return True
        decided: list[tuple[Editor, str]] = []
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if not isinstance(editor, Editor) or not editor.document().isModified():
                continue
            choice = self.ask_save(editor)
            if choice == "cancel":
                return False
            decided.append((editor, choice))
        for editor, choice in decided:
            if choice == "save" and not self.save_editor(editor):
                return False
        for editor, choice in decided:
            if choice == "discard":
                editor.discard_from_session = True
        return True

    def snapshot(self) -> dict:
        tabs = []
        current = self.current_editor()
        active = 0
        for index in range(self.tabs.count()):
            editor = self.tabs.widget(index)
            if not isinstance(editor, Editor) or editor.discard_from_session:
                continue
            if editor is current:
                active = len(tabs)
            tabs.append(self.editor_state(editor))
        return {
            "active_index": active,
            "tabs": tabs,
            "geometry": self.geometry_state(),
        }

    def editor_state(self, editor: Editor) -> dict:
        modified = bool(editor.document().isModified())
        state = {
            "path": editor.file_path,
            "encoding": editor.encoding,
            "newline": editor.newline,
            "zoom": editor.zoom_percent,
            "modified": modified,
            "untitled_name": editor.untitled_name,
        }
        if editor.file_path is None or modified:
            state["text"] = editor.toPlainText()
            if editor.file_path is None and state["text"]:
                state["modified"] = True
        return state

    def clear_tabs(self) -> None:
        while self.tabs.count():
            editor = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if editor is not None:
                editor.deleteLater()

    def apply_snapshot(self, snapshot: dict) -> None:
        self._loading = True
        try:
            self.clear_tabs()
            tabs = snapshot.get("tabs") if isinstance(snapshot, dict) else None
            if not isinstance(tabs, list):
                tabs = []
            for state in tabs:
                if isinstance(state, dict):
                    self.add_tab_from_state(state)
            active = 0
            if isinstance(snapshot, dict) and isinstance(snapshot.get("active_index"), int):
                active = snapshot["active_index"]
            if self.tabs.count():
                active = max(0, min(active, self.tabs.count() - 1))
                self.tabs.setCurrentIndex(active)
            geometry = snapshot.get("geometry") if isinstance(snapshot, dict) else None
            if isinstance(geometry, dict):
                self.apply_window_geometry(geometry)
            self.update_status()
        finally:
            self._loading = False

    def add_tab_from_state(self, state: dict) -> Editor:
        editor = self.create_editor()
        untitled = state.get("untitled_name")
        if isinstance(untitled, str) and untitled:
            editor.untitled_name = untitled
        else:
            editor.untitled_name = self.next_untitled_name()
        editor.encoding = normalize_encoding(state.get("encoding") if isinstance(state.get("encoding"), str) else None)
        editor.newline = normalize_newline_name(
            state.get("newline") if isinstance(state.get("newline"), str) else None
        )
        zoom = state.get("zoom", 100)
        if isinstance(zoom, (int, float)):
            editor.set_zoom(int(zoom))
        path = state.get("path") if isinstance(state.get("path"), str) and state.get("path") else None
        modified = bool(state.get("modified"))
        text = state.get("text") if isinstance(state.get("text"), str) else ""
        missing = False
        if path and not modified:
            editor.file_path = os.path.abspath(path)
            try:
                data = Path(editor.file_path).read_bytes()
            except OSError:
                missing = True
                editor.setPlainText(text)
                editor.document().setModified(True)
            else:
                loaded = load_bytes(data)
                editor.setPlainText(loaded.text)
                editor.encoding = loaded.encoding
                editor.newline = loaded.newline
                editor.document().setModified(False)
        else:
            editor.file_path = os.path.abspath(path) if path else None
            editor.setPlainText(text)
            if path:
                editor.document().setModified(True)
            else:
                editor.document().setModified(bool(text) or modified)
        self.add_editor(editor)
        if missing:
            self.show_status_message(f"Could not reload {path}")
        return editor

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = paths_from_mime(event.mimeData())
        if paths:
            self.open_paths(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def exit_application(self) -> None:
        global _quitting
        windows = list(OPEN_WINDOWS)
        keep = bool(get_settings().get("restore_session", True))
        for window in windows:
            if not window.confirm_for_exit(keep_in_session=keep):
                return
        stop_session_timer()
        save_session({"windows": [window.snapshot() for window in windows]})
        _quitting = True
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        stop_session_timer()
        if _quitting or self not in OPEN_WINDOWS:
            self._unregister()
            event.accept()
            return
        is_last = len(OPEN_WINDOWS) == 1
        keep = bool(get_settings().get("restore_session", True)) and is_last
        if not self.confirm_for_exit(keep_in_session=keep):
            event.ignore()
            return
        if is_last:
            save_session({"windows": [self.snapshot()]})
            self._unregister()
        else:
            self._unregister()
            save_open_session()
        event.accept()

    def _unregister(self) -> None:
        if self in OPEN_WINDOWS:
            OPEN_WINDOWS.remove(self)


add_theme_listener(refresh_open_windows_theme)
