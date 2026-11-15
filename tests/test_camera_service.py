"""Настоящий QThread и искусственный источник кадров: один capture и корректный release."""

import os
import ast
from pathlib import Path
import time
import unittest
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from camera.camera_service import CameraService
from hand_tracking.hand_detector import empty_hand
from ui.camera_preview import CameraPreview
from ui.main_window import MainWindow
from camera.camera_worker import CameraWorker
from test_recognition import pose


class FakeCapture:
    active = 0
    maximum = 0
    opened = []
    threads = []
    def __init__(self, index, backend):
        self.released = False
        type(self).active += 1
        type(self).maximum = max(type(self).maximum,type(self).active)
        type(self).opened.append(index)
        type(self).threads.append(get_ident())
    def isOpened(self): return True
    def set(self, *args): return True
    def read(self):
        time.sleep(.005)
        return True,np.zeros((120,160,3),dtype=np.uint8)
    def release(self):
        if not self.released:
            type(self).active -= 1
            self.released = True


class FakeDetector:
    def __init__(self, *args): pass
    def detect(self, *args): return empty_hand()
    def close(self): pass


class PoseDetector(FakeDetector):
    hand = empty_hand()
    def detect(self, *args): return type(self).hand


class CameraServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        FakeCapture.active = FakeCapture.maximum = 0
        FakeCapture.opened = []
        FakeCapture.threads = []

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic()<deadline:
            QTest.qWait(10)
            # qWait в PySide удерживает GIL; даём Python-коду рабочего потока квант.
            time.sleep(.005)
        self.assertTrue(predicate())

    def test_capture_can_only_be_constructed_in_camera_worker(self):
        root = Path(__file__).resolve().parents[1]
        sources = list(root.glob("*.py"))
        for directory in ("camera", "ui", "hand_tracking", "gesture_control", "actions", "database"):
            sources.extend((root / directory).rglob("*.py"))
        constructors = []
        for source in sources:
            tree = ast.parse(source.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "VideoCapture":
                    constructors.append(source.relative_to(root).as_posix())
        self.assertEqual(constructors, ["camera/camera_worker.py"])

    def test_shared_previews_switch_scan_stop_and_ui_heartbeat(self):
        FakeCapture.active=FakeCapture.maximum=0
        FakeCapture.opened=[]
        camera=CameraService()
        first, second=CameraPreview(camera),CameraPreview(camera)
        frames, ticks, scanned=[],[],[]
        camera.frame_ready.connect(frames.append)
        camera.cameras_found.connect(scanned.append)
        timer=QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda:ticks.append(1))
        with patch("cv2.VideoCapture",FakeCapture),patch("camera.camera_worker.HandDetector",FakeDetector):
            try:
                timer.start()
                camera.start(0)
                camera.start(0)
                self.wait_for(lambda:len(frames)>3)
                self.assertEqual(FakeCapture.opened,[0])
                self.assertIs(first.last_packet,second.last_packet)
                self.assertGreater(len(ticks),3)
                camera.configure({"camera":1},[])
                self.wait_for(lambda:frames[-1]["camera_index"]==1)
                camera.scan_cameras()
                self.wait_for(lambda:bool(scanned))
                self.wait_for(lambda:camera.is_running)
                camera.stop()
                self.wait_for(lambda:not camera.is_busy)
                self.assertEqual(FakeCapture.maximum,1)
                self.assertEqual(FakeCapture.active,0)
            finally:
                camera.stop()
                self.wait_for(lambda:not camera.is_busy)
                timer.stop()
                first.deleteLater()
                second.deleteLater()

    def test_checkbox_updates_pixels_without_reopening_or_stopping_detection(self):
        from app_state import AppState
        from ui.pages.settings_page import SettingsPage
        state, camera = AppState(), CameraService()
        page = SettingsPage(state, camera)
        PoseDetector.hand = pose("open_palm")
        frame = np.zeros((120,160,3),dtype=np.uint8)
        frame[:,:80] = (20,40,220)
        frame[:,80:] = (150,30,10)
        with patch("cv2.VideoCapture",FakeCapture), patch.object(FakeCapture,"read",return_value=(True,frame)), patch("camera.camera_worker.HandDetector",PoseDetector):
            try:
                camera.configure(state.settings, [])
                camera.start(0)
                self.wait_for(lambda: camera.last_packet is not None)
                page.landmarks_check.setChecked(False)
                page.mirror_check.setChecked(False)
                self.wait_for(lambda: camera.last_packet["image"].pixelColor(0,0).red()==220)
                clean = camera.last_packet["image"].copy()
                self.assertEqual(camera.last_packet["gesture"]["key"],"open_palm")
                page.mirror_check.setChecked(True)
                self.wait_for(lambda: camera.last_packet["image"].pixelColor(0,0).red()==10)
                page.mirror_check.setChecked(False)
                page.landmarks_check.setChecked(True)
                self.wait_for(lambda: camera.last_packet["image"].pixelColor(0,0).red()==220 and camera.last_packet["image"]!=clean)
                page.landmarks_check.setChecked(False)
                self.wait_for(lambda: camera.last_packet["image"]==clean)
                self.assertEqual(camera.last_packet["gesture"]["key"],"open_palm")
                self.assertEqual(FakeCapture.opened,[0])
            finally:
                camera.stop()
                self.wait_for(lambda:not camera.is_busy)
                page.preview.detach()
                page.close()

    def test_main_wizard_fullscreen_settings_and_onboarding_share_capture(self):
        # Полный цикл настоящих окон и записи, подменены только камера и MediaPipe.
        PoseDetector.hand = pose("custom")
        with patch("cv2.VideoCapture", FakeCapture), patch("camera.camera_worker.HandDetector", PoseDetector):
            window = MainWindow(SimpleNamespace(id="demo", user_metadata={"username": "student"}), SimpleNamespace())
            camera = window.camera_service
            home = window.pages["home"].preview
            window.show()
            try:
                camera.start(2)  # Проверяем и несохранённый выбор устройства.
                self.wait_for(lambda: home.last_packet is not None)
                window.show_page("gestures")
                window.pages["gestures"]._add_gesture()
                wizard = window.pages["gestures"]._wizard
                wizard.choose_type("static")
                wizard.name_input.setText("Тестовая поза")
                wizard._next()
                for example in range(5):
                    PoseDetector.hand = pose("custom")
                    self.wait_for(lambda: len(wizard.recorder.examples) == example + 1, timeout=4)
                    if example < 4:
                        PoseDetector.hand = empty_hand()
                        self.wait_for(lambda: not wizard.recorder.wait_release)
                self.wait_for(lambda: wizard.step == 2)
                self.assertIs(home.last_packet, wizard.preview.last_packet)
                self.assertIs(home.last_packet, window.pages["settings"].preview.last_packet)
                self.assertEqual(FakeCapture.opened, [2])
                self.assertEqual(len(wizard.recorded_data["samples"]), 5)
                PoseDetector.hand = empty_hand()
                self.wait_for(lambda: wizard._verify_released)
                PoseDetector.hand = pose("custom")
                self.wait_for(lambda: wizard._verified)
                wizard._save()
                self.wait_for(lambda: window.pages["gestures"]._wizard is None)
                self.assertIn("Тестовая поза", [g["name"] for g in window.state.gestures])
                self.assertEqual(FakeCapture.opened, [2])
                window.show_page("home")
                window.expand_camera()
                dialog = window._camera_dialog
                self.wait_for(lambda: dialog.preview.last_packet is home.last_packet)
                dialog.reject()
                self.assertTrue(camera.is_running)
                window.open_onboarding()
                onboarding = window._onboarding
                self.wait_for(lambda: onboarding.preview.last_packet is home.last_packet)
                onboarding.reject()
                self.assertEqual(FakeCapture.opened, [2])
                self.assertEqual(FakeCapture.maximum, 1)
                self.assertTrue(all(t != get_ident() for t in FakeCapture.threads))
            finally:
                window.close()
                self.wait_for(lambda: not camera.is_busy)
                QTest.qWait(30)
            self.assertEqual(FakeCapture.active, 0)

    def test_latest_configuration_wins_while_previous_camera_stops(self):
        camera = CameraService()
        with patch("cv2.VideoCapture", FakeCapture), patch("camera.camera_worker.HandDetector", FakeDetector):
            try:
                camera.start(0)
                self.wait_for(lambda: camera.last_packet is not None)
                camera.configure({"camera": 1})
                camera.configure({"camera": 2})
                self.wait_for(lambda: camera.last_packet is not None and camera.last_packet["camera_index"] == 2)
                self.assertEqual(FakeCapture.opened, [0, 2])
                camera.stop()
                self.wait_for(lambda: not camera.is_busy)
                camera.start()
                self.wait_for(lambda: camera.last_packet is not None)
                self.assertEqual(FakeCapture.opened, [0, 2, 2])
                self.assertEqual(FakeCapture.maximum, 1)
            finally:
                camera.stop()
                self.wait_for(lambda: not camera.is_busy)

    def test_unplug_releases_capture_and_error_remains_visible(self):
        camera = CameraService()
        preview = CameraPreview(camera)
        errors = []
        camera.error.connect(errors.append)
        with patch("cv2.VideoCapture", FakeCapture), patch("camera.camera_worker.HandDetector", FakeDetector):
            try:
                camera.start()
                self.wait_for(lambda: preview.last_packet is not None)
                with patch.object(FakeCapture, "read", return_value=(False, None)):
                    self.wait_for(lambda: not camera.is_busy)
                self.assertEqual(FakeCapture.active, 0)
                self.assertTrue(errors)
                self.assertEqual(preview.status_label.text(), errors[-1])
                self.assertIsNone(camera.last_packet)
                camera.start()
                self.wait_for(lambda: preview.last_packet is not None)
                self.assertEqual(camera.last_error, "")
            finally:
                camera.stop()
                self.wait_for(lambda: not camera.is_busy)
                preview.detach()
                preview.deleteLater()

    def test_backend_failure_releases_before_fallback(self):
        worker = CameraWorker(0, {}, [])
        failed = SimpleNamespace(isOpened=lambda: False, release=lambda: events.append("release"))
        opened = SimpleNamespace(isOpened=lambda: True)
        events = []
        def factory(index, backend):
            events.append(backend)
            return failed if backend == 1 else opened
        cv = SimpleNamespace(CAP_DSHOW=1, CAP_ANY=0, VideoCapture=factory)
        with patch("camera.camera_worker.sys.platform", "win32"):
            self.assertIs(worker._open_capture(cv, 0), opened)
        self.assertEqual(events, [1, "release", 0])

    def test_stop_cancels_pending_restart_and_late_settings(self):
        camera = CameraService()
        with patch("cv2.VideoCapture", FakeCapture), patch("camera.camera_worker.HandDetector", FakeDetector):
            try:
                camera.start(0)
                self.wait_for(lambda: camera.last_packet is not None)
                camera.start(1)
                camera.stop()
                camera.configure({"camera": 2})
                self.wait_for(lambda: not camera.is_busy)
                self.assertEqual(FakeCapture.opened, [0])
                self.assertEqual(FakeCapture.active, 0)
                self.assertIsNone(camera.last_packet)
            finally:
                camera.stop()
                self.wait_for(lambda: not camera.is_busy)

    def test_slow_ui_receives_latest_frame_without_backlog(self):
        worker = CameraWorker(0, {}, [])
        notifications = []
        worker.frame_available.connect(lambda: notifications.append(True))
        for index in range(100):
            worker._publish_frame({"number": index})
        self.assertEqual(len(notifications), 1)
        self.assertEqual(worker.take_latest_frame(), {"number": 99})
        worker._publish_frame({"number": 100})
        self.assertEqual(len(notifications), 2)

    def test_closed_wizard_detaches_even_before_qt_deletes_it(self):
        from app_state import AppState
        from ui.gesture_wizard import GestureWizard
        camera = CameraService()
        wizard = GestureWizard(AppState(), camera)
        wizard.reject()
        camera.frame_ready.emit({"hand": empty_hand()})
        self.assertIsNone(wizard.preview.last_packet)
        wizard.deleteLater()


if __name__ == "__main__": unittest.main()
