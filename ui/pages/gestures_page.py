"""Каталог стандартных поз и записанных пользователем жестов."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QMessageBox

from ui.widgets import card, label, message_label, page_header, primary_button, set_message


class GesturesPage(QWidget):
    wizard_opened = Signal()
    wizard_closed = Signal()

    def __init__(self, state=None, camera_service=None):
        super().__init__()
        self.state = state
        self.camera_service = camera_service
        self._wizard = None

        # ==========================================
        # СОЗДАНИЕ ИНТЕРФЕЙСА
        # ==========================================
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        page_header(layout, "Жесты", "Положения руки и движения. Действия назначаются в профилях.")
        heading = QHBoxLayout()
        heading.addWidget(label("Стандартные жесты", "section"))
        heading.addStretch()
        heading.addWidget(label("4 жеста", "badge"))
        layout.addLayout(heading)

        grid = QGridLayout()
        grid.setSpacing(14)
        gestures = (
            ("👍", "Большой палец вверх", "Большой палец поднят, остальные согнуты."),
            ("✊", "Кулак", "Все пальцы собраны в закрытую ладонь."),
            ("✌", "Два пальца", "Указательный и средний пальцы подняты."),
            ("✋", "Открытая ладонь", "Ладонь раскрыта, все пальцы выпрямлены."),
        )
        for index, (symbol, title, description) in enumerate(gestures):
            frame = card()
            top = QHBoxLayout()
            icon = label(symbol, "stat")
            icon.setStyleSheet("color: #7e9dff; font-family: 'Segoe UI Emoji'; font-size: 32px; background: transparent;")
            top.addWidget(icon)
            top.addStretch()
            top.addWidget(label(f"0{index + 1}", "muted"), alignment=Qt.AlignmentFlag.AlignTop)
            frame.layout().addLayout(top)
            title_label = label(title, "section")
            title_label.setWordWrap(True)
            frame.layout().addWidget(title_label)
            detail = label(description, "muted")
            detail.setWordWrap(True)
            frame.layout().addWidget(detail)
            grid.addWidget(frame, index // 2, index % 2)
        layout.addLayout(grid)
        layout.addWidget(label("Pinch — регулировка · динамический стандартный жест", "section"))
        layout.addWidget(label("Назначьте громкость или масштаб в профиле. Сомкните большой и указательный пальцы на 0,5 с, остальные раскройте. Уберите руку для выхода.", "muted"))

        custom = card()
        row = QHBoxLayout()
        custom_heading = label("Пользовательские жесты", "section")
        custom_heading.setWordWrap(False)
        row.addWidget(custom_heading)
        row.addStretch()
        self.custom_count = label("Пока нет", "badge")
        row.addWidget(self.custom_count)
        custom.layout().addLayout(row)
        description = label("Запишите пять вариантов позы или движения. Назначьте жесту действие в нужном профиле управления.", "muted")
        description.setWordWrap(True)
        custom.layout().addWidget(description)
        self.custom_list = QVBoxLayout()
        self.custom_list.setSpacing(12)
        custom.layout().addLayout(self.custom_list)
        self.add_button = primary_button("+ Добавить жест")
        custom.layout().addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status_message = message_label()
        self.status_message.hide()
        custom.layout().addWidget(self.status_message)
        self.add_button.clicked.connect(self._add_gesture)
        layout.addWidget(custom)
        layout.addStretch()
        if state is not None:
            state.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        while self.custom_list.count():
            item = self.custom_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        gestures = [item for item in getattr(self.state, "gestures", []) if item.get("is_custom")]
        self.custom_count.setText(str(len(gestures)) if gestures else "Пока нет")
        for gesture in gestures:
            row = QWidget()
            column = QVBoxLayout(row)
            column.setContentsMargins(0, 0, 0, 8)
            column.setSpacing(4)
            column.addWidget(label(gesture["name"], "section"))
            kind = "Динамическое движение" if gesture.get("gesture_data", {}).get("recognition_type") == "dynamic" else "Статическая поза"
            column.addWidget(label(kind + " · готово к назначению в профиле", "muted"))
            remove = QPushButton("Удалить жест полностью")
            remove.clicked.connect(lambda checked=False, name=gesture["name"]: self.delete_gesture(name))
            column.addWidget(remove)
            self.custom_list.addWidget(row)

    def delete_gesture(self, name):
        count = sum(mapping.get(name, "Нет действия") != "Нет действия" for mapping in self.state.assignments.values())
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Удалить жест полностью")
        dialog.setText(f'Удалить жест «{name}»?')
        dialog.setInformativeText(f"Жест используется в {count} профилях. При удалении будут удалены все его назначения.")
        cancel = dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        remove = dialog.addButton("Удалить", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() == remove
        dialog.deleteLater()
        if confirmed:
            try:
                self.state.delete_custom_gesture(name)
                set_message(self.status_message, "Сохраняем удаление…" if self.state.can_persist else "Жест удалён в текущем сеансе.", "badge")
            except ValueError as error:
                set_message(self.status_message, str(error))
            self.status_message.show()

    def _add_gesture(self):
        if self.state is None or self.camera_service is None:
            set_message(self.status_message, "Для записи жеста подключите камеру в приложении.")
            self.status_message.show()
            return
        if self._wizard is not None:
            self._wizard.raise_()
            return
        try:
            # Не предлагаем запись поверх неизвестных данных после ошибки загрузки.
            self.state._ensure_editable()
        except ValueError as error:
            set_message(self.status_message, str(error))
            self.status_message.show()
            return
        from ui.gesture_wizard import GestureWizard
        self._wizard = GestureWizard(self.state, self.camera_service, self.window())
        self._wizard.finished.connect(self._wizard_finished)
        # На время записи приостанавливаем выполнение назначенных действий.
        self.wizard_opened.emit()
        self._wizard.open()

    def _wizard_finished(self, result):
        wizard = self._wizard
        self._wizard = None
        if wizard is not None:
            wizard.deleteLater()
        self.wizard_closed.emit()
        if result:
            set_message(self.status_message, "✓ Жест сохранён. Теперь добавьте его в профиль управления.", "success")
            self.status_message.show()
