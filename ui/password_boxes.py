"""Шесть отдельных ячеек пароля для входа и регистрации."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QMenu, QWidget


class PasswordBox(QLineEdit):
    """Одна ячейка: отдельно обрабатываем Backspace и вставку пароля."""

    empty_backspace = Signal()
    paste_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("passwordBox")
        self.setMaxLength(1)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(52, 58)
        self.setInputMethodHints(
            Qt.InputMethodHint.ImhHiddenText
            | Qt.InputMethodHint.ImhNoPredictiveText
            | Qt.InputMethodHint.ImhSensitiveData
        )

    def keyPressEvent(self, event):
        # Backspace удаляет символ независимо от положения курсора внутри ячейки.
        if event.key() == Qt.Key.Key_Backspace:
            if self.text():
                self.clear()
            else:
                self.empty_backspace.emit()
            event.accept()
            return

        # Вставляем сразу несколько символов через общий компонент PasswordBoxes.
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit(QApplication.clipboard().text())
            event.accept()
            return

        # При исправлении заполненной ячейки новый символ заменяет старый.
        if event.text() and event.text().isprintable() and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self.selectAll()
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        # Своя команда вставки не теряет пять символов из-за maxLength(1).
        menu = QMenu(self)
        paste_action = menu.addAction("Вставить")
        paste_action.setEnabled(bool(QApplication.clipboard().text()) and self.isEnabled())
        clear_action = menu.addAction("Очистить ячейку")
        clear_action.setEnabled(bool(self.text()))
        action = menu.exec(event.globalPos())
        if action == paste_action:
            self.paste_requested.emit(QApplication.clipboard().text())
        elif action == clear_action:
            self.clear()


class PasswordBoxes(QWidget):
    submitted = Signal()
    completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.boxes = []
        self._filling = False
        self._was_complete = False

        # ==========================================
        # СОЗДАНИЕ ШЕСТИ ЯЧЕЕК ПАРОЛЯ
        # ==========================================
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for index in range(6):
            box = PasswordBox(self)
            box.setAccessibleName(f"Символ пароля {index + 1} из 6")
            box.textChanged.connect(lambda text, i=index: self.move_next(i, text))
            box.empty_backspace.connect(lambda i=index: self._erase_previous(i))
            box.paste_requested.connect(lambda text, i=index: self._paste(i, text))
            box.returnPressed.connect(self.submitted.emit)
            self.boxes.append(box)
            layout.addWidget(box)
        self.setFixedSize(362, 58)
        self.setFocusProxy(self.boxes[0])

    def move_next(self, index, text):
        # После ввода символа сразу переходим к следующей ячейке.
        if text and index < 5 and not self._filling:
            self.boxes[index + 1].setFocus()
            self.boxes[index + 1].selectAll()
        if not self._filling:
            self._check_complete()

    def _check_complete(self):
        # Сигнал возникает один раз при заполнении всех ячеек, в том числе вставкой.
        complete = all(bool(box.text()) for box in self.boxes)
        newly_complete = complete and not self._was_complete
        self._was_complete = complete
        if newly_complete:
            self.completed.emit()

    def _erase_previous(self, index):
        if index > 0:
            self.boxes[index - 1].clear()
            self.boxes[index - 1].setFocus()

    def _paste(self, index, text):
        # Переносы строк из буфера не становятся невидимой частью пароля.
        characters = [character for character in text if character.isprintable()]
        if not characters:
            return
        self._filling = True
        try:
            for position, character in enumerate(characters[:6 - index], start=index):
                self.boxes[position].setText(character)
        finally:
            self._filling = False
        next_index = min(index + len(characters), 5)
        self.boxes[next_index].setFocus()
        self.boxes[next_index].selectAll()
        self._check_complete()

    def password(self):
        # Пароль существует только в полях формы и в запросе к Supabase Auth.
        return "".join(box.text() for box in self.boxes)

    def clear_password(self):
        for box in self.boxes:
            box.clear()

    def focus_first(self):
        self.boxes[0].setFocus()
        self.boxes[0].selectAll()
