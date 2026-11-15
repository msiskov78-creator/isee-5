"""Обзор системы и быстрые переходы к основным разделам."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui.camera_preview import CameraPreview
from ui.widgets import card, label, message_label, page_header, primary_button, set_message


class HomePage(QWidget):
    navigate_requested = Signal(str)
    expand_requested = Signal()
    onboarding_requested = Signal()

    def __init__(self, username, state, camera_service=None, controller=None):
        super().__init__()
        self.state = state
        self.camera_service = camera_service
        self.controller = controller

        # ==========================================
        # СОЗДАНИЕ ИНТЕРФЕЙСА
        # ==========================================
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        page_header(layout, f"Добро пожаловать, {username}", "Ваше пространство для управления жестами.")

        overview = card()
        overview.layout().setSpacing(10)
        overview.layout().addWidget(label("СОСТОЯНИЕ СИСТЕМЫ", "muted"))
        self.system_value = label("Управление выключено", "section")
        overview.layout().addWidget(self.system_value)
        text = label("Выберите профиль и покажите жест перед камерой.", "subtitle")
        text.setWordWrap(True)
        overview.layout().addWidget(text)
        control_row = QHBoxLayout()
        self.control_button = primary_button("Включить управление")
        self.control_button.setMinimumWidth(225)
        control_row.addWidget(self.control_button)
        control_row.addStretch()
        self.connection_status = label("○  Ожидание камеры", "muted")
        control_row.addWidget(self.connection_status)
        overview.layout().addLayout(control_row)
        self.status_message = message_label()
        self.status_message.hide()
        overview.layout().addWidget(self.status_message)
        if controller is not None:
            self.control_button.clicked.connect(controller.toggle)
            controller.changed.connect(self._refresh)
            controller.status_changed.connect(self._runtime_status)
        layout.addWidget(overview)

        statistics = QGridLayout()
        statistics.setSpacing(14)
        self.profile_value = self._stat_card(statistics, 0, 0, "АКТИВНЫЙ ПРОФИЛЬ", state.active_profile_name, "Сценарий управления")
        self.gesture_value = self._stat_card(statistics, 0, 1, "ПОСЛЕДНИЙ ЖЕСТ", "—", "Распознавание в реальном времени")
        self.camera_value = self._stat_card(statistics, 0, 2, "КАМЕРА", "Не подключена", "Обработка на компьютере")
        for column in range(3):
            statistics.setColumnStretch(column, 1)
        layout.addLayout(statistics)

        camera_card = card()
        camera_row = QHBoxLayout()
        self.preview = CameraPreview(camera_service, self)
        self.preview.video.setFixedSize(280, 175)
        self.preview.setFixedWidth(280)
        camera_row.addWidget(self.preview)
        camera_info = QVBoxLayout()
        camera_info.addWidget(label("Камера и распознавание", "section"))
        camera_info.addWidget(label("Удерживайте одну позу, затем уберите руку или измените жест.", "muted"))
        self.action_value = label("Действие: —", "badge")
        camera_info.addWidget(self.action_value)
        expand = primary_button("Развернуть")
        expand.clicked.connect(self.expand_requested.emit)
        camera_info.addWidget(expand)
        setup = QPushButton("Настроить камеру и жесты")
        setup.clicked.connect(self.onboarding_requested.emit)
        camera_info.addWidget(setup)
        camera_info.addStretch()
        camera_row.addLayout(camera_info, 1)
        camera_card.layout().addLayout(camera_row)
        layout.addWidget(camera_card)
        if camera_service is not None:
            camera_service.status_changed.connect(self._camera_status)
            camera_service.error.connect(self._camera_error)
            camera_service.frame_ready.connect(self._frame_ready)
            camera_service.stopped.connect(self._camera_stopped)

        layout.addWidget(label("Быстрый доступ", "section"))
        shortcuts = QHBoxLayout()
        shortcuts.setSpacing(12)
        for title, destination in (("Мои жесты  →", "gestures"), ("Профили  →", "profiles"), ("Настройки  →", "settings")):
            button = QPushButton(title)
            button.setMinimumHeight(48)
            # Сигнал принимает MainWindow и переключает QStackedWidget.
            button.clicked.connect(lambda checked=False, name=destination: self.navigate_requested.emit(name))
            shortcuts.addWidget(button)
        layout.addLayout(shortcuts)
        layout.addStretch()
        self.state.changed.connect(self._refresh)

    def _stat_card(self, grid, row, column, title, value, description):
        frame = card()
        frame.layout().setSpacing(8)
        frame.layout().addWidget(label(title, "muted"))
        value_label = label(value, "stat")
        value_label.setWordWrap(True)
        frame.layout().addWidget(value_label)
        detail = label(description, "muted")
        detail.setWordWrap(True)
        frame.layout().addWidget(detail)
        grid.addWidget(frame, row, column)
        return value_label

    def _runtime_status(self, text):
        role = "badge" if self.controller.enabled else "muted"
        if text.startswith("Выполнено"):
            role = "success"
        set_message(self.status_message, text, role)
        self.status_message.show()

    def _camera_status(self, text):
        connected = "подключена" in text and "не подключена" not in text
        self.camera_value.setText("Подключена" if connected else text.removeprefix("Камера "))
        set_message(self.connection_status, "● " + text, "success" if connected else "muted")

    def _camera_error(self, text):
        self.camera_value.setText("Ошибка")
        set_message(self.connection_status, "● Ошибка камеры", "error")
        set_message(self.status_message, text, "error")
        self.status_message.show()

    def _camera_stopped(self):
        self._camera_status("Камера не подключена")

    def _frame_ready(self, packet):
        if self.camera_value.text() != "Подключена":
            self._camera_status("Камера подключена")

    def _refresh(self):
        self.profile_value.setText(self.state.active_profile_name)
        if self.controller is not None:
            enabled = self.controller.enabled
            self.system_value.setText("● Управление включено" if enabled else "○ Управление выключено")
            self.control_button.setText("Приостановить управление" if enabled else "Включить управление")
            self.gesture_value.setText(self.controller.last_gesture)
            self.action_value.setText(self.controller.last_action if self.controller.last_action != "—" else "Действие: —")
