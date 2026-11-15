"""Быстрая настройка действий с явным выбором профиля."""
from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget
from ui.action_settings_dialog import ActionSettingsDialog
from ui.widgets import clear_layout
from ui.widgets import card, label, page_header


class ActionsPage(QWidget):
    test_gesture_requested = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        page_header(layout, "Действия", "Один жест может выполнять разные команды в разных профилях.")
        self.profile_combo = QComboBox()
        layout.addWidget(self.profile_combo)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        layout.addLayout(self.body)
        layout.addStretch()
        self.profile_combo.currentIndexChanged.connect(self.render_actions)
        state.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        selected = self.profile_combo.currentData() or self.state.active_profile_id
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            for profile in self.state.profiles:
                self.profile_combo.addItem(profile["name"], profile["id"])
            index = self.profile_combo.findData(selected)
            self.profile_combo.setCurrentIndex(max(0, index))
        self.render_actions()

    def render_actions(self):
        clear_layout(self.body)
        pid = self.profile_combo.currentData()
        if pid is None:
            return
        for gesture in self.state.gestures:
            name = gesture["name"]
            frame = card()
            row = QHBoxLayout()
            content = QVBoxLayout()
            content.addWidget(label(name, "section"))
            content.addWidget(label(self.state.assignments[pid].get(name, "Нет действия"), "muted"))
            row.addLayout(content, 1)
            button = QPushButton("Настроить")
            button.clicked.connect(lambda checked=False, pid=pid, name=name: self.configure(pid, name))
            row.addWidget(button)
            frame.layout().addLayout(row)
            self.body.addWidget(frame)

    def configure(self, profile_id, name):
        dialog = ActionSettingsDialog(self.state, profile_id, name, self)
        dialog.test_requested.connect(self.test_gesture_requested)
        dialog.open()
