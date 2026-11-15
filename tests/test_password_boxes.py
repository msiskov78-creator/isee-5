"""Проверки реальных событий клавиатуры для компонента пароля."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from ui.password_boxes import PasswordBox, PasswordBoxes


class PasswordBoxesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = PasswordBoxes()
        self.widget.show()
        self.widget.activateWindow()
        self.widget.focus_first()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def test_typing_masking_and_automatic_focus(self):
        for index, character in enumerate("abc123"):
            box = self.widget.boxes[index]
            self.assertIs(self.app.focusWidget(), box)
            self.assertIsInstance(box, PasswordBox)
            self.assertEqual(box.maxLength(), 1)
            self.assertEqual(box.echoMode(), QLineEdit.EchoMode.Password)
            QTest.keyClicks(box, character)
        self.assertEqual(self.widget.password(), "abc123")
        self.assertIs(self.app.focusWidget(), self.widget.boxes[5])

    def test_backspace_clears_current_then_previous(self):
        self.widget._paste(0, "abc123")
        QTest.keyClick(self.widget.boxes[5], Qt.Key.Key_Backspace)
        self.assertEqual(self.widget.password(), "abc12")
        self.assertIs(self.app.focusWidget(), self.widget.boxes[5])
        QTest.keyClick(self.widget.boxes[5], Qt.Key.Key_Backspace)
        self.assertEqual(self.widget.password(), "abc1")
        self.assertIs(self.app.focusWidget(), self.widget.boxes[4])
        self.widget.clear_password()
        self.widget.focus_first()
        QTest.keyClick(self.widget.boxes[0], Qt.Key.Key_Backspace)
        self.assertIs(self.app.focusWidget(), self.widget.boxes[0])

    def test_filled_cell_can_be_corrected_at_start_of_text(self):
        self.widget._paste(0, "abc123")
        self.widget.boxes[1].setFocus()
        self.widget.boxes[1].setCursorPosition(0)
        QTest.keyClicks(self.widget.boxes[1], "Z")
        self.assertEqual(self.widget.password(), "aZc123")
        self.assertIs(self.app.focusWidget(), self.widget.boxes[2])

    def test_keyboard_paste_and_return(self):
        self.app.clipboard().setText("abc123EXTRA\n")
        QTest.keyClick(self.widget.boxes[0], Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.widget.password(), "abc123")
        spy = QSignalSpy(self.widget.submitted)
        QTest.keyClick(self.widget.boxes[5], Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)
        self.widget.clear_password()
        self.assertEqual(self.widget.password(), "")
        self.app.clipboard().clear()


if __name__ == "__main__":
    unittest.main()
