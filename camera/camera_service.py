"""Центральный сервис камеры: один поток, любое количество экранов."""

from copy import deepcopy
import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from camera.camera_worker import CameraWorker

logger = logging.getLogger("Camera")


class CameraService(QObject):
    # Пакет содержит QImage, hand, gesture, fps, timestamp и camera_index.
    frame_ready = Signal(object)
    status_changed = Signal(str)
    error = Signal(str)
    started = Signal()
    stopped = Signal()
    cameras_found = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._settings = {}
        self._custom_gestures = []
        self._pending_start = None
        self._pending_scan = False
        self._active_requested = False
        self.last_packet = None
        self.status = "Камера не подключена"
        self.last_error = ""

    @property
    def mirror_camera(self):
        return self._settings.get("mirror", True)

    @property
    def show_landmarks(self):
        return self._settings.get("show_landmarks", True)

    @property
    def is_running(self):
        return self._worker is not None and not self._worker.scanning and not self._worker.stopping

    @property
    def is_busy(self):
        """Учитываем поиск и завершение потока перед уничтожением MainWindow."""
        return self._worker is not None

    @property
    def camera_index(self):
        if self._pending_start is not None:
            return self._pending_start
        if self._worker is not None and not self._worker.scanning:
            return self._worker.camera_index
        return self._settings.get("camera", 0)

    def configure(self, settings, custom_gestures=None):
        previous_index = self._settings.get("camera", 0)
        self._settings = deepcopy(settings)
        if custom_gestures is not None:
            self._custom_gestures = deepcopy(custom_gestures)
        if self._worker is not None:
            self._worker.configure(self._settings, self._custom_gestures)
            # Последнее выбранное устройство побеждает даже во время остановки/поиска.
            if self._active_requested and settings.get("camera", 0) != previous_index:
                self.start(settings.get("camera", 0))

    def start(self, camera_index=None):
        # Окна без явного выбора устройства присоединяются к текущему потоку.
        if camera_index is None:
            camera_index = self.camera_index
        if type(camera_index) is not int or camera_index < 0:
            self._on_error("Номер камеры должен быть целым неотрицательным числом")
            return
        self._active_requested = True
        if self._worker is not None:
            if self.is_running and self._worker.camera_index == camera_index:
                return
            self._pending_start = camera_index
            # Подписка во время поиска не должна обрывать поиск устройств.
            if not self._worker.scanning:
                self._worker.request_stop()
            return
        self._launch(camera_index)

    def stop(self):
        self._active_requested = False
        self._pending_start = None
        self._pending_scan = False
        self.last_packet = None
        if self._worker is not None:
            self._set_status("Остановка камеры...")
            self._worker.request_stop()
        else:
            self._set_status("Камера не подключена")
            self.stopped.emit()

    def scan_cameras(self):
        if self._worker is not None:
            if self._worker.scanning or self._pending_scan:
                return
            if self._pending_start is None and self.is_running:
                self._pending_start = self._worker.camera_index
            self._pending_scan = True
            self._worker.request_stop()
            return
        self._launch(0, scanning=True)

    def _launch(self, camera_index, scanning=False):
        self.last_packet = None
        self.last_error = ""
        worker = CameraWorker(camera_index, self._settings, self._custom_gestures, scanning, self)
        self._worker = worker
        worker.frame_available.connect(self._forward_frame)
        worker.status_changed.connect(self._set_status)
        worker.error.connect(self._on_error)
        worker.cameras_found.connect(self.cameras_found)
        worker.finished.connect(self._worker_finished)
        logger.info("%s", "Поиск камер запущен" if scanning else f"starting camera index {camera_index}")
        worker.start()

    @Slot(str)
    def _set_status(self, text):
        self.status = text
        self.status_changed.emit(text)

    @Slot(str)
    def _on_error(self, text):
        self.last_error = text
        self.error.emit(text)

    @Slot()
    def _forward_frame(self):
        worker = self.sender()
        if worker is not self._worker:
            return
        packet = worker.take_latest_frame()
        # Уже поставленные в очередь кадры не оживляют UI после stop/logout.
        if packet is not None and self.is_running:
            first_frame = self.last_packet is None
            self.last_packet = packet
            if first_frame:
                self.started.emit()
            # Отправляем один и тот же обработанный пакет всем подписчикам.
            self.frame_ready.emit(packet)

    @Slot()
    def _worker_finished(self):
        worker = self._worker
        if worker is None:
            return
        # finished может прийти до завершения thread-local cleanup. wait(0)
        # проверяет полное завершение без блокировки интерфейса.
        if not worker.wait(0):
            QTimer.singleShot(10, self._worker_finished)
            return
        self._worker = None
        worker.deleteLater()
        self.last_packet = None
        logger.info("Поток остановлен")
        if self._pending_scan:
            self._pending_scan = False
            self._launch(0, scanning=True)
        elif self._pending_start is not None:
            camera_index, self._pending_start = self._pending_start, None
            self._launch(camera_index)
        else:
            self._set_status("Камера не подключена")
            self.stopped.emit()
