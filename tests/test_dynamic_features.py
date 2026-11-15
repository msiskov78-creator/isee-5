"""Геометрия и действия проверяются без физической камеры и реальных клавиш."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
from math import dist
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from actions.action_executor import ActionExecutor, GestureGate
from app_state import AppState
from control_runtime import ControlRuntime
from gesture_control.dynamic_gesture_detector import (DynamicGestureDetector, PinchControl, pinch_distance,
    pinch_to_volume, normalize_trajectory, trajectory_similarity)
from gesture_control.gesture_detector import GestureDetector, normalize_landmarks
from gesture_control.gesture_recorder import MultiStaticRecorder
from gesture_control.dynamic_gesture_recorder import DynamicGestureRecorder
from test_control_runtime import FakeCamera
from test_recognition import pose
from test_wizards import StateDouble, CameraDouble
from ui.gesture_wizard import GestureWizard


def pinch_hand(ratio):
    hand = deepcopy(pose("open_palm"))
    points = hand["landmarks"]
    scale = dist(points[0], points[9])
    points[4] = [points[8][0] + ratio * scale, points[8][1], points[8][2]]
    hand.update(ready=True, motion_ready=True, confidence=.99)
    return hand


def moving_hand(offset):
    hand = deepcopy(pose("custom"))
    for point in hand["landmarks"]:
        point[0] += offset
    hand.update(ready=False, motion_ready=True, confidence=.99)
    return hand


class DynamicFeaturesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)

    def test_normalized_pinch_scale_and_mapping(self):
        original = pinch_hand(.6)["landmarks"]
        transformed = [[x*2+.3,y*2-.2,z*2] for x,y,z in original]
        self.assertAlmostEqual(pinch_distance(original), pinch_distance(transformed))
        self.assertEqual(pinch_to_volume(.1), 0)
        self.assertEqual(pinch_to_volume(2), 1)
        self.assertAlmostEqual(pinch_to_volume((.15+1.3)/2), .5)

    def test_five_independent_static_examples_and_best_sample(self):
        recorder = MultiStaticRecorder()
        recorder.start()
        for example in range(5):
            hand = deepcopy(pose("custom"))
            hand["landmarks"][8][2] += .01 * example
            for _ in range(25):
                recorder.add_sample(hand)
            self.assertEqual(len(recorder.examples), example+1)
            for _ in range(30):
                recorder.add_sample(hand)
            self.assertEqual(len(recorder.examples), example+1)
            if example < 4:
                recorder.add_sample({"found": False})
        data = recorder.gesture_data()
        self.assertEqual(len(data["samples"]), 5)
        detector = GestureDetector([{"id": 1,"key":"custom","name":"Поза","gesture_data":data}])
        self.assertEqual(detector.detect(hand)["key"], "custom")
        self.assertEqual(data["samples"][0][:3], [0.,0.,0.])

    def test_trajectory_direction_scale_speed_and_bounded_history(self):
        right = [[i/30, 0, .2, .4] for i in range(30)]
        shifted = [[2+i/60, 3, .1, .4] for i in range(60)]
        left = [[-i/30, 0, .2, .4] for i in range(30)]
        norm = normalize_trajectory(right)
        self.assertGreater(trajectory_similarity(norm, normalize_trajectory(shifted)), .99)
        self.assertLess(trajectory_similarity(norm, normalize_trajectory(left)), .5)
        detector = DynamicGestureDetector()
        for i in range(200):
            detector.update(moving_hand(i/1000), i*.04)
        self.assertEqual(len(detector.history), 40)
        detector.update({"ready":False}, 10.)
        self.assertEqual(len(detector.history), 0)

    def test_pinch_activation_smoothing_threshold_frequency_and_release(self):
        control = PinchControl()
        self.assertIsNone(control.update(pinch_hand(1.), 0.))
        self.assertFalse(control.active)
        updates=[]
        for i in range(200):
            now=i*.04+.04
            value=control.update(pinch_hand(.1 if i<20 else 1.3), now)
            if value is not None:
                updates.append((now,value))
        self.assertTrue(control.active)
        self.assertTrue(all(b[0]-a[0] >= .099 for a,b in zip(updates,updates[1:])))
        self.assertTrue(all(abs(b[1]-a[1]) <= .04001 for a,b in zip(updates,updates[1:])))
        self.assertGreater(updates[-1][1], .95)
        for i in range(12):
            control.update({}, 8.04+i*.04)
        self.assertFalse(control.active)

    def test_windows_action_routing_and_errors(self):
        backend=Mock()
        executor=ActionExecutor(backend=backend)
        for key in ("play_pause","next_track","previous_track","next_slide","previous_slide","volume_up","volume_down","mute"):
            executor.execute(key)
            self.assertTrue(executor.succeeded)
        self.assertEqual(backend.keys.call_count,5)
        executor.execute("hotkey", {"action_value":"ctrl+shift+s"})
        backend.hotkey.assert_called_once_with("Ctrl+Shift+S")
        executor.execute("pinch_volume", {"value":.6})
        backend.set_volume.assert_called_once_with(.6)
        backend.keys.side_effect=RuntimeError("ошибка устройства")
        with self.assertLogs("Actions",level="ERROR"):
            self.assertIn("ошибка устройства",executor.execute("next_slide"))
        self.assertFalse(executor.succeeded)

    def test_native_key_resolution_and_release_after_failure(self):
        from actions.windows_actions import WindowsActions
        from pynput.keyboard import Key
        backend=WindowsActions()
        backend._keyboard=Mock()
        for name in ("media_play_pause","media_next","media_previous","pageup","pagedown","win","f24"):
            backend.keys(name)
        backend._keyboard.reset_mock()
        backend._keyboard.release.side_effect=[RuntimeError("release"),None]
        with self.assertRaises(RuntimeError):
            backend.keys("ctrl","s")
        self.assertEqual(backend._keyboard.release.call_args_list[-1].args,(Key.ctrl,))

    def test_dynamic_preview_and_profile_gesture_verification(self):
        from ui.camera_preview import CameraDialog
        state,camera=AppState(),FakeCamera()
        dialog=CameraDialog(camera,state,target_gesture="Вправо")
        movement={"key":"right","name":"Вправо","confidence":.91}
        packet={"hand":moving_hand(.1),"timestamp":1.,"dynamic_gestures":[movement]}
        camera.frame_ready.emit(packet)
        self.assertEqual(dialog.preview.gesture_label.text(),"Вправо")
        self.assertIn("91%",dialog.verification_status.text())
        dialog.reject()

    def test_runtime_continuous_profile_and_suspension(self):
        state, camera=AppState(),FakeCamera()
        state.set_action_settings(state.active_profile_id,"Pinch — регулировка",action="Регулировка громкости")
        runtime=ControlRuntime(state,camera)
        backend=Mock()
        backend.get_volume.return_value=.5
        runtime.executor=ActionExecutor(backend=backend)
        runtime.set_enabled(True)
        for i in range(80):
            camera.frame_ready.emit({"hand":pinch_hand(.1 if i<20 else 1.3),"timestamp":i*.04,"gesture":{}})
        self.assertGreater(backend.set_volume.call_count,5)
        self.assertIn("Регулировка громкости",runtime.status)
        runtime.suspend()
        before=backend.set_volume.call_count
        for i in range(80,100):
            camera.frame_ready.emit({"hand":pinch_hand(.1),"timestamp":i*.04})
        self.assertEqual(backend.set_volume.call_count,before)
        self.assertFalse(runtime.pinch.active)

    def test_dynamic_wizard_records_five_and_verifies_movement(self):
        state,camera=StateDouble(),CameraDouble()
        wizard=GestureWizard(state,camera)
        self.assertEqual(wizard.step,-1)
        wizard.choose_type("dynamic")
        wizard.name_input.setText("Вправо")
        wizard._next()
        now=0.
        try:
            for example in range(5):
                camera.frame_ready.emit({"hand": moving_hand(0), "timestamp": now})
                self.assertTrue(wizard.next_button.isEnabled())
                wizard.next_button.click()
                for i in range(135):
                    now+=.04
                    hand=moving_hand(max(0,i-75)*.008)
                    camera.frame_ready.emit({"hand":hand,"timestamp":now})
                    if len(wizard.recorder.examples)==example+1:
                        break
                self.assertEqual(len(wizard.recorder.examples),example+1,wizard.hint_label.text())
                now+=.04
                wizard._on_frame({"hand":{"found":False},"timestamp":now})
            self.assertEqual(wizard.step,2)
            self.assertEqual(len(wizard.recorded_data["samples"]),5)
            self.assertEqual(len(wizard.recorded_data["samples"][0]["frames"]),30)
            for i in range(40):
                now+=.04
                wizard._on_frame({"hand":moving_hand(i*.008),"timestamp":now})
            self.assertTrue(wizard._verified)
            wizard._save()
            self.assertEqual(state.added[0][1]["recognition_type"],"dynamic")
            state.save_completed.emit(state.revision)
        finally:
            wizard._save_revision=None
            wizard.reject()

    def test_motion_gate_respects_duration_cooldown_and_release(self):
        gate=GestureGate()
        settings={"hold_time":.5,"cooldown":1.,"sensitivity":.7}
        gesture={"key":"right","duration":1.2,"confidence":.9}
        self.assertTrue(gate.trigger_motion(gesture,settings,1.))
        self.assertFalse(gate.trigger_motion(gesture,settings,3.))
        for i in range(10):
            gate.update(None,0,settings,3.+i*.05)
        self.assertTrue(gate.trigger_motion(gesture,settings,4.))

    def test_interrupted_motion_release_does_not_repeat_action(self):
        gate=GestureGate()
        settings={"hold_time":.5,"cooldown":.1,"sensitivity":.7}
        gesture={"key":"right","duration":1.,"confidence":.9}
        self.assertTrue(gate.trigger_motion(gesture,settings,0.))
        gate.update(None,0,settings,.1)
        self.assertFalse(gate.trigger_motion(gesture,settings,.2))
        gate.update(None,0,settings,.3)
        self.assertFalse(gate.trigger_motion(gesture,settings,.4))

    def test_auto_start_waits_for_button_when_disabled(self):
        from unittest.mock import patch
        from ui.main_window import MainWindow
        for auto_start in (False,True):
            camera=FakeCamera()
            with patch("ui.main_window.CameraService",return_value=camera):
                window=MainWindow(SimpleNamespace(id="demo",user_metadata={}),SimpleNamespace())
                window.state.settings.update(onboarding_completed=True,auto_start=auto_start)
                window.controller.configure()
                window._loaded()
                self.assertEqual(window.controller.enabled,auto_start)
                self.assertEqual(bool(camera.starts),auto_start)
                if not auto_start:
                    window.controller.toggle()
                    self.assertTrue(camera.starts)
                window.close()
                self.app.processEvents()

    def test_zoom_is_thresholded_and_disabled_profile_cannot_send(self):
        state,camera=AppState(),FakeCamera()
        state.set_action_settings(state.active_profile_id,"Pinch — регулировка",action="Масштабирование")
        runtime=ControlRuntime(state,camera)
        backend=Mock()
        runtime.executor=ActionExecutor(backend=backend)
        runtime.set_enabled(True)
        for i in range(120):
            camera.frame_ready.emit({"hand":pinch_hand(.1 if i<20 else 1.3),"timestamp":i*.04})
        self.assertGreater(backend.keys.call_count,0)
        self.assertLess(backend.keys.call_count,10)
        self.assertTrue(all(call.args==("ctrl","+") for call in backend.keys.call_args_list))
        before=backend.keys.call_count
        state.set_active_profile(state.profiles[1]["id"])
        for i in range(120,160):
            camera.frame_ready.emit({"hand":pinch_hand(.1),"timestamp":i*.04})
        self.assertEqual(backend.keys.call_count,before)

    def test_pinch_dynamic_sequence_and_runtime_one_shot(self):
        data={"recognition_type":"dynamic","dynamic_type":"pinch","version":2,
              "samples":[{"frames":[[0,0,1,.1+i*.035] for i in range(30)]} for _ in range(5)]}
        state,camera=AppState(),FakeCamera()
        state.add_custom_gesture("Разведение",data)
        # Камера получает тот же постоянный ключ, который хранится в состоянии.
        detector=DynamicGestureDetector([g for g in state.gestures if g["name"]=="Разведение"])
        detections=[]
        for i in range(30):
            detections += detector.update(pinch_hand(.1+i*.035),i*.04)
        self.assertTrue(detections)
        state.set_assignment(state.active_profile_id,"Разведение","Следующий слайд")
        runtime=ControlRuntime(state,camera)
        backend=Mock()
        runtime.executor=ActionExecutor(backend=backend)
        runtime.set_enabled(True)
        for i in range(40):
            camera.frame_ready.emit({"hand":pinch_hand(.6),"timestamp":i*.04,
                                    "dynamic_gestures":[detections[-1]]})
        backend.keys.assert_called_once_with("right")
