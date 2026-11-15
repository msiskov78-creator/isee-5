"""Первичная проверка камеры и четырёх статических жестов одной руки."""

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout

from gesture_control.gesture_recorder import feature_distance, normalize_landmarks
from ui.camera_preview import CameraPreview
from ui.theme import APP_STYLE
from ui.widgets import label, message_label, primary_button, set_message


class OnboardingWizard(QDialog):
    GESTURES = (
        ("thumbs_up", "👍 Большой палец вверх"),
        ("fist", "✊ Кулак"),
        ("two_fingers", "✌ Два пальца"),
        ("open_palm", "✋ Открытая ладонь"),
    )

    def __init__(self, state, camera_service, parent=None):
        super().__init__(parent)
        self.state = state
        self.camera_service = camera_service
        self.step = 0
        self._checking_camera = False
        self._camera_checked = False
        self._hand_checked = False
        self._gesture_index = 0
        self._stable_since = None
        self._last_features = None
        self._last_frame_time = None
        self._save_revision = None
        self._save_failed = False
        self._connections = []
        self.setWindowTitle("Gesture Control — первая настройка")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(850, 760)
        self.setMinimumSize(660, 650)
        self.setStyleSheet(APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.steps_label = label("", "badge")
        layout.addWidget(self.steps_label)
        self.title = label("", "title")
        layout.addWidget(self.title)
        self.description = label("", "muted")
        layout.addWidget(self.description)

        self.camera_row = QHBoxLayout()
        self.camera_combo = QComboBox()
        camera = int(state.settings.get("camera", 0))
        self.camera_combo.addItem(f"Камера {camera}", camera)
        self.camera_combo.currentIndexChanged.connect(self._camera_changed)
        self.camera_row.addWidget(self.camera_combo, 1)
        self.scan_button = QPushButton("Найти камеры")
        self.scan_button.clicked.connect(self._scan_cameras)
        self.camera_row.addWidget(self.scan_button)
        self.check_button = QPushButton("Проверить")
        self.check_button.clicked.connect(self._check_camera)
        self.camera_row.addWidget(self.check_button)
        layout.addLayout(self.camera_row)

        # Мини-превью и мастер подписаны на один сервис, нового подключения нет.
        self.preview = CameraPreview(camera_service, self)
        self.preview.setMinimumHeight(300)
        layout.addWidget(self.preview, 1)
        self.hint_label = message_label()
        layout.addWidget(self.hint_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.result_label = message_label()
        layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        self.later_button = QPushButton("Настроить позже")
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)
        buttons.addStretch()
        self.next_button = primary_button("Далее →")
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self._connect(camera_service.frame_ready, self._on_frame)
        self._connect(camera_service.cameras_found, self._cameras_found)
        self._connect(camera_service.error, self._camera_error)
        self._connect(state.save_completed, self._saved)
        self._connect(state.save_failed, self._saving_failed)
        self.finished.connect(self._disconnect)
        self._render_step()

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def _disconnect(self, *_):
        self.preview.detach()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()

    def _camera_changed(self, *_):
        self._camera_checked = False
        self._checking_camera = False
        self.next_button.setEnabled(False)

    def _scan_cameras(self):
        set_message(self.hint_label, "Ищем доступные камеры…", "badge")
        self.scan_button.setEnabled(False)
        self.camera_service.scan_cameras()

    def _cameras_found(self, cameras):
        self.scan_button.setEnabled(True)
        selected = self.camera_combo.currentData()
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for camera in cameras:
            self.camera_combo.addItem(camera.get("name", f"Камера {camera['index']}"), camera["index"])
        if self.camera_combo.findData(selected) < 0:
            self.camera_combo.addItem(f"Камера {selected}", selected)
        self.camera_combo.setCurrentIndex(self.camera_combo.findData(selected))
        self.camera_combo.blockSignals(False)
        if not cameras:
            set_message(self.hint_label, "Камера не найдена. Подключите её и повторите поиск.")
        else:
            set_message(self.hint_label, "Выберите камеру и нажмите «Проверить».", "muted")

    def _check_camera(self):
        self._checking_camera = True
        self._camera_checked = False
        self.next_button.setEnabled(False)
        set_message(self.hint_label, "Подключаем камеру…", "badge")
        self.camera_service.start(self.camera_combo.currentData())

    def _camera_error(self, message):
        self.scan_button.setEnabled(True)
        self._camera_checked = False
        self._checking_camera = False
        self._stable_since = None
        self._hand_checked = False
        if self.step < 3:
            self.next_button.setEnabled(False)
        set_message(self.hint_label, message)

    def _render_step(self):
        names = ["АККАУНТ ✓", "КАМЕРА", "СКАНИРОВАНИЕ РУКИ", "ОСНОВНЫЕ ЖЕСТЫ", "ГОТОВО"]
        self.steps_label.setText("  →  ".join(names))
        for index in range(self.camera_row.count()):
            self.camera_row.itemAt(index).widget().setVisible(self.step == 0)
        self.check_button.setVisible(self.step < 3)
        self.preview.setVisible(self.step < 3)
        self.progress.setVisible(self.step in (1, 2))
        self.progress.setValue(0)
        set_message(self.result_label, "", "muted")
        if self.step == 0:
            self.title.setText("Подключение камеры")
            self.description.setText("Проверьте изображение. Все кадры и точки руки обрабатываются на вашем компьютере.")
            self.next_button.setEnabled(self._camera_checked)
            set_message(self.hint_label, "Выберите камеру и нажмите «Проверить».", "muted")
        elif self.step == 1:
            self.title.setText("Покажите руку")
            self.description.setText("Поместите одну кисть целиком в кадр и ненадолго задержите её.")
            self.next_button.setEnabled(False)
        elif self.step == 2:
            self.title.setText("Проверим основные жесты")
            self.description.setText("По очереди покажите четыре позы. Удерживайте каждую около секунды.")
            self.next_button.setEnabled(False)
            self._render_gesture()
        else:
            self.title.setText("Настройка завершена")
            self.description.setText("Камера подключена, рука обнаружена и все четыре жеста проверены.")
            set_message(self.hint_label, "✓ Всё готово для управления", "success")
            self.next_button.setText("Начать работу")
            self.next_button.setEnabled(True)

    def _render_gesture(self):
        if self._gesture_index < len(self.GESTURES):
            set_message(self.hint_label, f"{self._gesture_index + 1} / 4   {self.GESTURES[self._gesture_index][1]}", "badge")

    def _on_frame(self, payload):
        if self.step == 0:
            if self._checking_camera and payload.get("camera_index", self.camera_combo.currentData()) == self.camera_combo.currentData():
                self._camera_checked = True
                self.next_button.setEnabled(True)
                set_message(self.hint_label, "● Камера подключена", "success")
            return
        if self.step not in (1, 2):
            return
        hand = payload.get("hand", {})
        now = float(payload.get("timestamp", time.monotonic()))
        # Разрыв потока не считается временем непрерывного удержания.
        if self._last_frame_time is not None and now - self._last_frame_time > 0.3:
            self._stable_since = None
        self._last_frame_time = now
        if not hand.get("ready") or hand.get("count", 1) != 1:
            self._stable_since = None
            self._last_features = None
            self.progress.setValue(0)
            target = self.hint_label if self.step == 1 else self.result_label
            set_message(target, hand.get("hint", "Рука не обнаружена"), "muted")
            return
        if self.step == 1:
            features = normalize_landmarks(hand["landmarks"])
            if self._last_features is not None and feature_distance(features, self._last_features) > 0.08:
                self._stable_since = None
            self._last_features = features
            if self._stable_since is None:
                self._stable_since = now
            self.progress.setValue(min(100, int((now - self._stable_since) / 0.8 * 100)))
            if now - self._stable_since >= 0.8:
                self._hand_checked = True
                self.next_button.setEnabled(True)
                set_message(self.hint_label, "✓ Отлично, рука обнаружена", "success")
            elif not self._hand_checked:
                set_message(self.hint_label, "Держите руку неподвижно", "badge")
        elif self._gesture_index < len(self.GESTURES):
            self._render_gesture()
            gesture = payload.get("gesture", {})
            expected = self.GESTURES[self._gesture_index][0]
            if gesture.get("key") != expected or gesture.get("confidence", 0) < 0.7:
                self._stable_since = None
                self.progress.setValue(0)
                set_message(self.result_label, "Покажите указанный жест и удерживайте его.", "muted")
                return
            if self._stable_since is None:
                self._stable_since = now
            duration = now - self._stable_since
            self.progress.setValue(min(100, int(duration / 0.65 * 100)))
            set_message(self.result_label, f"Удерживайте жест… Уверенность: {gesture['confidence']:.0%}", "badge")
            if duration >= 0.65:
                self._gesture_index += 1
                self._stable_since = None
                set_message(self.result_label, "✓ Жест распознан", "success")
                self._render_gesture()
                if self._gesture_index == len(self.GESTURES):
                    self.hint_label.setText("✓ Все четыре жеста распознаны")
                    self.next_button.setEnabled(True)

    def _next(self):
        if self.step == 0 and not self._camera_checked:
            return
        if self.step == 1 and not self._hand_checked:
            return
        if self.step == 2 and self._gesture_index != len(self.GESTURES):
            return
        if self.step == 3:
            self._save()
            return
        self.step += 1
        self._stable_since = None
        self._last_frame_time = None
        self._render_step()

    def _save(self):
        if self._save_revision is not None:
            return
        try:
            if self._save_failed:
                self.state.flush_async()
            else:
                self.state.save_settings(camera=self.camera_combo.currentData(), onboarding_completed=True)
            self._save_revision = self.state.revision
        except ValueError as error:
            set_message(self.result_label, str(error))
            return
        self.next_button.setEnabled(False)
        self.later_button.setEnabled(False)
        set_message(self.result_label, "Сохраняем настройку…", "badge")

    def _saved(self, revision):
        if self._save_revision is not None and revision >= self._save_revision:
            self.accept()

    def _saving_failed(self, revision, message):
        if self._save_revision is not None and revision >= self._save_revision:
            self._save_revision = None
            self._save_failed = True
            self.next_button.setEnabled(True)
            self.later_button.setEnabled(True)
            set_message(self.result_label, message)

    def reject(self):
        # Не закрываем мастер клавишей Esc, пока результат сохранения неизвестен.
        if self._save_revision is not None and not getattr(self.parent(), "_shutdown_kind", None):
            set_message(self.result_label, "Дождитесь завершения сохранения…", "badge")
            return
        super().reject()
