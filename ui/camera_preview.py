"""Все превью подписываются на один сервис и не открывают камеру сами."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui.widgets import label, set_message


class VideoSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.setMinimumSize(280, 175)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#090d16"))
        if self.image is None or self.image.isNull():
            painter.setPen(QColor("#8d96aa"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Камера не подключена")
            return
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x, y = (self.width() - size.width()) // 2, (self.height() - size.height()) // 2
        painter.drawImage(x, y, self.image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))


class CameraPreview(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._connections = []
        self.last_packet = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.video = VideoSurface(self)
        layout.addWidget(self.video, 1)
        self.gesture_label = label("Ожидание жеста", "section")
        self.details_label = label("Уверенность: — · FPS: —", "muted")
        self.status_label = label("● Камера не подключена", "muted")
        layout.addWidget(self.gesture_label)
        layout.addWidget(self.details_label)
        layout.addWidget(self.status_label)
        if service is not None:
            for signal, slot in ((service.frame_ready, self.update_frame),
                                 (service.status_changed, self.update_status),
                                 (service.error, self.show_error), (service.stopped, self.clear)):
                signal.connect(slot)
                self._connections.append((signal, slot))
            logging.getLogger("Camera").info("Подписчик: %s", type(parent).__name__ if parent else "CameraPreview")
            if getattr(service, "last_packet", None) is not None:
                self.update_frame(service.last_packet)
            else:
                self.update_status(getattr(service, "status", "Камера не подключена"))
            if getattr(service, "last_error", ""):
                self.show_error(service.last_error)

    def detach(self, *_):
        # Закрытие отдельного превью удаляет подписку, но не останавливает камеру.
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()

    def update_frame(self, packet):
        # QImage уже скопирован рабочим потоком; здесь только отображение.
        self.last_packet = packet
        self.video.image = packet.get("image")
        if self.isVisible():
            self.video.update()
        movements = packet.get("dynamic_gestures") or []
        gesture = movements[0] if movements else packet.get("gesture") or {}
        self.gesture_label.setText(gesture.get("name") or "Ожидание жеста")
        confidence = float(gesture.get("confidence", 0))
        self.details_label.setText(f"Уверенность: {confidence:.0%} · FPS: {packet.get('fps', 0):.1f}")
        hand = packet.get("hand") or {}
        text = hand.get("hint") or ("Рука обнаружена" if hand.get("found") else "Рука не обнаружена")
        role = "success" if hand.get("ready") else "badge"
        if packet.get("recognition_available") is False:
            role = "error"
        set_message(self.status_label, "● " + text, role)

    def update_status(self, text):
        role = "success" if "подключена" in text and "не подключена" not in text else "muted"
        set_message(self.status_label, "● " + text, role)

    def show_error(self, text):
        set_message(self.status_label, text, "error")

    def clear(self):
        self.video.image = None
        self.last_packet = None
        self.video.update()
        self.gesture_label.setText("Ожидание жеста")
        self.details_label.setText("Уверенность: — · FPS: —")
        self.update_status("Камера не подключена")
        if getattr(self.service, "last_error", ""):
            self.show_error(self.service.last_error)


class CameraDialog(QDialog):
    def __init__(self, service, state, controller=None, parent=None, target_gesture=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Gesture Control — камера")
        self.resize(900, 600)
        self.setMinimumSize(640, 480)
        self.target_gesture = target_gesture
        from gesture_control.dynamic_gesture_detector import PinchControl
        self._pinch_preview = PinchControl()
        self._match_since = None
        self._match_last = None
        self._connections = []
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.profile_label = label("", "section")
        top.addWidget(self.profile_label, 1)
        close = QPushButton("Свернуть · Esc")
        close.clicked.connect(self.reject)
        top.addWidget(close)
        layout.addLayout(top)
        if target_gesture:
            hint = label(f"Проверка жеста: {target_gesture}. Здесь проверяется только распознавание. "
                         "Для выполнения действий закройте проверку и нажмите «Включить управление» на главной.", "badge")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.verification_status = label("Ожидание указанного жеста", "muted")
            layout.addWidget(self.verification_status)
            service.frame_ready.connect(self.verify_gesture)
            self._connections.append((service.frame_ready, self.verify_gesture))
        self.preview = CameraPreview(service, self)
        self.finished.connect(self._disconnect)
        layout.addWidget(self.preview, 1)
        self.system_status = label("Управление приостановлено", "muted")
        layout.addWidget(self.system_status)
        self.state = state
        state.changed.connect(self.refresh_profile)
        self.refresh_profile()
        if controller is not None:
            controller.status_changed.connect(self.system_status.setText)
            self.system_status.setText(controller.status)

    def _disconnect(self, *_):
        self.preview.detach()
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()

    def refresh_profile(self):
        self.profile_label.setText("Активный профиль: " + self.state.active_profile_name)

    def verify_gesture(self, packet):
        # Проверка движения использует тот же поток, но никогда не исполняет команды.
        for movement in packet.get("dynamic_gestures") or []:
            if movement.get("name") == self.target_gesture and movement.get("confidence", 0) >= .7:
                set_message(self.verification_status, f"✓ Движение распознано · {movement['confidence']:.0%}", "success")
                return
        target = next((g for g in self.state.gestures if g["name"] == self.target_gesture), {})
        if target.get("key") == "pinch_volume":
            self._pinch_preview.update(packet.get("hand") or {}, packet.get("timestamp", 0))
            if self._pinch_preview.active:
                set_message(self.verification_status, f"✓ Pinch активен · {self._pinch_preview.value:.0%}", "success")
            else:
                set_message(self.verification_status, "Сомкните пальцы на 0,5 с, остальные раскройте", "badge")
            return
        gesture, hand = packet.get("gesture") or {}, packet.get("hand") or {}
        now = packet.get("timestamp", 0)
        matches = (gesture.get("name") == self.target_gesture and hand.get("ready")
                   and gesture.get("confidence", 0) >= .7)
        if not matches or (self._match_last is not None and now - self._match_last > .3):
            self._match_since = None
        self._match_last = now
        if not matches:
            set_message(self.verification_status, "Покажите указанный жест", "muted")
            return
        if self._match_since is None:
            self._match_since = now
        if now - self._match_since >= .5:
            set_message(self.verification_status, "✓ Жест распознан устойчиво", "success")
        else:
            set_message(self.verification_status, "Держите жест неподвижно…", "badge")
