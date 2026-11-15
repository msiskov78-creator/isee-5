"""Выбор режима, запись пяти примеров позы или движения и отдельная проверка."""

import time
import logging
from diagnostics import log_error

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget

from gesture_control.gesture_detector import GestureDetector
from gesture_control.gesture_recorder import MultiStaticRecorder
from gesture_control.dynamic_gesture_recorder import DynamicGestureRecorder
from gesture_control.dynamic_gesture_detector import DynamicGestureDetector
from ui.camera_preview import CameraPreview
from ui.theme import APP_STYLE
from ui.widgets import label, message_label, primary_button, set_message


class GestureWizard(QDialog):
    def __init__(self, state, camera_service, parent=None):
        super().__init__(parent)
        self.state = state
        self.camera_service = camera_service
        self.recorder = MultiStaticRecorder()
        self.recognition_type = "static"
        self.step = -1
        self.recorded_data = None
        self._verification_detector = None
        self._verify_released = False
        self._verified = False
        self._stable_since = None
        self._last_frame_time = None
        self._verification_frames = 0
        self._gesture_id = None
        self._save_revision = None
        self._connections = []
        self._dynamic_hand_state = None
        self._received_dynamic_frame = False
        self.setWindowTitle("Gesture Control — добавить жест")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(850, 730)
        self.setMinimumSize(640, 620)
        self.setStyleSheet(APP_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        self.steps_label = label("НАЗВАНИЕ  →  ЗАПИСЬ  →  ПРОВЕРКА", "badge")
        layout.addWidget(self.steps_label)
        self.title = label("Название жеста", "title")
        layout.addWidget(self.title)
        self.description = label("Запишите новую неподвижную позу одной руки. Действие назначается отдельно внутри профиля управления.", "muted")
        layout.addWidget(self.description)
        self.choice = QWidget()
        choice_layout = QVBoxLayout(self.choice)
        for title, kind in (("✋ Статический — положение руки без движения", "static"), ("↔ Динамический — движение руки или пальцев", "dynamic")):
            button = primary_button(title)
            button.clicked.connect(lambda checked=False, kind=kind: self.choose_type(kind))
            choice_layout.addWidget(button)
        layout.addWidget(self.choice)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Например, Мой жест")
        self.name_input.setMaxLength(40)
        self.name_input.returnPressed.connect(self._next)
        layout.addWidget(self.name_input)
        self.dynamic_kind = QComboBox()
        self.dynamic_kind.addItem("Движение руки", "trajectory")
        self.dynamic_kind.addItem("Изменение расстояния между пальцами", "pinch")
        self.dynamic_kind.addItem("Пользовательская последовательность — пока недоступна", "sequence")
        self.dynamic_kind.model().item(2).setEnabled(False)
        self.dynamic_kind.hide()
        layout.addWidget(self.dynamic_kind)
        self.preview = CameraPreview(camera_service, self)
        self.preview.setMinimumHeight(300)
        self.preview.hide()
        layout.addWidget(self.preview, 1)
        self.hint_label = message_label()
        layout.addWidget(self.hint_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.recognized_label = label("", "section")
        self.recognized_label.hide()
        layout.addWidget(self.recognized_label)
        self.result_label = message_label()
        layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.retry_button = QPushButton("Записать заново")
        self.retry_button.clicked.connect(self._begin_recording)
        self.retry_button.hide()
        buttons.addWidget(self.retry_button)
        buttons.addStretch()
        self.next_button = primary_button("Перейти к камере →")
        self.next_button.clicked.connect(self._next)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)
        self._connect(camera_service.frame_ready, self._on_frame)
        self._connect(camera_service.error, self._camera_error)
        self._connect(state.save_completed, self._saved)
        self._connect(state.save_failed, self._saving_failed)
        self.finished.connect(self._disconnect)
        self.title.setText("Какой жест вы хотите создать?")
        self.description.setText("Выберите положение руки или движение. Затем запишите пять отдельных примеров.")
        self.name_input.hide()
        self.next_button.hide()

    def choose_type(self, kind):
        if kind not in ("static", "dynamic") or self.step != -1:
            return
        self.recognition_type = kind
        if kind == "dynamic":
            logging.getLogger("DynamicGesture").info("Страница открыта")
            # В мастере движения выводим один статус вместо статической уверенности.
            for widget in (self.preview.gesture_label, self.preview.details_label, self.preview.status_label,
                           self.result_label, self.recognized_label):
                widget.hide()
            self.preview.setMinimumHeight(175)
        self.step = 0
        self.choice.hide()
        self.name_input.show()
        self.next_button.show()
        self.dynamic_kind.setVisible(kind == "dynamic")
        self.title.setText("Название жеста")
        self.description.setText("Запишите пять вариантов. Между примерами убирайте руку из кадра.")

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def _disconnect(self, *_):
        self.preview.detach()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
        self.step = -2

    def _next(self):
        if self.step == 0:
            name = self.name_input.text().strip()
            if not name:
                set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Введите название жеста.")
                self.name_input.setFocus()
                return
            if len(name) > 40:
                set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Название должно содержать не больше 40 символов.")
                return
            if any(item["name"].casefold() == name.casefold() for item in self.state.gestures):
                set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Жест с таким названием уже существует.")
                return
            self.name_input.setText(name)
            self._begin_recording()
        elif self.step == 1 and self.recognition_type == "dynamic":
            if self.recorder.begin_countdown(self._last_frame_time if self._last_frame_time is not None else time.monotonic()):
                self.next_button.setEnabled(False)
                set_message(self.hint_label, self.recorder.hint, "badge")
        elif self.step == 2 and self._verified:
            self._save()

    def _begin_recording(self):
        if self._gesture_id is not None or self._save_revision is not None:
            return
        self.step = 1
        self.recorded_data = None
        self._verification_detector = None
        self._verified = False
        self._verify_released = False
        self._last_frame_time = None
        self._stable_since = None
        self._verification_frames = 0
        self.recorder = MultiStaticRecorder() if self.recognition_type == "static" else DynamicGestureRecorder(self.dynamic_kind.currentData())
        self.recorder.start()
        self.dynamic_kind.setEnabled(False)
        self.title.setText("Запись жеста")
        self.description.setText("Запишите пять примеров. Статика: удерживайте позу; движение: дождитесь отсчёта и двигайте рукой. Между примерами убирайте руку.")
        self.name_input.setEnabled(False)
        self.preview.show()
        self.progress.show()
        self.progress.setValue(0)
        self.progress.setFormat("Сканирование: %p%")
        self.recognized_label.hide()
        self.retry_button.show()
        self.next_button.setText("Сканирование…")
        if self.recognition_type == "dynamic":
            self.next_button.setText("Начать запись")
            self.description.setText("Покажите руку и нажмите «Начать запись». После 3–2–1 выполняйте движение 2 секунды. Между примерами убирайте руку.")
            self.progress.setFormat("Кадров записано: 0/30 · Пример 1/5")
        self.next_button.setEnabled(False)
        set_message(self.hint_label, "Покажите одну руку", "muted")
        set_message(self.result_label, "", "muted")
        self.camera_service.start()

    def _camera_error(self, message):
        if self.recognition_type == "dynamic":
            logging.getLogger("DynamicGesture").error("%s", message)
        set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, message)
        self.next_button.setEnabled(False)
        self._stable_since = None
        self._verification_frames = 0
        if self.step == 1:
            self.recorder.reset()

    def _on_frame(self, payload):
        try:
            self._process_frame(payload)
        except Exception as error:
            if self.recognition_type != "dynamic":
                raise
            log_error("DynamicGesture", "Обработка кадра", error)
            self.recorder.restart_current()
            self.next_button.setEnabled(False)
            set_message(self.hint_label, str(error))

    def _process_frame(self, payload):
        if self.step not in (1, 2) or self._save_revision is not None:
            return
        hand = payload.get("hand", {})
        if self.recognition_type == "dynamic":
            logger = logging.getLogger("DynamicGesture")
            if not self._received_dynamic_frame:
                logger.info("Получен кадр")
                self._received_dynamic_frame = True
            observation = (bool(hand.get("found")), len(hand.get("landmarks", [])), hand.get("motion_ready"))
            if observation != self._dynamic_hand_state:
                logger.info("%s", "Рука обнаружена" if observation[0] else "Рука не обнаружена")
                logger.info("landmarks=%s; bbox=%s; handedness=%s; confidence=%s",
                            observation[1], hand.get("bbox"), hand.get("handedness"), hand.get("confidence"))
                self._dynamic_hand_state = observation
        now = float(payload.get("timestamp", time.monotonic()))
        gap = self._last_frame_time is not None and now - self._last_frame_time > 0.3
        self._last_frame_time = now
        if self.step == 1:
            if self.recorder.complete:
                return
            if gap and self.recognition_type == "static":
                self.recorder.restart_current()
            # Записываем несколько образцов пользовательского жеста, а не один удачный кадр.
            progress = self.recorder.add_sample(hand, now)
            if self.recognition_type == "dynamic":
                self.next_button.setEnabled(self.recorder.ready and not self.recorder.wait_release)
                self.progress.setFormat(f"Кадров записано: {len(self.recorder.frames)}/30 · Пример {min(5, len(self.recorder.examples)+1)}/5")
            self.progress.setValue(round(progress * 100))
            set_message(self.hint_label, self.recorder.hint, "badge" if hand.get("ready") else "muted")
            if self.recorder.complete:
                self._recording_complete()
            return

        if self._verified:
            return
        if gap:
            self._stable_since = None
            self._verification_frames = 0
        if self.recognition_type == "dynamic":
            if not self._verify_released:
                if not hand.get("found"):
                    self._verify_released = True
                    self._verification_detector.history.clear()
                set_message(self.hint_label, "Уберите руку, затем повторите движение", "badge")
                return
            matches = self._verification_detector.update(hand, now)
            if matches and matches[0]["confidence"] >= .8:
                self._verified = True
                self.next_button.setEnabled(True)
                self.progress.setValue(100)
                self.recognized_label.setText(f"Совпадение движения: {matches[0]['confidence']:.0%}")
                set_message(self.hint_label, "✓ Движение подтверждено", "success")
            return
        gesture = self._verification_detector.detect(hand) if hand.get("ready") else {}
        matches = gesture.get("key") == "recording" and gesture.get("confidence", 0) >= 0.75
        if not self._verify_released:
            # Просим повторить позу после отпускания: запись и проверка независимы.
            if not hand.get("found") or (hand.get("ready") and not matches):
                self._verify_released = True
                set_message(self.hint_label, "Снова покажите записанный жест", "badge")
            return
        if not matches:
            self._stable_since = None
            self._verification_frames = 0
            self.progress.setValue(0)
            self.recognized_label.setText("Распознано: —")
            set_message(self.hint_label, hand.get("hint", "Покажите записанный жест"), "muted")
            return
        if self._stable_since is None:
            self._stable_since = now
        self._verification_frames += 1
        duration = now - self._stable_since
        self.progress.setValue(min(100, round(duration * 100)))
        self.recognized_label.setText(f"Распознано: {self.name_input.text()}\nУверенность: {gesture['confidence']:.0%}")
        set_message(self.hint_label, "Держите жест неподвижно…", "badge")
        if duration >= 1.0 and self._verification_frames >= 10:
            self._verified = True
            self.progress.setValue(100)
            self.next_button.setEnabled(True)
            set_message(self.hint_label, "✓ Жест готов", "success")

    def _recording_complete(self):
        data = self.recorder.gesture_data()
        detector = GestureDetector(custom_gestures=self.state.gestures)
        duplicate = detector.find_similar(data) if self.recognition_type == "static" else None
        if duplicate is not None:
            set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, f"Этот жест очень похож на «{duplicate['name']}». Попробуйте другую позу и нажмите «Записать заново».")
            set_message(self.hint_label, "Нужна другая поза руки", "muted")
            return
        self.recorded_data = data
        recorded = [
            {"id": "recording", "key": "recording", "name": self.name_input.text(), "gesture_data": data, "is_custom": True}
        ]
        self._verification_detector = GestureDetector(recorded) if self.recognition_type == "static" else DynamicGestureDetector(recorded)
        self.step = 2
        self.title.setText("Проверка жеста")
        self.description.setText("Уберите руку или измените позу, затем покажите записанный жест ещё раз и удерживайте одну секунду.")
        if self.recognition_type == "dynamic":
            self.description.setText("Уберите руку, затем повторите записанное движение для проверки.")
        self.progress.setValue(0)
        self.progress.setFormat("Проверка: %p%")
        self.recognized_label.setText("Распознано: —")
        self.recognized_label.show()
        if self.recognition_type == "dynamic":
            self.recognized_label.hide()
        self.next_button.setText("Сохранить")
        set_message(self.hint_label, "Уберите руку, затем покажите жест ещё раз", "badge")
        set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Жест успешно записан. Осталось проверить повторяемость.", "success")

    def _save(self):
        if self._save_revision is not None or not self._verified or self.recorded_data is None:
            return
        try:
            if self._gesture_id is None:
                self._gesture_id = self.state.add_custom_gesture(self.name_input.text(), self.recorded_data)
            else:
                self.state.flush_async()
            self._save_revision = self.state.revision
        except ValueError as error:
            set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, str(error))
            return
        self.next_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Сохраняем жест…", "badge")

    def _saved(self, revision):
        if self._save_revision is not None and revision >= self._save_revision:
            self.accept()

    def _saving_failed(self, revision, message):
        if self._save_revision is not None and revision >= self._save_revision:
            self._save_revision = None
            self.next_button.setEnabled(True)
            self.cancel_button.setEnabled(True)
            set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, message)

    def reject(self):
        # Esc не прячет результат незавершённого сохранения. Выход из аккаунта
        # завершает запрос на уровне MainWindow и может закрыть мастер сразу.
        if self._save_revision is not None and not getattr(self.parent(), "_shutdown_kind", None):
            set_message(self.hint_label if self.recognition_type == "dynamic" else self.result_label, "Дождитесь завершения сохранения…", "badge")
            return
        super().reject()
