"""Одно назначение относится только к выбранной паре профиль–жест."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QFileDialog, QMessageBox, QScrollArea, QWidget
from actions.action_types import ACTION_KEYS, VALUE_ACTIONS, is_dangerous, normalize_action_value
from actions.action_settings import execution_mode, ExecutionMode
from ui.action_picker import ActionPicker
from sensitivity import sensitivity_from_percent, sensitivity_to_percent
from ui.widgets import label, message_label, primary_button, set_message


class ActionSettingsDialog(QDialog):
    test_requested = Signal(str)

    def __init__(self, state, profile_id, gesture, parent=None):
        super().__init__(parent)
        self.state, self.profile_id, self.gesture = state, profile_id, gesture
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Настройки жеста в профиле")
        self.resize(600, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        layout.setSpacing(16)
        layout.addWidget(label(gesture, "title"))
        layout.addWidget(label("Профиль: " + state._get_profile(profile_id)["name"], "muted"))
        self.action = ActionPicker()
        self.action.setCurrentText(state.assignments[profile_id].get(gesture, "Нет действия"))
        layout.addWidget(label("Действие"))
        layout.addWidget(self.action)
        effective = state.get_action_settings(profile_id, gesture)
        raw = state.action_settings.get(profile_id, {}).get(gesture, {})
        self.hotkey_input = QLineEdit(raw.get("action_value") or "")
        self.hotkey_input.setMaxLength(2048)
        self.hotkey_input.setPlaceholderText("Например, Ctrl+Shift+P")
        self.hotkey_input.setAccessibleName("Комбинация клавиш")
        self.value_label = label("Параметр действия")
        layout.addWidget(self.value_label)
        layout.addWidget(self.hotkey_input)
        self.browse_button = QPushButton("Выбрать файл")
        self.browse_button.clicked.connect(self.browse)
        layout.addWidget(self.browse_button)
        self.warning = label("⚠ Это системное действие. Только однократное выполнение. Время удержания выбираете вы.", "error")
        layout.addWidget(self.warning)
        self.hotkey_input.textChanged.connect(lambda: self._action_changed(self.action.currentText()))
        self.action.currentTextChanged.connect(self._action_changed)
        self.enabled = QCheckBox("Жест включён")
        self.enabled.setChecked(effective["enabled"])
        layout.addWidget(self.enabled)
        self.inputs, self.inherit = {}, {}
        form = QFormLayout()
        for key, title, maximum in (("hold_time", "Удержание", 3), ("cooldown", "Cooldown", 5), ("sensitivity", "Чувствительность", 100)):
            row = QHBoxLayout()
            if key == "sensitivity":
                spin = QSlider(Qt.Orientation.Horizontal)
                spin.setRange(0, 100)
                spin.setValue(sensitivity_to_percent(effective[key]))
                percentage = label(f"{spin.value()}%", "badge")
                spin.valueChanged.connect(lambda value, text=percentage: text.setText(f"{value}%"))
                row.addWidget(percentage)
            else:
                spin = QDoubleSpinBox()
                spin.setDecimals(1)
                spin.setRange(0., 3.4e38)
                spin.setMaximumWidth(190)
                spin.setSingleStep(.1)
                spin.setSuffix(" с")
                spin.setValue(effective[key])
            inherit = QCheckBox("Общая настройка")
            inherit.setChecked(raw.get(key) is None)
            spin.setEnabled(not inherit.isChecked())
            inherit.toggled.connect(lambda checked, widget=spin: widget.setEnabled(not checked))
            row.addWidget(spin)
            row.addWidget(inherit)
            form.addRow(title, row)
            self.inputs[key], self.inherit[key] = spin, inherit
        layout.addLayout(form)
        self.repeat = QCheckBox("Повторять действие при удержании")
        self.repeat.setChecked(effective["repeat_while_held"])
        layout.addWidget(self.repeat)
        self.extra_form = QFormLayout()
        self.repeat_interval = QDoubleSpinBox()
        self.repeat_interval.setRange(0., 3.4e38)
        self.repeat_interval.setMaximumWidth(190)
        self.repeat_interval.setDecimals(2)
        self.repeat_interval.setSingleStep(.05)
        self.repeat_interval.setSuffix(" с")
        self.repeat_interval.setValue(effective["repeat_interval"])
        self.volume_step = QSpinBox()
        self.volume_step.setRange(1, 25)
        self.volume_step.setSuffix(" %")
        self.volume_step.setValue(effective["volume_step"])
        self.extra_form.addRow("Интервал повтора", self.repeat_interval)
        self.extra_form.addRow("Изменение громкости за действие", self.volume_step)
        self.scroll_step = QSpinBox()
        self.scroll_step.setRange(1, 10)
        self.scroll_step.setValue(effective["scroll_step"])
        self.extra_form.addRow("Шаг прокрутки", self.scroll_step)
        self.pinch_inputs = {}
        for key, title, low, high in (("pinch_smoothing", "Коэффициент сглаживания pinch", .05, 1.),
                                      ("pinch_min", "Минимальное расстояние pinch", .05, 2.),
                                      ("pinch_max", "Максимальное расстояние pinch", .1, 3.)):
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(2)
            spin.setSingleStep(.05)
            spin.setValue(effective[key])
            self.pinch_inputs[key] = spin
            self.extra_form.addRow(title, spin)
        layout.addLayout(self.extra_form)
        self.repeat.toggled.connect(lambda: self._action_changed(self.action.currentText()))
        self._action_changed(self.action.currentText())
        layout.addWidget(label("Первое действие — после удержания. При повторе используется его интервал, а Cooldown — после отпускания перед новым циклом. Непрерывная регулировка pinch работает отдельно.", "muted"))
        self.message = message_label()
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        test = QPushButton("Проверить жест")
        test.clicked.connect(lambda: self.test_requested.emit(gesture))
        buttons.addWidget(test)
        self.save_button = primary_button("Сохранить")
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.save_button)
        outer.addLayout(buttons)
        self._revision = None
        state.save_completed.connect(self.saved)
        state.save_failed.connect(self.failed)
        self.finished.connect(self._disconnect)
        self._closed = False

    def _disconnect(self, *_):
        if self._closed:
            return
        self._closed = True
        self._revision = None
        # Завершение отложенного сохранения не должно повторно закрывать уничтожаемый диалог.
        self.state.save_completed.disconnect(self.saved)
        self.state.save_failed.disconnect(self.failed)
        self.hotkey_input.textChanged.disconnect()
        self.action.currentTextChanged.disconnect()
        self.repeat.toggled.disconnect()

    def _action_changed(self, action):
        key = ACTION_KEYS.get(action)
        self.hotkey_input.setVisible(key in VALUE_ACTIONS)
        self.value_label.setVisible(key in VALUE_ACTIONS)
        titles = {"hotkey": "Комбинация клавиш, например Ctrl+Shift+S", "open_application": "Программа (.exe)",
                  "open_file": "Файл", "open_folder": "Папка", "open_url": "URL (https://…)",
                  "set_volume": "Громкость 0–100% (пусто — прежний режим pinch)", "set_brightness": "Яркость 0–100%"}
        self.value_label.setText(titles.get(key, "Параметр действия"))
        self.hotkey_input.setPlaceholderText(titles.get(key, ""))
        self.browse_button.setVisible(key in ("open_application", "open_file", "open_folder"))
        self.browse_button.setText("Выбрать папку" if key == "open_folder" else "Выбрать файл")
        if not hasattr(self, "extra_form"):
            return
        continuous = execution_mode(action, {"action_value": self.hotkey_input.text().strip()}) == ExecutionMode.CONTINUOUS
        dangerous = is_dangerous(action, self.hotkey_input.text())
        self.warning.setVisible(dangerous)
        self.repeat.setEnabled(not continuous and not dangerous)
        if dangerous:
            self.repeat.setChecked(False)
        self.inputs["hold_time"].setMinimum(0.)
        self.inherit["hold_time"].setEnabled(True)
        self.extra_form.setRowVisible(self.repeat_interval, self.repeat.isChecked() and not continuous)
        self.extra_form.setRowVisible(self.volume_step, ACTION_KEYS.get(action) in ("volume_up", "volume_down"))
        self.extra_form.setRowVisible(self.scroll_step, key in ("scroll_up", "scroll_down", "scroll_left", "scroll_right"))
        for spin in self.pinch_inputs.values():
            self.extra_form.setRowVisible(spin, continuous)

    def browse(self):
        key = ACTION_KEYS.get(self.action.currentText())
        if key == "open_folder":
            path = QFileDialog.getExistingDirectory(self, "Выбрать папку")
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", "", "Программы (*.exe)" if key == "open_application" else "Все файлы (*)")
        if path:
            self.hotkey_input.setText(path)

    def confirm_dangerous(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Опасное действие")
        dialog.setText("Это действие может завершить работу компьютера или закрыть активное приложение. Вы действительно хотите назначить его жесту?")
        cancel = dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        assign = dialog.addButton("Назначить", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() == assign
        dialog.deleteLater()
        return confirmed

    def save(self):
        values = {key: None if self.inherit[key].isChecked() else widget.value() for key, widget in self.inputs.items()}
        if values["sensitivity"] is not None:
            values["sensitivity"] = sensitivity_from_percent(values["sensitivity"])
        try:
            normalize_action_value(self.action.currentText(), self.hotkey_input.text())
            dangerous = is_dangerous(self.action.currentText(), self.hotkey_input.text())
            if dangerous and not self.confirm_dangerous():
                return
            self.state.set_action_settings(self.profile_id, self.gesture, action=self.action.currentText(),
                enabled=self.enabled.isChecked(), action_value=self.hotkey_input.text(),
                repeat_while_held=self.repeat.isChecked() and self.repeat.isEnabled(),
                repeat_interval=self.repeat_interval.value(), volume_step=self.volume_step.value(),
                scroll_step=self.scroll_step.value(), dangerous_confirmed=dangerous,
                **{key: spin.value() for key, spin in self.pinch_inputs.items()}, **values)
            self._revision = self.state.revision
        except ValueError as error:
            set_message(self.message, str(error))
            return
        self.save_button.setEnabled(False)
        set_message(self.message, "Сохраняем назначение…", "badge")

    def saved(self, revision):
        if self._revision is not None and revision >= self._revision:
            self.accept()

    def failed(self, revision, message):
        if self._revision is not None and revision >= self._revision:
            self._revision = None
            self.save_button.setEnabled(True)
            set_message(self.message, message)
