"""Проверяем весь путь от кадра до назначения активного профиля без камеры и сети."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app_state import AppState
from control_runtime import ControlRuntime


class FakeCamera(QObject):
    frame_ready = Signal(object)
    status_changed = Signal(str)
    error = Signal(str)
    stopped = Signal()
    cameras_found = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.starts = []
        self.is_busy = False
        self.is_running = False
        self.last_configuration = None

    def configure(self, settings, custom_gestures):
        self.last_configuration = (settings, custom_gestures)

    def start(self, index=0):
        self.starts.append(index)
        self.is_running = self.is_busy = True
        self.status_changed.emit("Камера подключена")

    def stop(self):
        self.is_running = self.is_busy = False
        self.stopped.emit()

    def scan_cameras(self):
        self.cameras_found.emit([{"index": 0, "name": "Камера 0"}])


class ControlRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state, self.camera = AppState(), FakeCamera()
        self.runtime = ControlRuntime(self.state, self.camera)
        self.actions = []
        self.runtime.action_performed.connect(self.actions.append)

    def frame(self, timestamp, name="Большой палец вверх", key="thumbs_up", ready=True):
        self.camera.frame_ready.emit({"timestamp": timestamp, "hand": {"ready": ready},
                                      "gesture": {"name": name, "key": key, "confidence": .99}})

    def hold(self, start, duration, **kwargs):
        for index in range(round(duration * 20) + 1):
            self.frame(start + index / 20, **kwargs)

    def test_profile_action_hold_and_no_frame_spam(self):
        self.runtime.set_enabled(True)
        self.hold(10, .3)
        self.assertEqual(self.actions, [])
        self.hold(10.35, .35)
        self.assertEqual(len(self.actions), 1)
        self.assertIn("Play / Pause", self.actions[0])
        self.hold(10.75, 4)
        self.assertEqual(len(self.actions), 1)
        self.state.set_active_profile(self.state.profiles[1]["id"])
        self.frame(16)
        self.assertEqual(len(self.actions), 1)
        self.hold(16.05, .65)
        self.assertEqual(len(self.actions), 2)
        self.assertIn("Следующий слайд", self.actions[-1])

    def test_disabled_binding_and_modal_suspension(self):
        self.runtime.set_enabled(True)
        self.runtime.suspend()
        self.hold(1, 2)
        self.assertEqual(self.actions, [])
        self.runtime.resume()
        self.hold(4, .7)
        self.assertEqual(len(self.actions), 1)
        self.state.set_action_settings(self.state.active_profile_id, "Большой палец вверх", enabled=False)
        self.hold(6, 2)
        self.assertEqual(len(self.actions), 1)

    def test_invalid_hand_and_camera_error_cannot_execute(self):
        self.runtime.set_enabled(True)
        self.hold(1, 2, ready=False)
        self.assertEqual(self.actions, [])
        self.camera.error.emit("Камера не найдена")
        self.assertFalse(self.runtime.enabled)
        self.hold(5, 3)
        self.assertEqual(self.actions, [])

    def test_per_profile_timing_is_used(self):
        self.state.set_action_settings(self.state.active_profile_id, "Большой палец вверх", hold_time=1.5)
        self.runtime.set_enabled(True)
        self.hold(1, .8)
        self.assertEqual(self.actions, [])
        self.hold(1.85, .75)
        self.assertEqual(len(self.actions), 1)

    def test_conflicting_pinch_bindings_do_not_block_static_volume(self):
        from copy import deepcopy
        pinch = deepcopy(self.state.gestures[-1])
        pinch.update(id="another-pinch", key="another-pinch", name="Другой pinch")
        self.state.gestures.append(pinch)
        pid = self.state.active_profile_id
        self.state.set_assignment(pid, "Pinch — регулировка", "Регулировка громкости")
        self.state.set_assignment(pid, "Другой pinch", "Масштабирование")
        self.state.set_assignment(pid, "Большой палец вверх", "Громкость +")
        self.runtime.set_enabled(True)
        self.hold(1, 1)
        self.assertEqual(len(self.actions), 1)
        self.assertIn("Громкость +", self.actions[0])

    def test_disabled_dynamic_match_does_not_hide_static_assignment(self):
        pid = self.state.active_profile_id
        self.state.set_action_settings(pid, "Два пальца", enabled=False)
        self.runtime.set_enabled(True)
        for index in range(21):
            self.camera.frame_ready.emit({
                "timestamp": 1 + index / 20, "hand": {"ready": True, "motion_ready": True},
                "gesture": {"name": "Большой палец вверх", "key": "thumbs_up", "confidence": .99},
                "dynamic_gestures": [{"name": "Два пальца", "key": "two_fingers",
                                      "confidence": .99, "duration": 1, "recognition_type": "dynamic"}]})
        self.assertEqual(len(self.actions), 1)
        self.assertIn("Play / Pause", self.actions[0])

    def test_paused_reason_is_logged_once_per_transition(self):
        with self.assertLogs("Actions", level="INFO") as logs:
            self.hold(1, 1)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Управление выключено", logs.output[0])

    def test_database_gesture_name_is_resolved_by_key(self):
        snapshot = self.state.snapshot()
        original, renamed = "Большой палец вверх", "Палец вверх"
        gesture = next(g for g in snapshot["gestures"] if g["key"] == "thumbs_up")
        gesture["name"] = renamed
        pid = snapshot["active_profile_id"]
        snapshot["assignments"][pid][renamed] = snapshot["assignments"][pid].pop(original)
        snapshot["action_settings"][pid][renamed] = {"hold_time": 0}
        self.state._apply_snapshot(snapshot)
        self.state.changed.emit()
        self.runtime.set_enabled(True)
        # Распознаватель возвращает встроенное название, БД — пользовательское.
        self.frame(1, name=original, key="thumbs_up")
        self.assertEqual(len(self.actions), 1)
        self.assertEqual(self.runtime.last_gesture, renamed)

    def test_unknown_key_cannot_execute_binding_with_same_name(self):
        self.runtime.set_enabled(True)
        self.hold(1, 1, key="unknown_pose")
        self.assertEqual(self.actions, [])

    def test_low_confidence_diagnostic_includes_actual_threshold(self):
        self.state.set_action_settings(self.state.active_profile_id, "Большой палец вверх", sensitivity=1.)
        self.runtime.set_enabled(True)
        with self.assertLogs("Actions", level="INFO") as logs:
            self.hold(1, 1)
        self.assertIn("confidence=0.99; threshold=1.00", "\n".join(logs.output))
        self.assertEqual(self.actions, [])

    def test_unchanged_state_does_not_reconfigure_camera(self):
        from unittest.mock import patch
        with patch.object(self.camera, "configure") as configure:
            self.state.changed.emit()
        configure.assert_not_called()

    def test_assignment_change_preserves_camera_history_but_settings_propagate(self):
        from unittest.mock import patch
        with patch.object(self.camera, "configure") as configure:
            self.state.set_assignment(self.state.active_profile_id, "Большой палец вверх", "Громкость +")
            configure.assert_not_called()
            self.state.save_settings(mirror=False)
            configure.assert_called_once()
            self.assertFalse(configure.call_args.args[0]["mirror"])

    def test_dynamic_binding_uses_key_after_display_name_change(self):
        # Проверяем ту же привязку для последовательности движения.
        gesture = self.state.gestures[1]
        self.runtime.set_enabled(True)
        self.camera.frame_ready.emit({"timestamp": 1, "hand": {"motion_ready": True},
                                      "dynamic_gestures": [{"name": "Другое название", "key": gesture["key"],
                                                            "confidence": .99, "duration": 1,
                                                            "recognition_type": "dynamic"}]})
        self.assertEqual(len(self.actions), 1)
        self.assertIn("Следующий трек", self.actions[0])


if __name__ == "__main__":
    unittest.main()
