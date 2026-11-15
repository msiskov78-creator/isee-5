"""Проверка настоящих Qt-сигналов мастера без камеры и статического распознавания."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from PySide6.QtWidgets import QApplication
from app_state import AppState
from ui.gesture_wizard import GestureWizard
from test_wizards import CameraDouble
from test_dynamic_features import moving_hand, pinch_hand


class DynamicWizardFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_wizard(self, kind="trajectory"):
        state, camera = AppState(), CameraDouble()
        wizard = GestureWizard(state, camera)
        wizard.choose_type("dynamic")
        wizard.name_input.setText("Тест движения")
        wizard.dynamic_kind.setCurrentIndex(1 if kind == "pinch" else 0)
        wizard._next()
        self.addCleanup(lambda: (setattr(wizard, "_save_revision", None), wizard.reject()))
        return wizard, camera, state

    def emit(self, camera, hand, now):
        camera.frame_ready.emit({"hand": hand, "timestamp": now,
                                 "gesture": {"key": None, "confidence": 0}})

    def test_pinch_full_flow_saves_landmarks_and_appears_in_state(self):
        wizard, camera, state = self.make_wizard("pinch")
        now = 0.
        for example in range(5):
            self.emit(camera, pinch_hand(.1), now)
            self.assertTrue(wizard.next_button.isEnabled())
            wizard.next_button.click()
            for i in range(1, 106):
                now += .05
                self.emit(camera, pinch_hand(.1 + max(0, i-60)*.02), now)
                if len(wizard.recorder.examples) == example+1:
                    break
            self.assertEqual(len(wizard.recorder.examples), example+1)
            now += .05
            self.emit(camera, {"found": False}, now)
        self.assertEqual(wizard.step, 2)
        for i in range(40):
            now += .05
            self.emit(camera, pinch_hand(.1+i*.02), now)
        self.assertTrue(wizard._verified)
        wizard.next_button.click()
        saved = next(g for g in state.gestures if g["name"] == "Тест движения")
        sample = saved["gesture_data"]["samples"][0]
        self.assertEqual((len(sample["frames"]), len(sample["frames"][0])), (30, 63))
        self.assertEqual(len(sample["pinch"]), 30)
        self.assertGreater(max(sample["pinch"])-min(sample["pinch"]), .25)
        self.assertEqual(len(camera.starts), 1)
        state.save_completed.emit(state.revision)
        self.assertEqual(wizard._connections, [])
        self.assertEqual(wizard.preview._connections, [])

    def test_readiness_countdown_and_lost_hand(self):
        wizard, camera, _ = self.make_wizard()
        self.emit(camera, {"found": False}, 0.)
        self.assertFalse(wizard.next_button.isEnabled())
        hand = moving_hand(0)
        hand.update(motion_ready=False, hint="Поднесите руку ближе")
        self.emit(camera, hand, .1)
        self.assertIn("ближе", wizard.hint_label.text())
        self.emit(camera, moving_hand(0), .2)
        self.assertTrue(wizard.next_button.isEnabled())
        self.assertIsNone(wizard.recorder.prepared_at)
        wizard.next_button.click()
        for now, digit in ((.2,"3"),(1.2,"2"),(2.2,"1")):
            self.emit(camera, moving_hand(0), now)
            self.assertIn(digit, wizard.hint_label.text())
        self.emit(camera, {"found":False}, 2.3)
        self.assertIsNone(wizard.recorder.prepared_at)
        self.assertFalse(wizard.next_button.isEnabled())

    def test_slow_frames_do_not_reset_countdown_every_point_three_seconds(self):
        wizard, camera, _ = self.make_wizard()
        self.emit(camera, moving_hand(0), 0.)
        wizard.next_button.click()
        for i in range(1,9):
            self.emit(camera, moving_hand(0), i*.4)
        self.assertIsNotNone(wizard.recorder.recording_at)

    def test_malformed_landmarks_log_exact_error(self):
        wizard, camera, _ = self.make_wizard()
        hand = moving_hand(0)
        hand["landmarks"] = []
        with self.assertLogs("DynamicGesture", level="ERROR") as captured:
            self.emit(camera, hand, 0.)
        self.assertIn("IndexError", captured.output[0])
        self.assertFalse(wizard.next_button.isEnabled())

    def test_close_reopen_and_single_status(self):
        wizard, camera, state = self.make_wizard()
        wizard.show()
        self.app.processEvents()
        for widget in (wizard.preview.gesture_label, wizard.preview.details_label,
                       wizard.preview.status_label, wizard.result_label, wizard.recognized_label):
            self.assertFalse(widget.isVisible())
        wizard.reject()
        self.assertEqual(wizard._connections, [])
        self.assertEqual(wizard.preview._connections, [])
        self.emit(camera, moving_hand(0), 1.)
        self.assertEqual(wizard.step, -2)
        reopened = GestureWizard(state, camera)
        reopened.choose_type("dynamic")
        reopened.name_input.setText("Повторное открытие")
        reopened._next()
        self.emit(camera, moving_hand(0), 2.)
        self.assertTrue(reopened.next_button.isEnabled())
        reopened.reject()
