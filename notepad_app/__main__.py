"""Launch Notepad with Fusion style and its own Windows taskbar identity."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from notepad_app.main_window import get_settings, open_initial_windows
from notepad_app.theme import install_theme

# Keeps this process off the generic python.exe taskbar group.
APP_USER_MODEL_ID = "PyNotepad.Desktop.Notepad"


def set_windows_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    if sys.platform != "win32":
        return
    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
        shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
        shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        return


def app_icon_file() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parent
    return base / "assets" / "notepad.ico"


def load_app_icon() -> QIcon:
    path = app_icon_file()
    if path.is_file():
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return make_app_icon()


def make_app_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#2b579a"))
    painter.drawRoundedRect(3, 2, 26, 28, 2, 2)
    painter.setBrush(QColor("#f7f7f7"))
    painter.drawRoundedRect(6, 6, 20, 21, 1, 1)
    painter.setPen(QColor("#2b579a"))
    for y in (11, 15, 19, 23):
        painter.drawLine(9, y, 22, y)
    painter.end()
    return QIcon(pixmap)


def main(argv: list[str] | None = None) -> int:
    set_windows_app_user_model_id()
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Notepad")
    app.setApplicationDisplayName("Notepad")
    app.setOrganizationName("PyNotepad")
    app.setStyle("Fusion")
    app.setWindowIcon(load_app_icon())
    app.setQuitOnLastWindowClosed(True)
    settings = get_settings()
    install_theme(app, str(settings.get("theme", "system")))
    open_initial_windows()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
