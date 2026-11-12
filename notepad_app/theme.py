"""Light, dark, and match-Windows palettes for the Fusion style."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

_mode = "system"
_dark = False
_hooked = False
_listeners: list[Callable[[], None]] = []


def current_mode() -> str:
    return _mode


def theme_is_dark() -> bool:
    return _dark


def add_theme_listener(callback: Callable[[], None]) -> None:
    if callback not in _listeners:
        _listeners.append(callback)


def _scheme_is_dark(app, mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    scheme = app.styleHints().colorScheme()
    return scheme == Qt.ColorScheme.Dark


def light_palette() -> QPalette:
    palette = QPalette()
    window = QColor("#f3f3f3")
    base = QColor("#ffffff")
    text = QColor("#1a1a1a")
    button = QColor("#f3f3f3")
    highlight = QColor("#0078d4")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b6b6b"))
    disabled = QColor("#8a8a8a")
    group = QPalette.ColorGroup.Disabled
    palette.setColor(group, QPalette.ColorRole.Text, disabled)
    palette.setColor(group, QPalette.ColorRole.WindowText, disabled)
    palette.setColor(group, QPalette.ColorRole.ButtonText, disabled)
    return palette


def dark_palette() -> QPalette:
    palette = QPalette()
    window = QColor("#202020")
    base = QColor("#1a1a1a")
    text = QColor("#f3f3f3")
    button = QColor("#2d2d2d")
    highlight = QColor("#0078d4")
    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2a2a2a"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2d2d2d"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9a9a9a"))
    disabled = QColor("#7a7a7a")
    group = QPalette.ColorGroup.Disabled
    palette.setColor(group, QPalette.ColorRole.Text, disabled)
    palette.setColor(group, QPalette.ColorRole.WindowText, disabled)
    palette.setColor(group, QPalette.ColorRole.ButtonText, disabled)
    return palette


def stylesheet(dark: bool) -> str:
    if dark:
        background = "#1a1a1a"
        tab = "#2d2d2d"
        selected = "#1a1a1a"
        text = "#f3f3f3"
        border = "#3f3f3f"
        find_background = "#252525"
        status = "#202020"
    else:
        background = "#ffffff"
        tab = "#f3f3f3"
        selected = "#ffffff"
        text = "#1a1a1a"
        border = "#e1e1e1"
        find_background = "#f6f6f6"
        status = "#f3f3f3"
    return f"""
    QPlainTextEdit {{
        background: {background};
        color: {text};
        selection-background-color: #0078d4;
        selection-color: #ffffff;
        border: none;
    }}
    QTabWidget::pane {{
        border: none;
        background: {background};
    }}
    QTabBar::tab {{
        background: {tab};
        color: {text};
        padding: 6px 14px;
        border: 1px solid {border};
        border-bottom: none;
        margin-right: 2px;
        min-height: 18px;
    }}
    QTabBar::tab:selected {{
        background: {selected};
    }}
    QStatusBar {{
        background: {status};
        color: {text};
    }}
    QStatusBar QLabel {{
        color: {text};
        padding-left: 6px;
        padding-right: 6px;
    }}
    QStatusBar QToolButton {{
        color: {text};
        padding: 2px 8px;
        border: none;
    }}
    QWidget#FindReplaceBar {{
        background: {find_background};
        border-bottom: 1px solid {border};
    }}
    """


def apply_theme(app, mode: str) -> None:
    global _mode, _dark
    if mode not in ("system", "light", "dark"):
        mode = "system"
    _mode = mode
    _dark = _scheme_is_dark(app, mode)
    app.setPalette(dark_palette() if _dark else light_palette())
    app.setStyleSheet(stylesheet(_dark))


def install_theme(app, mode: str) -> None:
    global _hooked
    apply_theme(app, mode)
    if _hooked:
        return
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_args: _on_scheme_changed(app))
    _hooked = True


def _on_scheme_changed(app) -> None:
    if _mode != "system":
        return
    apply_theme(app, "system")
    for callback in list(_listeners):
        callback()


def set_windows_titlebar_dark(widget, dark: bool) -> None:
    """Use the Windows 11 immersive dark title bar when a window handle exists."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    if not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        # 20 is DWMWA_USE_IMMERSIVE_DARK_MODE; 19 is the older attribute.
        for attribute in (20, 19):
            dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
    except Exception:
        return
