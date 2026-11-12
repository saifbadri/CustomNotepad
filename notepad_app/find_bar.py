"""Find and replace bar shown above the editor."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FindReplaceBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FindReplaceBar")
        self._editor_provider: Callable[[], object | None] = lambda: None
        self._message: Callable[[str], None] = lambda _text: None

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace")
        self.match_case = QCheckBox("Match case")
        self.wrap_around = QCheckBox("Wrap around")
        self.wrap_around.setChecked(True)

        self.next_button = QPushButton("Find next")
        self.previous_button = QPushButton("Find previous")
        self.replace_button = QPushButton("Replace")
        self.replace_all_button = QPushButton("Replace all")
        self.close_button = QPushButton("Close")

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find"))
        find_row.addWidget(self.find_edit, 1)
        find_row.addWidget(self.next_button)
        find_row.addWidget(self.previous_button)
        find_row.addWidget(self.close_button)

        self.replace_row = QWidget()
        replace_layout = QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.addWidget(QLabel("Replace"))
        replace_layout.addWidget(self.replace_edit, 1)
        replace_layout.addWidget(self.replace_button)
        replace_layout.addWidget(self.replace_all_button)

        options = QHBoxLayout()
        options.addWidget(self.match_case)
        options.addWidget(self.wrap_around)
        options.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(find_row)
        layout.addWidget(self.replace_row)
        layout.addLayout(options)

        self.next_button.clicked.connect(self.find_next)
        self.previous_button.clicked.connect(self.find_previous)
        self.replace_button.clicked.connect(self.replace_one)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.close_button.clicked.connect(self.dismiss)
        self.find_edit.returnPressed.connect(self.find_next)
        self.replace_edit.returnPressed.connect(self.replace_one)

        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self.dismiss)
        self.replace_row.hide()

    def set_callbacks(self, editor_provider, message) -> None:
        self._editor_provider = editor_provider
        self._message = message

    def show_find(self) -> None:
        self.replace_row.hide()
        self._prefill_from_selection()
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def show_replace(self) -> None:
        self.replace_row.show()
        self._prefill_from_selection()
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def dismiss(self) -> None:
        self.hide()
        editor = self._editor()
        if editor is not None:
            editor.setFocus()

    def find_next(self) -> bool:
        return self._find(backward=False)

    def find_previous(self) -> bool:
        return self._find(backward=True)

    def replace_one(self) -> None:
        editor = self._editor()
        term = self.find_edit.text()
        if editor is None or term == "":
            self._message("Enter text to find.")
            return
        cursor = editor.textCursor()
        selected = _selection_text(cursor)
        if cursor.hasSelection() and self._same(selected, term):
            cursor.insertText(self.replace_edit.text())
        self.find_next()

    def replace_all(self) -> int:
        editor = self._editor()
        term = self.find_edit.text()
        if editor is None or term == "":
            self._message("Enter text to find.")
            return 0
        replacement = self.replace_edit.text()
        flags = self._flags(backward=False)
        document = editor.document()
        original_length = len(editor.toPlainText())
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        count = 0
        try:
            search = QTextCursor(document)
            search.setPosition(0)
            while count <= original_length:
                found = document.find(term, search, flags)
                if found.isNull():
                    break
                found.insertText(replacement)
                count += 1
                search = QTextCursor(document)
                search.setPosition(found.position())
        finally:
            cursor.endEditBlock()
        noun = "occurrence" if count == 1 else "occurrences"
        self._message(f"Replaced {count} {noun}.")
        return count

    def _editor(self):
        editor = self._editor_provider()
        return editor

    def _prefill_from_selection(self) -> None:
        editor = self._editor()
        if editor is None:
            return
        selected = _selection_text(editor.textCursor()).replace("\n", "")
        if selected:
            self.find_edit.setText(selected)

    def _same(self, left: str, right: str) -> bool:
        if self.match_case.isChecked():
            return left == right
        return left.casefold() == right.casefold()

    def _flags(self, backward: bool):
        flags = QTextDocument.FindFlags()
        if self.match_case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        return flags

    def _find(self, backward: bool) -> bool:
        editor = self._editor()
        term = self.find_edit.text()
        if editor is None or term == "":
            if term == "":
                self._message("Enter text to find.")
            return False
        original = editor.textCursor()
        cursor = editor.textCursor()
        if cursor.hasSelection() and self._same(_selection_text(cursor), term):
            position = cursor.selectionStart() if backward else cursor.selectionEnd()
            cursor.setPosition(position)
            editor.setTextCursor(cursor)
        flags = self._flags(backward)
        if editor.find(term, flags):
            return True
        if not self.wrap_around.isChecked():
            editor.setTextCursor(original)
            self._message(f'Cannot find "{term}"')
            return False
        wrapped = editor.textCursor()
        move = QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
        wrapped.movePosition(move)
        editor.setTextCursor(wrapped)
        if editor.find(term, flags):
            return True
        editor.setTextCursor(original)
        self._message(f'Cannot find "{term}"')
        return False


def _selection_text(cursor: QTextCursor) -> str:
    return cursor.selectedText().replace("\u2029", "\n")
