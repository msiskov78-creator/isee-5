"""Чтение единственной камеры и распознавание в рабочем QThread."""

from copy import deepcopy
import logging
import sys
from threading import Event, Lock
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from gesture_control.gesture_detector import GestureDetector
from gesture_control.dynamic_gesture_detector import DynamicGestureDetector
from hand_tracking.hand_detector import FINGERTIPS, HAND_CONNECTIONS, HandDetector, empty_hand


# Даже случайное создание второго сервиса не откроет вторую камеру одновременно.
_CAPTURE_LOCK = Lock()


logger = logging.getLogger("Camera")


class CameraWorker(QThread):
    frame_available = Signal()
    status_changed = Signal(str)
    error = Signal(str)
    cameras_found = Signal(object)

    def __init__(self, camera_index, settings, custom_gestures, scanning=False, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.scanning = scanning
        self._stop_event = Event()
        self._config_lock = Lock()
        self._settings = deepcopy(settings)
        self._custom_gestures = deepcopy(custom_gestures)
        self._version = 0
        self._frame_lock = Lock()
        self._latest_packet = None
        self._notification_pending = False

    def take_latest_frame(self):
        with self._frame_lock:
            packet, self._latest_packet = self._latest_packet, None
            self._notification_pending = False
            return packet

    def _publish_frame(self, packet):
        # Медленный UI получает свежий кадр, а не растущую очередь изображений.
        with self._frame_lock:
            self._latest_packet = packet
            notify = not self._notification_pending
            self._notification_pending = True
        if notify:
            self.frame_available.emit()

    def configure(self, settings, custom_gestures):
        with self._config_lock:
            self._settings = deepcopy(settings)
            self._custom_gestures = deepcopy(custom_gestures)
            self._version += 1

    def _snapshot(self):
        with self._config_lock:
            # configure заменяет целый снимок; кадры только читают его, без копирования образцов 25 раз/с.
            return self._settings, self._custom_gestures, self._version

    def request_stop(self):
        self._stop_event.set()

    @property
    def stopping(self):
        return self._stop_event.is_set()

    def _open_capture(self, cv2, index):
        # DirectShow обычно быстрее открывает USB-камеры в Windows.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        backends = [backend] if backend == cv2.CAP_ANY else [backend, cv2.CAP_ANY]
        for selected_backend in backends:
            if self.stopping:
                return None
            # Камера открывается только здесь. Предыдущая попытка уже освобождена.
            capture = cv2.VideoCapture(index, selected_backend)
            try:
                if capture is not None and capture.isOpened():
                    return capture
            except Exception:
                capture.release()
                raise
            capture.release()
        return None

    def _scan(self, cv2):
        cameras = []
        self.status_changed.emit("Поиск камер...")
        for index in range(6):
            if self.stopping:
                return
            capture = None
            try:
                capture = self._open_capture(cv2, index)
                if capture is not None and capture.isOpened():
                    success, _ = capture.read()
                    if success:
                        cameras.append({"index": index, "name": f"Камера {index}"})
            finally:
                if capture is not None:
                    capture.release()
        if not self.stopping:
            self.cameras_found.emit(cameras)
            self.status_changed.emit("Камеры найдены" if cameras else "Камера не найдена")

    def run(self):
        # Открытие камеры, MediaPipe и освобождение ресурсов остаются в одном
        # потоке и общем try/finally: дробление этого цикла усложнит завершение.
        capture = None
        detector = None
        acquired = False
        try:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError("Установите OpenCV: python -m pip install opencv-python") from exc
            while not self.stopping:
                acquired = _CAPTURE_LOCK.acquire(timeout=0.1)
                if acquired:
                    break
            if not acquired or self.stopping:
                return
            if self.scanning:
                self._scan(cv2)
                return
            self.status_changed.emit("Подключение камеры...")
            capture = self._open_capture(cv2, self.camera_index)
            if self.stopping:
                return
            if capture is None:
                raise RuntimeError(f"Камера {self.camera_index} не найдена или занята другим приложением")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_FPS, 30)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self.stopping:
                return
            self.status_changed.emit("Камера подключена")
            logger.info("Открыта камера %s", self.camera_index)
            settings, custom_gestures, version = self._snapshot()
            detector_error = ""
            try:
                detector = HandDetector(settings.get("model_path"))
            except Exception as exc:
                detector_error = f"Распознавание недоступно: {exc}"
                self.error.emit(detector_error)
            gestures = GestureDetector(custom_gestures)
            dynamic = DynamicGestureDetector(custom_gestures)
            previous_gesture = None
            previous_frame = None
            average_fps = 0.0
            failed_reads = 0
            while not self.stopping:
                started = time.monotonic()
                settings, custom_gestures, new_version = self._snapshot()
                if new_version != version:
                    gestures.configure(custom_gestures)
                    dynamic.configure(custom_gestures)
                    version = new_version
                success, frame = capture.read()
                if self.stopping:
                    break
                if not success or frame is None:
                    failed_reads += 1
                    if failed_reads >= 5:
                        raise RuntimeError("Камера отключена: не удалось прочитать кадр")
                    self._stop_event.wait(0.05)
                    continue
                failed_reads = 0
                if settings.get("mirror", settings.get("mirror_camera", True)):
                    frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                hand = empty_hand(detector_error) if detector_error else empty_hand()
                if detector is not None:
                    try:
                        hand = detector.detect(rgb, started)
                    except Exception as exc:
                        detector_error = f"Ошибка распознавания: {exc}"
                        self.error.emit(detector_error)
                        try:
                            detector.close()
                        finally:
                            detector = None
                        hand = empty_hand(detector_error)
                gesture = gestures.detect(hand)
                dynamic_gestures = dynamic.update(hand, started)
                if gesture["key"] != previous_gesture:
                    previous_gesture = gesture["key"]
                    if previous_gesture:
                        logging.getLogger("Gesture").info("Распознано: %s", previous_gesture)
                # Landmarks скрываются только визуально; детектор выше работает всегда.
                if settings.get("show_landmarks", True) and hand["found"]:
                    self._draw_landmarks(cv2, rgb, hand)
                height, width = rgb.shape[:2]
                # Передаём обработанный кадр в интерфейс с собственной копией памяти.
                image = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()
                if previous_frame is not None:
                    instant_fps = 1.0 / max(started - previous_frame, 0.001)
                    average_fps = instant_fps if average_fps == 0 else 0.85 * average_fps + 0.15 * instant_fps
                previous_frame = started
                self._publish_frame({"image": image, "hand": hand, "gesture": gesture,
                                       "dynamic_gestures": dynamic_gestures,
                                       "fps": round(average_fps, 1), "timestamp": started,
                                       "status": detector_error or hand["hint"],
                                       "camera_index": self.camera_index,
                                       "recognition_available": detector is not None})
                fps_limit = max(10, min(30, float(settings.get("target_fps", 25))))
                self._stop_event.wait(max(0.0, 1.0 / fps_limit - (time.monotonic() - started)))
        except Exception as exc:
            message = str(exc)
            logger.error("%s", message)
            self.error.emit(message)
            self.status_changed.emit(message)
        finally:
            # Освобождаем камеру при закрытии приложения, logout и любой ошибке.
            try:
                if capture is not None:
                    capture.release()
                    logger.info("Камера %s освобождена", self.camera_index)
            finally:
                try:
                    if detector is not None:
                        detector.close()
                except Exception:
                    pass
                finally:
                    if acquired:
                        _CAPTURE_LOCK.release()

    @staticmethod
    def _draw_landmarks(cv2, rgb, hand):
        height, width = rgb.shape[:2]
        points = [(int(p[0] * width), int(p[1] * height)) for p in hand["landmarks"]]
        for first, second in HAND_CONNECTIONS:
            cv2.line(rgb, points[first], points[second], (87, 201, 170), 2, cv2.LINE_AA)
        for index, point in enumerate(points):
            tip = index in FINGERTIPS.values()
            cv2.circle(rgb, point, 5 if tip else 3, (255, 240, 130) if tip else (240, 250, 255), -1, cv2.LINE_AA)
        if points:
            xs, ys = zip(*points)
            cv2.rectangle(rgb, (min(xs), min(ys)), (max(xs), max(ys)), (87, 201, 170), 1)

