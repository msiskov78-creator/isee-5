"""Мастера используют общий сервис и сохраняют только после устойчивой проверки."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from ui.gesture_wizard import GestureWizard
from ui.onboarding_wizard import OnboardingWizard


class CameraDouble(QObject):
    frame_ready = Signal(object)
    status_changed = Signal(str)
    error = Signal(str)
    stopped = Signal()
    cameras_found = Signal(object)

    def __init__(self):
        super().__init__()
        self.starts = []

    def start(self, index=0):
        self.starts.append(index)

    def scan_cameras(self):
        self.cameras_found.emit([{"index": 0, "name": "Камера 0"}])


class StateDouble(QObject):
    changed = Signal()
    save_completed = Signal(int)
    save_failed = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.settings = {"camera": 0, "onboarding_completed": False}
        self.gestures = []
        self.revision = 0
        self.added = []
        self.retries = 0

    def save_settings(self, **settings):
        self.settings.update(settings)
        self.revision += 1

    def add_custom_gesture(self, name, data):
        self.added.append((name, data))
        self.revision += 1
        return "custom-id"

    def flush_async(self):
        self.retries += 1


class RecorderDouble:
    def __init__(self, target_samples=40):
        self.target = target_samples
        self.start()

    def start(self):
        self.count = 0
        self.hint = "Держите жест неподвижно"

    reset = start
    restart_current = start

    @property
    def complete(self):
        return self.count >= self.target

    def add_sample(self, hand, now=None):
        if hand.get("ready"):
            self.count += 1
        return min(1, self.count / self.target)

    def gesture_data(self):
        return {"version": 1, "type": "static", "samples": [[0.0] * 63] * self.target}


class DetectorDouble:
    duplicate = None

    def __init__(self, custom_gestures=None):
        pass

    def find_similar(self, data):
        return self.duplicate

    def detect(self, hand):
        return {"key": "recording" if hand.get("pose") == "custom" else None, "confidence": 0.95}


class WizardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.state = StateDouble()
        self.camera = CameraDouble()
        self.dialogs = []
        self.timestamp = 0.0
        DetectorDouble.duplicate = None

    def tearDown(self):
        for dialog in self.dialogs:
            dialog._save_revision = None
            dialog.reject()
            dialog.deleteLater()
        self.app.processEvents()

    def frame(self, gesture=None, hand=None, camera_index=0):
        self.timestamp += 0.05
        if hand is None:
            hand = {"found": True, "ready": True, "count": 1, "pose": "custom",
                    "landmarks": [[0.1 + index * 0.03, 0.8 - index * 0.02, 0.0] for index in range(21)]}
        self.camera.frame_ready.emit({"timestamp": self.timestamp, "hand": hand,
                                      "gesture": gesture or {}, "camera_index": camera_index})

    def test_onboarding_requires_camera_and_all_four_stable_gestures(self):
        dialog = OnboardingWizard(self.state, self.camera)
        self.dialogs.append(dialog)
        dialog.show()
        dialog._next()
        self.assertEqual(dialog.step, 0)
        dialog._check_camera()
        self.assertEqual(self.camera.starts, [0])
        self.frame(camera_index=1)
        self.assertFalse(dialog.next_button.isEnabled())
        self.frame()
        dialog._next()
        self.assertEqual(dialog.step, 1)
        self.frame(hand={"found": False, "ready": False, "hint": "Поднесите руку ближе"})
        self.assertEqual(dialog.hint_label.text(), "Поднесите руку ближе")
        for _ in range(20):
            self.frame()
        dialog._next()
        self.assertEqual(dialog.step, 2)
        self.frame({"key": "thumbs_up", "confidence": 0.98})
        self.assertEqual(dialog._gesture_index, 0)
        for key, _ in dialog.GESTURES:
            for _ in range(16):
                self.frame({"key": key, "confidence": 0.98})
        self.assertEqual(dialog._gesture_index, 4)
        self.assertFalse(self.state.settings["onboarding_completed"])
        dialog._next()
        self.assertEqual(dialog.step, 3)
        accepted = QSignalSpy(dialog.accepted)
        dialog._next()
        self.assertTrue(self.state.settings["onboarding_completed"])
        self.assertEqual(accepted.count(), 0)
        dialog.reject()
        self.assertTrue(dialog.isVisible(), "Esc не должен скрыть незавершённое сохранение")
        self.state.save_completed.emit(self.state.revision)
        self.assertEqual(accepted.count(), 1)

    @patch("ui.gesture_wizard.GestureDetector", DetectorDouble)
    @patch("ui.gesture_wizard.MultiStaticRecorder", RecorderDouble)
    def test_record_verify_release_and_retry_save_without_duplicate(self):
        dialog = GestureWizard(self.state, self.camera)
        dialog.choose_type("static")
        self.dialogs.append(dialog)
        dialog.show()
        dialog.name_input.setText("Моя поза")
        dialog._next()
        for _ in range(40):
            self.frame()
        self.assertEqual(dialog.step, 2)
        for _ in range(25):
            self.frame()
        self.assertFalse(dialog.next_button.isEnabled(), "Сначала нужно повторить жест после отпускания")
        self.frame(hand={"found": False, "ready": False})
        for _ in range(25):
            self.frame()
        self.assertTrue(dialog.next_button.isEnabled())
        self.assertEqual(self.state.added, [])
        accepted = QSignalSpy(dialog.accepted)
        dialog._next()
        self.assertEqual(len(self.state.added), 1)
        self.state.save_failed.emit(self.state.revision, "Проверьте соединение")
        self.assertIn("соединение", dialog.result_label.text())
        self.assertEqual(accepted.count(), 0)
        dialog._next()
        self.assertEqual(len(self.state.added), 1)
        self.assertEqual(self.state.retries, 1)
        self.state.save_completed.emit(self.state.revision)
        self.assertEqual(accepted.count(), 1)

    @patch("ui.gesture_wizard.GestureDetector", DetectorDouble)
    @patch("ui.gesture_wizard.MultiStaticRecorder", RecorderDouble)
    def test_duplicate_pose_cannot_be_saved(self):
        DetectorDouble.duplicate = {"name": "Открытая ладонь"}
        dialog = GestureWizard(self.state, self.camera)
        dialog.choose_type("static")
        self.dialogs.append(dialog)
        dialog.name_input.setText("Моя поза")
        dialog._next()
        for _ in range(40):
            self.frame()
        self.assertEqual(dialog.step, 1)
        self.assertIn("Открытая ладонь", dialog.result_label.text())
        self.assertFalse(dialog.next_button.isEnabled())
        dialog._next()
        self.assertEqual(self.state.added, [])


if __name__ == "__main__":
    unittest.main()
