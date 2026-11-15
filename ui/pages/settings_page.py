"""Постоянные настройки камеры и распознавания, общие для всех профилей."""
import logging
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QPushButton, QSlider, QVBoxLayout, QWidget
from ui.camera_preview import CameraPreview
from sensitivity import sensitivity_from_percent, sensitivity_to_percent
from ui.widgets import card, label, message_label, page_header, primary_button, set_message


class SettingsPage(QWidget):
    def __init__(self, state, camera_service=None):
        super().__init__()
        self.state, self.camera_service = state, camera_service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        page_header(layout, "Настройки", "Подготовьте управление под свой темп.")
        camera = card()
        camera.layout().addWidget(label("Источник видео", "section"))
        row = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(140)
        self.camera_combo.addItem("Камера 0", 0)
        row.addWidget(self.camera_combo, 1)
        self.scan_button = QPushButton("Найти камеры")
        self.scan_button.clicked.connect(self.scan)
        row.addWidget(self.scan_button)
        test = QPushButton("Проверить камеру")
        test.clicked.connect(self.check_camera)
        row.addWidget(test)
        camera.layout().addLayout(row)
        self.preview = CameraPreview(camera_service, self)
        self.preview.video.setFixedSize(280, 175)
        self.preview.setFixedWidth(280)
        camera.layout().addWidget(self.preview)
        self.mirror_check = QCheckBox("Зеркальное отображение")
        self.landmarks_check = QCheckBox("Показывать landmarks и кончики пальцев")
        self.auto_start_check = QCheckBox("Автоматически запускать управление после входа")
        for checkbox in (self.mirror_check, self.landmarks_check, self.auto_start_check):
            camera.layout().addWidget(checkbox)
        layout.addWidget(camera)
        recognition = card()
        recognition.layout().addWidget(label("Распознавание жестов", "section"))
        self.sensitivity_value = label("70%", "badge")
        recognition.layout().addWidget(self.sensitivity_value)
        self.sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity_slider.setRange(0, 100)
        self.sensitivity_slider.valueChanged.connect(lambda value: self.sensitivity_value.setText(f"Чувствительность: {value}%"))
        recognition.layout().addWidget(self.sensitivity_slider)
        recognition.layout().addWidget(label("Минимальная уверенность для команды: выше — строже. Рекомендуется 70%.", "muted"))
        form = QFormLayout()
        self.hold_spin = self.time_input()
        self.pause_spin = self.time_input()
        form.addRow("Время удержания жеста", self.hold_spin)
        form.addRow("Cooldown между командами", self.pause_spin)
        recognition.layout().addLayout(form)
        layout.addWidget(recognition)
        self.save_button = primary_button("Сохранить настройки")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.status_message = message_label()
        layout.addWidget(self.status_message)
        layout.addStretch()
        state.loaded.connect(self.refresh)
        state.persistence_status.connect(self.persistence_status)
        if camera_service is not None:
            camera_service.cameras_found.connect(self.cameras_found)
            camera_service.error.connect(self.camera_error)
        self.refresh()
        for widget, key in ((self.mirror_check, "mirror"), (self.landmarks_check, "show_landmarks"), (self.auto_start_check, "auto_start")):
            widget.toggled.connect(lambda checked, key=key: self.apply_toggle(key, checked))

    def apply_toggle(self, key, checked):
        try:
            # Мгновенно применяем настройку через общий state; сеть работает в очереди.
            self.state.save_settings(**{key: checked})
            if self.camera_service is not None:
                self.camera_service.configure(self.state.settings, [g for g in self.state.gestures if g.get("is_custom")])
            column = {"mirror": "mirror_camera", "auto_start": "auto_start_recognition"}.get(key, key)
            logging.getLogger("Settings").info("%s = %s", column, checked)
        except ValueError as error:
            self.refresh()
            set_message(self.status_message, str(error))

    @staticmethod
    def time_input():
        spin = QDoubleSpinBox()
        spin.setRange(0., 3.4e38)
        spin.setMaximumWidth(190)
        spin.setSingleStep(.1)
        spin.setDecimals(1)
        spin.setSuffix(" с")
        return spin

    def refresh(self):
        settings = self.state.settings
        index = self.camera_combo.findData(settings["camera"])
        if index < 0:
            self.camera_combo.addItem(f"Камера {settings['camera']}", settings["camera"])
            index = self.camera_combo.findData(settings["camera"])
        self.camera_combo.setCurrentIndex(index)
        self.sensitivity_slider.setValue(sensitivity_to_percent(settings["sensitivity"]))
        self.hold_spin.setValue(settings["hold_time"])
        self.pause_spin.setValue(settings["command_pause"])
        for widget, key in ((self.mirror_check, "mirror"), (self.landmarks_check, "show_landmarks"), (self.auto_start_check, "auto_start")):
            # Загрузка значений не должна запускать повторное сохранение.
            with QSignalBlocker(widget):
                widget.setChecked(settings[key])

    def showEvent(self, event):
        # Мастер мог изменить выбранную камеру, пока страница была скрыта.
        self.refresh()
        super().showEvent(event)

    def scan(self):
        if self.camera_service:
            self.scan_button.setEnabled(False)
            self.camera_service.scan_cameras()

    def cameras_found(self, cameras):
        self.scan_button.setEnabled(True)
        selected = self.camera_combo.currentData()
        self.camera_combo.clear()
        for camera in cameras:
            self.camera_combo.addItem(camera["name"], camera["index"])
        if self.camera_combo.findData(selected) < 0:
            self.camera_combo.addItem(f"Камера {selected}", selected)
        self.camera_combo.setCurrentIndex(self.camera_combo.findData(selected))
        set_message(self.status_message, "Камеры найдены" if cameras else "Камера не найдена", "success" if cameras else "error")

    def camera_error(self, text):
        self.scan_button.setEnabled(True)
        set_message(self.status_message, text)

    def check_camera(self):
        if self.camera_service:
            self.camera_service.start(self.camera_combo.currentData())

    def save(self):
        try:
            self.state.save_settings(camera=self.camera_combo.currentData(), sensitivity=sensitivity_from_percent(self.sensitivity_slider.value()),
                hold_time=self.hold_spin.value(), command_pause=self.pause_spin.value(),
                mirror=self.mirror_check.isChecked(), show_landmarks=self.landmarks_check.isChecked(),
                auto_start=self.auto_start_check.isChecked())
        except ValueError as error:
            set_message(self.status_message, str(error))
            return
        set_message(self.status_message, "Сохраняем настройки…" if self.state.can_persist else "Настройки текущего сеанса изменены.", "badge")

    def persistence_status(self, text, success):
        set_message(self.status_message, text, "success" if success else "error")
