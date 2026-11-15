"""Вход через Supabase и переход к анимации только после успешного ответа."""

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtWidgets import QLineEdit, QPushButton, QStackedWidget, QVBoxLayout

from supabase_client import AuthError, AuthService, get_username, validate_password, validate_username
from ui.async_request import RequestWindow
from ui.auth_layout import build_auth_layout
from ui.login_animation import LoginAnimation
from ui.password_boxes import PasswordBoxes
from ui.theme import APP_STYLE
from ui.widgets import label, message_label, primary_button, set_message, switch_window


class LoginWindow(RequestWindow):
    def __init__(self, auth_service=None, username=""):
        super().__init__()
        self.auth_service = auth_service if auth_service is not None else AuthService()
        self.user = None
        self.login_in_progress = False
        self.setWindowTitle("Gesture Control — вход")
        self.resize(1000, 700)
        self.setMinimumSize(950, 680)
        self.setStyleSheet(APP_STYLE)

        # ==========================================
        # СОЗДАНИЕ ИНТЕРФЕЙСА
        # ==========================================
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.form_page, form = build_auth_layout(
            "Вход в аккаунт", "С возвращением. Продолжим с ваших настроек."
        )
        form.addWidget(label("Логин"))
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Введите логин")
        self.username_input.setAccessibleName("Логин")
        self.username_input.setText(username)
        self.username_input.setMaxLength(64)
        form.addWidget(self.username_input)
        form.addSpacing(4)
        form.addWidget(label("Пароль"))
        self.password_boxes = PasswordBoxes()
        form.addWidget(self.password_boxes)
        form.addWidget(label("6 символов вашего пароля", "muted"))
        self.error_label = message_label()
        self.error_label.setMinimumHeight(44)
        form.addWidget(self.error_label)
        self.button = primary_button("Войти  →")
        self.button.clicked.connect(self.button_clicked)
        form.addWidget(self.button)
        self.register_button = QPushButton("Нет аккаунта? Создать")
        self.register_button.setObjectName("link")
        self.register_button.clicked.connect(self.open_register)
        form.addWidget(self.register_button)
        self.stack.addWidget(self.form_page)
        self.animation = LoginAnimation()
        self.animation.finished.connect(self.open_main)
        self.stack.addWidget(self.animation)
        self.username_input.returnPressed.connect(self.password_boxes.focus_first)
        self.password_boxes.submitted.connect(self.button_clicked)
        self.password_boxes.completed.connect(self.button_clicked)
        self.username_input.setFocus()

    def set_busy(self, busy):
        self.login_in_progress = busy
        self.button.setEnabled(not busy)
        self.register_button.setEnabled(not busy)
        self.username_input.setEnabled(not busy)
        self.password_boxes.setEnabled(not busy)
        self.button.setText("Проверка..." if busy else "Войти  →")

    def show_error(self, message):
        set_message(self.error_label, message)
        self.password_boxes.clear_password()
        self.password_boxes.focus_first()

    def button_clicked(self):
        # Защищаем вход от повторного сигнала шестой ячейки и нажатия кнопки.
        if self.login_in_progress or self.worker is not None or self.stack.currentWidget() is self.animation:
            return
        try:
            # Получаем логин и проверяем, что введены все 6 символов пароля.
            username = validate_username(self.username_input.text())
            password = self.password_boxes.password()
            validate_password(password)
        except AuthError as error:
            self.show_error(str(error))
            return
        self._submitted_username = username
        set_message(self.error_label, "Подключаемся…", "muted")
        self.set_busy(True)
        self.start_request(lambda: self.auth_service.sign_in(username, password), self.login_finished)

    def login_finished(self, user, error):
        if error:
            self.set_busy(False)
            self.show_error(error)
            return
        self.user = user
        username = get_username(user, self._submitted_username)
        # Передаём только геометрию ячеек: анимация никогда не получает пароль.
        username_rect = QRectF(self.username_input.rect())
        username_rect.moveTopLeft(self.username_input.mapTo(self.form_page, QPoint(0, 0)))
        boxes_rects = []
        for box in self.password_boxes.boxes:
            rect = QRectF(box.rect())
            rect.moveTopLeft(box.mapTo(self.form_page, QPoint(0, 0)))
            boxes_rects.append(rect)
        self.password_boxes.clear_password()
        # Запускаем анимацию успешного входа; главное окно появится по finished.
        self.stack.setCurrentWidget(self.animation)
        self.animation.start(username, username_rect, boxes_rects)

    def open_register(self):
        if self.worker is not None:
            return
        from ui.register_window import RegisterWindow
        self.password_boxes.clear_password()
        switch_window(self, RegisterWindow(self.auth_service))

    def open_main(self):
        from ui.main_window import MainWindow
        switch_window(self, MainWindow(self.user, self.auth_service))

    def closeEvent(self, event):
        super().closeEvent(event)
        if event.isAccepted():
            self.animation.stop()
            self.password_boxes.clear_password()
