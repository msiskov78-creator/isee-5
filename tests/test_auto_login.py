"""Автоматическая отправка шести ячеек и восстановление формы после ошибки."""

import os
import threading
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from supabase_client import AuthError
from ui.login_window import LoginWindow
from ui.register_window import RegisterWindow


class AuthDouble:
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.failure = "Неверный логин или пароль."

    def sign_in(self, username, password):
        self.calls.append((username, password))
        self.gate.wait(3)
        if self.failure:
            raise AuthError(self.failure)
        return SimpleNamespace(user_metadata={"username": username})

    def sign_up(self, username, password):
        self.calls.append((username, password))
        return SimpleNamespace(user_metadata={"username": username})


class AutomaticLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.auth = AuthDouble()
        self.window = LoginWindow(self.auth, "student")
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()

    def wait_until(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def tearDown(self):
        self.auth.gate.set()
        self.wait_until(lambda: self.window.worker is None)
        self.window.close()
        self.app.processEvents()

    def test_sixth_character_starts_once_and_error_focuses_first(self):
        for index, character in enumerate("abc12"):
            QTest.keyClicks(self.window.password_boxes.boxes[index], character)
        self.assertEqual(self.auth.calls, [])
        QTest.keyClicks(self.window.password_boxes.boxes[5], "3")
        self.wait_until(lambda: bool(self.auth.calls))
        self.assertTrue(self.window.login_in_progress)
        self.assertEqual(self.window.button.text(), "Проверка...")
        self.assertFalse(self.window.password_boxes.isEnabled())
        self.window.button_clicked()
        self.window.password_boxes.submitted.emit()
        self.assertEqual(len(self.auth.calls), 1)
        self.auth.gate.set()
        self.wait_until(lambda: self.window.worker is None)
        self.assertFalse(self.window.login_in_progress)
        self.assertEqual(self.window.password_boxes.password(), "")
        self.assertIs(self.app.focusWidget(), self.window.password_boxes.boxes[0])
        self.assertIn("Неверный", self.window.error_label.text())

    def test_paste_starts_request_and_success_keeps_existing_animation(self):
        self.auth.failure = None
        spy = QSignalSpy(self.window.password_boxes.completed)
        self.window.password_boxes._paste(0, "abc123")
        self.wait_until(lambda: bool(self.auth.calls))
        self.assertEqual(spy.count(), 1)
        self.auth.gate.set()
        self.wait_until(lambda: self.window.worker is None)
        self.assertIs(self.window.stack.currentWidget(), self.window.animation)
        self.assertEqual(self.window.password_boxes.password(), "")

    def test_repeat_password_completes_registration(self):
        self.window.close()
        self.window = RegisterWindow(self.auth)
        self.window.show()
        self.window.username_input.setText("student")
        self.window.password_boxes._paste(0, "abc123")
        self.assertEqual(self.auth.calls, [])
        self.window.confirm_password_boxes._paste(0, "abc123")
        self.wait_until(lambda: self.window.worker is None and self.window.registered)
        self.assertEqual(self.auth.calls, [("student", "abc123")])


if __name__ == "__main__":
    unittest.main()
