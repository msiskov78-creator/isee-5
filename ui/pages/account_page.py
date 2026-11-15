"""Информация об аккаунте без технического email и пароля."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui.widgets import card, label, page_header


class AccountPage(QWidget):
    logout_requested = Signal()

    def __init__(self, username, user):
        super().__init__()

        # ==========================================
        # СОЗДАНИЕ ИНТЕРФЕЙСА
        # ==========================================
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        page_header(layout, "Аккаунт", "Ваш профиль в Gesture Control.")

        identity = card()
        top = QHBoxLayout()
        avatar = label(username[:2].upper(), "stat")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(64, 64)
        avatar.setStyleSheet("background: #202e52; color: #9cb5ff; border: 1px solid #344b81; border-radius: 20px; font-size: 24px; font-weight: 600;")
        top.addWidget(avatar)
        summary = QVBoxLayout()
        summary.setSpacing(6)
        summary.addWidget(label(username, "section"))
        summary.addWidget(label("Личный аккаунт", "muted"))
        top.addLayout(summary)
        top.addStretch()
        top.addWidget(label("●  В сети", "badge"))
        identity.layout().addLayout(top)
        layout.addWidget(identity)

        details = card()
        details.layout().addWidget(label("Данные аккаунта", "section"))
        # Supabase возвращает объект User; словарь удобен для локальной проверки.
        user_id = self._user_value(user, "id")
        created_at = self._user_value(user, "created_at")
        for title, value in (
            ("Логин", username),
            ("ID пользователя", str(user_id) if user_id else "Не указан"),
            ("Дата регистрации", self._format_date(created_at)),
        ):
            details.layout().addWidget(label(title, "muted"))
            value_label = label(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.layout().addWidget(value_label)
        layout.addWidget(details)

        session = card()
        session.layout().addWidget(label("Текущий сеанс", "section"))
        note = label("После выхода камера отключится. Сохранённые в Supabase профили и настройки загрузятся при следующем входе.", "muted")
        note.setWordWrap(True)
        session.layout().addWidget(note)
        self.logout_button = QPushButton("Выйти из аккаунта")
        self.logout_button.setObjectName("danger")
        self.logout_button.setMinimumHeight(42)
        session.layout().addWidget(self.logout_button, alignment=Qt.AlignmentFlag.AlignLeft)
        # Реальный sign_out и смену окон выполняет MainWindow.
        self.logout_button.clicked.connect(self.logout_requested.emit)
        layout.addWidget(session)
        layout.addStretch()

    @staticmethod
    def _user_value(user, name):
        if isinstance(user, dict):
            return user.get(name)
        return getattr(user, name, None)

    @staticmethod
    def _format_date(value):
        if value is None:
            return "Не указана"
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y")
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d.%m.%Y")
        except ValueError:
            return "Не указана"
