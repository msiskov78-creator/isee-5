"""Регистрация по логину и двум одинаковым паролям из шести символов."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLineEdit, QPushButton, QVBoxLayout

from supabase_client import AuthError, AuthService, validate_password, validate_username
from ui.async_request import RequestWindow
from ui.auth_layout import build_auth_layout
from ui.password_boxes import PasswordBoxes
from ui.theme import APP_STYLE
from ui.widgets import label, message_label, primary_button, set_message, switch_window


class RegisterWindow(RequestWindow):
    def __init__(self, auth_service=None):
        super().__init__()
        self.auth_service = auth_service if auth_service is not None else AuthService()
        self.registered = False
        self.setWindowTitle("Gesture Control — регистрация")
        self.resize(1000, 750)
        self.setMinimumSize(950, 730)
        self.setStyleSheet(APP_STYLE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page, form = build_auth_layout("Создание аккаунта", "Создайте своё пространство управления.")
        outer.addWidget(page)
        form.addWidget(label("Логин"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Например, maxim33")
        self.username_input.setAccessibleName("Логин")
        self.username_input.setMaxLength(64)
        form.addWidget(self.username_input)
        form.addWidget(label("3–20 символов: латинские буквы, цифры и _", "muted"))
        form.addWidget(label("Пароль · 6 символов"))
        self.password_boxes = PasswordBoxes()
        form.addWidget(self.password_boxes)
        form.addWidget(label("Повторите пароль"))
        self.confirm_password_boxes = PasswordBoxes()
        form.addWidget(self.confirm_password_boxes)
        self.error_label = message_label()
        self.error_label.setMinimumHeight(44)
        form.addWidget(self.error_label)
        self.button = primary_button("Создать аккаунт  →")
        self.button.clicked.connect(self.register_clicked)
        form.addWidget(self.button)
        self.login_button = QPushButton("Уже есть аккаунт? Войти")
        self.login_button.setObjectName("link")
        self.login_button.clicked.connect(self.open_login)
        form.addWidget(self.login_button)
        self.username_input.returnPressed.connect(self.password_boxes.focus_first)
        self.password_boxes.submitted.connect(self.confirm_password_boxes.focus_first)
        self.confirm_password_boxes.submitted.connect(self.register_clicked)
        self.confirm_password_boxes.completed.connect(self._auto_register)
        # Таймер принадлежит окну и не сработает после его уничтожения.
        self.return_timer = QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.setInterval(1400)
        self.return_timer.timeout.connect(self.open_login)
        self.username_input.setFocus()

    def set_busy(self, busy):
        for widget in (self.username_input, self.password_boxes, self.confirm_password_boxes,
                       self.button, self.login_button):
            widget.setEnabled(not busy)
        self.button.setText("Создаём аккаунт…" if busy else "Создать аккаунт  →")

    def _auto_register(self):
        # Не отправляем неполную форму, когда пользователь начал с повторного пароля.
        if self.username_input.text().strip() and len(self.password_boxes.password()) == 6:
            self.register_clicked()

    def register_clicked(self):
        if self.worker is not None or self.registered:
            return
        try:
            username = validate_username(self.username_input.text())
            password = self.password_boxes.password()
            repeat = self.confirm_password_boxes.password()
            validate_password(password)
            validate_password(repeat)
            if password != repeat:
                raise AuthError("Пароли не совпадают. Повторите ввод.")
        except AuthError as error:
            set_message(self.error_label, str(error))
            return
        self._registered_username = username
        self.set_busy(True)
        set_message(self.error_label, "Создаём ваш аккаунт…", "muted")
        self.start_request(lambda: self.auth_service.sign_up(username, password), self.registration_finished)

    def registration_finished(self, user, error):
        self.password_boxes.clear_password()
        self.confirm_password_boxes.clear_password()
        if error:
            self.set_busy(False)
            set_message(self.error_label, error)
            self.password_boxes.focus_first()
            return
        self.registered = True
        self.button.setText("Аккаунт создан  ✓")
        set_message(self.error_label, "Аккаунт создан! Сейчас откроется окно входа.", "success")
        self.return_timer.start()

    def open_login(self):
        if self.worker is not None:
            return
        from ui.login_window import LoginWindow
        self.return_timer.stop()
        self.password_boxes.clear_password()
        self.confirm_password_boxes.clear_password()
        username = self._registered_username if self.registered else ""
        switch_window(self, LoginWindow(self.auth_service, username))

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.return_timer.stop()
            self.password_boxes.clear_password()
            self.confirm_password_boxes.clear_password()
