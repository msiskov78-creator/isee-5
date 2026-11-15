"""Проверяем реальные переходы Qt; вместо Supabase используем тестовый сервис."""

import os
import sys
import threading
import time
from types import SimpleNamespace
import unittest

# Окна участвуют в обычном цикле событий, но не перекрывают рабочий стол.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from shiboken6 import isValid

from supabase_client import AuthError
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.register_window import RegisterWindow


class FakeAuthService:
    """Задерживаем ответ событием потока, не останавливая интерфейс Qt."""

    def __init__(self):
        self.user = SimpleNamespace(
            id="test-account-id", user_metadata={"username": "maxim33"},
            created_at="2026-01-01T12:00:00+00:00",
        )
        self.calls = []
        self.login_error = None
        self.logout_error = None
        self.login_started = threading.Event()
        self.login_gate = threading.Event()
        self.login_gate.set()

    def configuration_error(self):
        return ""

    @property
    def configured(self):
        return True

    def sign_in(self, username, password):
        self.calls.append(("sign_in", username, password))
        self.login_started.set()
        if not self.login_gate.wait(5):
            raise AuthError("Тестовый ответ не был разрешён вовремя.")
        if self.login_error:
            raise AuthError(self.login_error)
        return self.user

    def sign_up(self, username, password):
        self.calls.append(("sign_up", username, password))
        return self.user

    def sign_out(self):
        self.calls.append(("sign_out",))
        if self.logout_error:
            raise AuthError(self.logout_error)


class AppFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.auth = FakeAuthService()
        self.callback_errors = []
        self.qt_errors = []
        self.previous_exception_hook = sys.excepthook
        sys.excepthook = lambda kind, value, traceback: self.callback_errors.append(f"{kind.__name__}: {value}")
        self.previous_message_handler = qInstallMessageHandler(self.capture_qt_message)
        self.open_window(LoginWindow(self.auth))

    def capture_qt_message(self, kind, context, message):
        if kind in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) or any(
            text in message for text in ("QThread: Destroyed", "Cannot create children", "different thread", "Timers cannot")
        ):
            self.qt_errors.append(message)

    def tearDown(self):
        # Даже после неудачной проверки освобождаем запрос перед удалением окна.
        self.auth.login_gate.set()
        deadline = time.monotonic() + 2
        while any(getattr(window, "worker", None) is not None for window in self.app.topLevelWidgets() if isValid(window)):
            if time.monotonic() > deadline:
                break
            QTest.qWait(10)
        for window in self.app.topLevelWidgets():
            if isValid(window):
                window.close()
        QTest.qWait(40)
        self.app.current_window = None
        sys.excepthook = self.previous_exception_hook
        qInstallMessageHandler(self.previous_message_handler)
        self.assertEqual(self.callback_errors, [], "Исключение в обработчике интерфейса")
        self.assertEqual(self.qt_errors, [], "Ошибка жизненного цикла Qt")

    def open_window(self, window):
        self.app.current_window = window
        window.show()
        window.activateWindow()
        QTest.qWait(30)
        return window

    def wait_until(self, predicate, timeout=2000, message="Ожидаемое событие не произошло"):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(10)
        self.assertTrue(predicate(), message)

    def current_is(self, window_class):
        window = getattr(self.app, "current_window", None)
        return window is not None and isValid(window) and isinstance(window, window_class)

    def enter_password(self, boxes, password="abc123"):
        for box, character in zip(boxes.boxes, password):
            QTest.mouseClick(box, Qt.MouseButton.LeftButton)
            QTest.keyClicks(box, character)

    def enter_login(self, window):
        QTest.keyClicks(window.username_input, "maxim33")
        self.enter_password(window.password_boxes)

    def click(self, button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    def test_login_register_navigation_both_directions(self):
        login = self.app.current_window
        self.enter_password(login.password_boxes)
        self.click(login.register_button)
        self.wait_until(lambda: self.current_is(RegisterWindow))
        register = self.app.current_window
        self.assertEqual(register.password_boxes.password(), "")
        self.assertEqual(register.confirm_password_boxes.password(), "")
        self.click(register.login_button)
        self.wait_until(lambda: self.current_is(LoginWindow))
        self.assertEqual(self.app.current_window.password_boxes.password(), "")
        self.assertEqual(self.auth.calls, [])

    def test_invalid_forms_do_not_start_requests_or_animation(self):
        login = self.app.current_window
        animation_finished = QSignalSpy(login.animation.finished)
        self.click(login.button)
        self.assertIn("логин", login.error_label.text().lower())
        QTest.keyClicks(login.username_input, "maxim33")
        self.enter_password(login.password_boxes, "123")
        self.click(login.button)
        self.assertIn("6", login.error_label.text())
        self.assertEqual(login.password_boxes.password(), "")
        self.assertIs(login.stack.currentWidget(), login.form_page)
        self.assertEqual(animation_finished.count(), 0)
        self.assertEqual(self.auth.calls, [])

        self.click(login.register_button)
        self.wait_until(lambda: self.current_is(RegisterWindow))
        register = self.app.current_window
        self.enter_login(register)
        self.enter_password(register.confirm_password_boxes, "abc124")
        self.click(register.button)
        self.assertIn("не совпадают", register.error_label.text())
        self.assertTrue(register.button.isEnabled())
        self.assertEqual(self.auth.calls, [])

    def test_pending_login_is_responsive_and_failure_clears_password(self):
        login = self.app.current_window
        self.auth.login_gate.clear()
        self.auth.login_error = "Неверный логин или пароль."
        animation_finished = QSignalSpy(login.animation.finished)
        self.enter_login(login)
        ticks = []
        heartbeat = QTimer(login)
        heartbeat.setInterval(20)
        heartbeat.timeout.connect(lambda: ticks.append(True))
        heartbeat.start()
        self.click(login.button)
        self.wait_until(self.auth.login_started.is_set)
        self.assertFalse(login.button.isEnabled())
        self.assertFalse(login.register_button.isEnabled())
        QTest.qWait(150)
        self.assertGreaterEqual(len(ticks), 3, "Цикл событий Qt остановился во время запроса")
        self.click(login.button)
        self.assertEqual(len(self.auth.calls), 1)
        self.auth.login_gate.set()
        self.wait_until(lambda: login.worker is None)
        self.assertTrue(login.button.isEnabled())
        self.assertTrue(login.register_button.isEnabled())
        self.assertEqual(login.password_boxes.password(), "")
        self.assertIn("Неверный", login.error_label.text())
        self.assertIs(login.stack.currentWidget(), login.form_page)
        self.assertEqual(animation_finished.count(), 0)

    def test_signup_shows_success_before_delayed_return_to_login(self):
        self.click(self.app.current_window.register_button)
        self.wait_until(lambda: self.current_is(RegisterWindow))
        register = self.app.current_window
        self.enter_login(register)
        self.enter_password(register.confirm_password_boxes)
        self.click(register.button)
        self.wait_until(lambda: register.worker is None and register.registered)
        self.assertIn("Аккаунт создан", register.error_label.text())
        self.assertEqual(register.password_boxes.password(), "")
        self.assertEqual(register.confirm_password_boxes.password(), "")
        QTest.qWait(300)
        self.assertTrue(self.current_is(RegisterWindow), "Сообщение об успехе исчезло слишком быстро")
        self.wait_until(lambda: self.current_is(LoginWindow))
        login = self.app.current_window
        self.assertEqual(login.username_input.text(), "maxim33")
        self.assertEqual(login.password_boxes.password(), "")
        self.assertEqual(self.auth.calls, [("sign_up", "maxim33", "abc123")])

    def test_successful_login_animation_pages_and_logout_retry(self):
        login = self.app.current_window
        self.enter_login(login)
        animation_finished = QSignalSpy(login.animation.finished)
        self.click(login.button)
        self.wait_until(lambda: login.worker is None and login.stack.currentWidget() is login.animation)
        animation_started = time.monotonic()
        self.assertEqual(login.password_boxes.password(), "")
        self.assertEqual(animation_finished.count(), 0)
        QTest.qWait(7000)
        self.assertTrue(self.current_is(LoginWindow), "Главное окно открылось до окончания анимации")
        self.assertEqual(animation_finished.count(), 0)
        self.wait_until(lambda: self.current_is(MainWindow), timeout=4000)
        animation_seconds = time.monotonic() - animation_started
        self.assertGreaterEqual(animation_seconds, 8.5)
        self.assertLess(animation_seconds, 10.5)
        self.assertEqual(animation_finished.count(), 1)
        main = self.app.current_window
        self.assertEqual(main.username, "maxim33")

        for name, button in main.nav_buttons.items():
            with self.subTest(page=name):
                self.click(button)
                self.assertIs(main.stack.currentWidget().widget(), main.pages[name])
                self.assertTrue(button.isChecked())
                self.assertEqual(sum(item.isChecked() for item in main.nav_buttons.values()), 1)
                self.assertIs(self.app.current_window, main)

        # Проверяем кнопки домашней страницы через настоящие clicked/signals.
        for title, name in (("Мои жесты", "gestures"), ("Профили", "profiles"), ("Настройки", "settings")):
            self.click(main.nav_buttons["home"])
            shortcut = next(button for button in main.pages["home"].findChildren(QPushButton) if button.text().startswith(title))
            self.click(shortcut)
            self.assertIs(main.stack.currentWidget().widget(), main.pages[name])
        visible_texts = [label.text() for label in main.findChildren(QLabel)]
        self.assertFalse(any("@gesturecontrol.local" in text for text in visible_texts))

        self.auth.logout_error = "Нет соединения с Supabase. Повторите попытку."
        self.click(main.logout_button)
        self.wait_until(lambda: main.worker is None)
        self.assertIs(self.app.current_window, main)
        self.assertTrue(main.logout_button.isEnabled())
        self.assertTrue(main.pages["account"].logout_button.isEnabled())
        self.assertIn("Нет соединения", main.status_label.text())
        self.auth.logout_error = None
        self.click(main.nav_buttons["account"])
        self.click(main.pages["account"].logout_button)
        self.wait_until(lambda: self.current_is(LoginWindow))
        self.assertEqual(self.app.current_window.password_boxes.password(), "")
        self.assertEqual([call[0] for call in self.auth.calls], ["sign_in", "sign_out", "sign_out"])

    def test_close_during_pending_request_waits_without_opening_next_window(self):
        login = self.app.current_window
        self.auth.login_gate.clear()
        self.enter_login(login)
        self.click(login.button)
        self.wait_until(self.auth.login_started.is_set)
        login.close()
        QTest.qWait(50)
        self.assertTrue(isValid(login), "Окно уничтожило ещё работающий поток")
        self.assertIn("завершение запроса", login.windowTitle())
        self.auth.login_gate.set()
        self.wait_until(lambda: not isValid(login))
        self.assertFalse(any(
            isinstance(window, (LoginWindow, RegisterWindow, MainWindow)) and window.isVisible()
            for window in self.app.topLevelWidgets() if isValid(window)
        ))


if __name__ == "__main__":
    unittest.main()
