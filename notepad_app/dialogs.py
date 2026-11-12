"""Go to line, settings, and about dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFontDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)


def font_from_settings(settings: dict) -> QFont:
    """Build the editor font from saved family, size, weight, and italic."""
    font = QFont(str(settings.get("font_family") or "Consolas"))
    size = settings.get("font_size", 11)
    try:
        point_size = float(size)
    except (TypeError, ValueError):
        point_size = 11.0
    if point_size <= 0:
        point_size = 11.0
    font.setPointSizeF(point_size)
    weight = settings.get("font_weight", int(QFont.Weight.Normal))
    try:
        font.setWeight(QFont.Weight(int(weight)))
    except (TypeError, ValueError):
        font.setWeight(QFont.Weight.Normal)
    font.setItalic(bool(settings.get("font_italic", False)))
    return font


def font_settings(font: QFont) -> dict:
    point_size = font.pointSizeF()
    if point_size <= 0:
        point_size = float(font.pointSize()) if font.pointSize() > 0 else 11.0
    return {
        "font_family": font.family() or "Consolas",
        "font_size": int(round(point_size)),
        "font_weight": int(font.weight()),
        "font_italic": bool(font.italic()),
    }


def font_label(font: QFont) -> str:
    point_size = font.pointSize()
    if point_size <= 0:
        point_size = int(round(font.pointSizeF())) if font.pointSizeF() > 0 else 11
    style = _style_label(font) or "Regular"
    return f"{font.family()}, {style}, {point_size} pt"


def unpack_font_dialog(result) -> tuple[bool, QFont]:
    """PySide6 QFontDialog.getFont returns (ok, font), not (font, ok)."""
    if isinstance(result, tuple) and len(result) >= 2:
        if isinstance(result[1], QFont):
            return bool(result[0]), result[1]
        if isinstance(result[0], QFont):
            return bool(result[1]), result[0]
    return False, QFont()


def _style_label(font: QFont) -> str:
    name = (font.styleName() or "").strip()
    if name and name.lower() not in {"regular", "normal", "roman", "book"}:
        return name
    weight = int(font.weight())
    italic = font.italic()
    normal = int(QFont.Weight.Normal)
    if weight == normal and not italic:
        return ""
    named = (
        (int(QFont.Weight.Thin), "Thin"),
        (int(QFont.Weight.ExtraLight), "Extra Light"),
        (int(QFont.Weight.Light), "Light"),
        (int(QFont.Weight.Medium), "Medium"),
        (int(QFont.Weight.DemiBold), "Semibold"),
        (int(QFont.Weight.Bold), "Bold"),
        (int(QFont.Weight.ExtraBold), "Extra Bold"),
        (int(QFont.Weight.Black), "Black"),
    )
    label = "" if weight == normal else min(named, key=lambda item: abs(item[0] - weight))[1]
    if italic:
        return f"{label} Italic".strip()
    return label


class GoToDialog(QDialog):
    def __init__(self, current: int, maximum: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to line")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.spin = QSpinBox()
        upper = max(1, maximum)
        self.spin.setRange(1, upper)
        self.spin.setValue(min(max(1, current), upper))
        form.addRow("Line number:", self.spin)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.spin.setFocus()
        self.spin.selectAll()

    def line_number(self) -> int:
        return int(self.spin.value())


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self._font = font_from_settings(settings)

        layout = QVBoxLayout(self)

        theme_box = QGroupBox("Theme")
        theme_layout = QVBoxLayout(theme_box)
        self.theme_group = QButtonGroup(self)
        self.theme_system = QRadioButton("Match Windows")
        self.theme_light = QRadioButton("Light")
        self.theme_dark = QRadioButton("Dark")
        for button in (self.theme_system, self.theme_light, self.theme_dark):
            self.theme_group.addButton(button)
            theme_layout.addWidget(button)
        theme = settings.get("theme", "system")
        if theme == "light":
            self.theme_light.setChecked(True)
        elif theme == "dark":
            self.theme_dark.setChecked(True)
        else:
            self.theme_system.setChecked(True)

        font_box = QGroupBox("Font")
        font_layout = QHBoxLayout(font_box)
        self.font_label = QLabel(font_label(self._font))
        change = QPushButton("Change...")
        change.clicked.connect(self._choose_font)
        font_layout.addWidget(self.font_label, 1)
        font_layout.addWidget(change)

        self.word_wrap = QCheckBox("Word wrap")
        self.word_wrap.setChecked(bool(settings.get("word_wrap", True)))
        self.status_bar = QCheckBox("Status bar")
        self.status_bar.setChecked(bool(settings.get("status_bar", True)))

        startup = QGroupBox("When Notepad starts")
        startup_layout = QVBoxLayout(startup)
        self.startup_group = QButtonGroup(self)
        self.startup_restore = QRadioButton("Continue the previous session")
        self.startup_empty = QRadioButton("Start empty")
        self.startup_group.addButton(self.startup_restore)
        self.startup_group.addButton(self.startup_empty)
        startup_layout.addWidget(self.startup_restore)
        startup_layout.addWidget(self.startup_empty)
        if settings.get("restore_session", True):
            self.startup_restore.setChecked(True)
        else:
            self.startup_empty.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(theme_box)
        layout.addWidget(font_box)
        layout.addWidget(self.word_wrap)
        layout.addWidget(self.status_bar)
        layout.addWidget(startup)
        layout.addWidget(buttons)
        self.resize(420, 380)

    def _choose_font(self) -> None:
        # getFont returns (ok, font). Reading family() from the bool crashes.
        ok, font = unpack_font_dialog(QFontDialog.getFont(self._font, self, "Font"))
        if not ok:
            return
        if font.pointSizeF() <= 0 and font.pointSize() <= 0:
            fallback = self._font.pointSize() if self._font.pointSize() > 0 else 11
            font.setPointSize(fallback)
        self._font = QFont(font)
        self.font_label.setText(font_label(self._font))

    def result_settings(self) -> dict:
        if self.theme_dark.isChecked():
            theme = "dark"
        elif self.theme_light.isChecked():
            theme = "light"
        else:
            theme = "system"
        values = {
            "theme": theme,
            "word_wrap": self.word_wrap.isChecked(),
            "status_bar": self.status_bar.isChecked(),
            "restore_session": self.startup_restore.isChecked(),
        }
        values.update(font_settings(self._font))
        return values


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Notepad")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(8)

        icon = QApplication.windowIcon()
        if not icon.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(48, 48))
            layout.addWidget(icon_label)

        name = QLabel("Notepad")
        name.setObjectName("aboutAppName")
        name_font = name.font()
        name_font.setPointSize(name_font.pointSize() + 8)
        name_font.setBold(True)
        name.setFont(name_font)

        description = QLabel("A plain text editor")
        copyright_label = QLabel("Copyright 2026 - Saif Al Badri")
        copyright_label.setObjectName("aboutCopyright")
        copyright_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)

        layout.addWidget(name)
        layout.addWidget(description)
        layout.addSpacing(8)
        layout.addWidget(copyright_label)
        layout.addSpacing(8)
        layout.addWidget(buttons)
        self.setMinimumWidth(320)
