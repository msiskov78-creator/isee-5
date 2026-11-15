"""Профили управления и отдельные назначения жестов внутри каждого профиля."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog, QLineEdit, QPushButton, QVBoxLayout, QWidget, QMessageBox
from ui.action_settings_dialog import ActionSettingsDialog
from sensitivity import sensitivity_to_percent
from ui.widgets import card, label, message_label, page_header, primary_button, set_message, clear_layout


class ProfilesPage(QWidget):
    test_gesture_requested = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.selected_profile_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        page_header(layout, "Профили управления", "Свои действия и темп управления для каждого сценария.")
        self.status_message = message_label()
        layout.addWidget(self.status_message)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        layout.addLayout(self.body)
        layout.addStretch()
        state.changed.connect(self.refresh)
        state.persistence_status.connect(self.persistence_status)
        self.refresh()

    def persistence_status(self, text, success):
        set_message(self.status_message, text, "success" if success else "error")

    def perform(self, operation):
        try:
            operation()
            set_message(self.status_message, "Сохраняем изменения…" if self.state.can_persist else "Изменения в текущем сеансе.", "badge")
        except ValueError as error:
            set_message(self.status_message, str(error))

    def refresh(self):
        if self.selected_profile_id not in {p["id"] for p in self.state.profiles}:
            self.selected_profile_id = None
        clear_layout(self.body)
        if self.selected_profile_id:
            self.render_detail()
        else:
            self.render_list()

    def render_list(self):
        for profile in self.state.profiles:
            pid = profile["id"]
            frame = card()
            row = QHBoxLayout()
            row.addWidget(label(profile["name"], "section"), 1)
            active = pid == self.state.active_profile_id
            row.addWidget(label("● Активный" if active else "○ Неактивный", "success" if active else "muted"))
            frame.layout().addLayout(row)
            if profile.get("description"):
                frame.layout().addWidget(label(profile["description"], "muted"))
            count = sum(action != "Нет действия" and self.state.get_action_settings(pid, gesture)["enabled"] for gesture, action in self.state.assignments[pid].items())
            frame.layout().addWidget(label(f"Жестов настроено: {count}", "muted"))
            buttons = QHBoxLayout()
            for title, callback in (
                ("Открыть", lambda checked=False, key=pid: self.open_profile(key)),
                ("Сделать активным", lambda checked=False, key=pid: self.perform(lambda: self.state.set_active_profile(key))),
                ("Дублировать", lambda checked=False, key=pid: self.perform(lambda: self.state.duplicate_profile(key))),
            ):
                button = QPushButton(title)
                button.clicked.connect(callback)
                button.setEnabled(not (title == "Сделать активным" and active))
                buttons.addWidget(button)
            frame.layout().addLayout(buttons)
            self.body.addWidget(frame)
        create = card()
        create.layout().addWidget(label("Новый профиль", "section"))
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(32)
        self.name_input.setPlaceholderText("Название, например Игры")
        self.description_input = QLineEdit()
        self.description_input.setMaxLength(250)
        self.description_input.setPlaceholderText("Описание профиля")
        create.layout().addWidget(self.name_input)
        create.layout().addWidget(self.description_input)
        button = primary_button("+ Создать профиль")
        button.clicked.connect(self.create_profile)
        create.layout().addWidget(button)
        self.body.addWidget(create)

    def create_profile(self):
        name, description = self.name_input.text(), self.description_input.text()
        self.perform(lambda: self.state.add_profile(name, description))

    def open_profile(self, profile_id):
        self.selected_profile_id = profile_id
        self.refresh()

    def render_detail(self):
        pid = self.selected_profile_id
        profile = self.state._get_profile(pid)
        top = QHBoxLayout()
        back = QPushButton("← Назад")
        back.clicked.connect(lambda: self.open_profile(None))
        top.addWidget(back)
        top.addWidget(label(profile["name"], "section"), 1)
        active = pid == self.state.active_profile_id
        top.addWidget(label("● Активный профиль" if active else "Неактивный профиль", "success" if active else "muted"))
        self.body.addLayout(top)
        manage = QHBoxLayout()
        for title, callback in (
            ("Переименовать", self.rename_profile),
            ("Сделать активным", lambda: self.perform(lambda: self.state.set_active_profile(pid))),
            ("Дублировать", lambda: self.perform(lambda: self.state.duplicate_profile(pid))),
            ("Удалить", lambda: self.perform(lambda: self.state.delete_profile(pid))),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            manage.addWidget(button)
        self.body.addLayout(manage)
        for gesture in self.state.gestures:
            name = gesture["name"]
            action = self.state.assignments[pid].get(name, "Нет действия")
            if action == "Нет действия" and name not in self.state.action_settings[pid]:
                continue
            effective = self.state.get_action_settings(pid, name)
            frame = card()
            row = QHBoxLayout()
            content = QVBoxLayout()
            content.addWidget(label(name, "section"))
            content.addWidget(label(action))
            enabled = "Включён" if effective["enabled"] else "Выключен"
            content.addWidget(label(f"Удержание {effective['hold_time']:.1f} с · Cooldown {effective['cooldown']:.1f} с · {sensitivity_to_percent(effective['sensitivity'])}% · {enabled}", "muted"))
            row.addLayout(content, 1)
            configure = QPushButton("Настроить")
            configure.clicked.connect(lambda checked=False, name=name: self.configure_gesture(name))
            row.addWidget(configure)
            remove = QPushButton("Удалить из профиля")
            remove.clicked.connect(lambda checked=False, name=name, pid=pid: self.remove_assignment(pid, name))
            row.addWidget(remove)
            frame.layout().addLayout(row)
            self.body.addWidget(frame)
        add_row = QHBoxLayout()
        self.gesture_combo = QComboBox()
        self.gesture_combo.addItems([g["name"] for g in self.state.gestures])
        add_row.addWidget(self.gesture_combo, 1)
        add = primary_button("+ Добавить жест")
        add.clicked.connect(lambda: self.configure_gesture(self.gesture_combo.currentText()))
        add_row.addWidget(add)
        self.body.addLayout(add_row)

    def rename_profile(self):
        pid = self.selected_profile_id
        name, accepted = QInputDialog.getText(self, "Переименовать профиль", "Название:", text=self.state._get_profile(pid)["name"])
        if accepted:
            self.perform(lambda: self.state.rename_profile(pid, name))

    def remove_assignment(self, pid, name):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Удалить из профиля")
        dialog.setText(f'Удалить жест «{name}» из профиля «{self.state._get_profile(pid)["name"]}»?')
        dialog.setInformativeText("Сам жест не будет удалён из вашей библиотеки.")
        cancel = dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        remove = dialog.addButton("Удалить", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() == remove
        dialog.deleteLater()
        if confirmed:
            self.perform(lambda: self.state.remove_gesture_from_profile(pid, name))

    def configure_gesture(self, gesture):
        dialog = ActionSettingsDialog(self.state, self.selected_profile_id, gesture, self)
        dialog.test_requested.connect(self.test_gesture_requested)
        dialog.open()
