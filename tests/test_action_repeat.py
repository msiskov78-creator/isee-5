"""Повторы, шаг громкости и независимое удаление назначений без физической камеры."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QCoreApplication, QEvent
from actions.action_executor import GestureGate, ActionExecutor
from actions.windows_actions import WindowsActions
from actions.action_settings import action_parameters, execution_mode, ExecutionMode
from app_state import AppState
from ui.action_settings_dialog import ActionSettingsDialog
from test_control_runtime import FakeCamera
from control_runtime import ControlRuntime


class ActionRepeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settings(self, **changes):
        return dict(enabled=True, hold_time=.5, cooldown=1., sensitivity=.7,
                    repeat_while_held=True, repeat_interval=.25, volume_step=3, **changes)

    def test_repeat_interval_ignores_cooldown_and_stops_on_release(self):
        gate, settings = GestureGate(), self.settings()
        fired = [i/20 for i in range(41) if gate.update("up", .99, settings, i/20)]
        self.assertEqual(fired, [.5,.75,1.,1.25,1.5,1.75,2.])
        self.assertFalse(gate.update(None, 0, {}, 2.05))
        for i in range(42,62):
            self.assertFalse(gate.update("up", .99, settings, i/20))
        self.assertIsNone(gate._repeat_key)

    def test_repeat_stops_on_low_quality_change_disabled_and_gap(self):
        for key, confidence, overrides, now in (("other",.99,{},.65), ("up",.1,{},.65),
                                               ("up",.99,{"enabled":False},.65), ("up",.99,{},2.)):
            gate, settings = GestureGate(), self.settings()
            for i in range(13):
                gate.update("up",.99,settings,i*.05)
            self.assertFalse(gate.update(key,confidence,dict(settings,**overrides),now))
            self.assertIsNone(gate._repeat_key)

    def test_one_shot_still_requires_release(self):
        gate = GestureGate()
        settings = dict(self.settings(),repeat_while_held=False)
        fired = sum(gate.update("up",.99,settings,i*.05) for i in range(81))
        self.assertEqual(fired,1)
        for i in range(81,88):
            gate.update(None,0,settings,i*.05)
        self.assertEqual(sum(gate.update("up",.99,settings,i*.05) for i in range(88,110)),1)

    def test_volume_steps_and_clamping(self):
        class Endpoint:
            value = .4
            def GetMasterVolumeLevelScalar(self): return self.value
            def SetMasterVolumeLevelScalar(self,value,_): self.value=value
        endpoint = Endpoint()
        backend = WindowsActions()
        backend._audio = lambda operation: operation(endpoint)
        executor = ActionExecutor(backend=backend)
        for action, step, expected in (("volume_up",5,.45),("volume_up",10,.55),("volume_down",10,.45)):
            executor.execute(action,{"volume_step":step})
            self.assertTrue(executor.succeeded)
            self.assertAlmostEqual(endpoint.value,expected)
        endpoint.value=.98
        executor.execute("volume_up",{"volume_step":25})
        self.assertEqual(endpoint.value,1.)
        endpoint.value=.02
        executor.execute("volume_down",{"volume_step":25})
        self.assertEqual(endpoint.value,0.)

    def test_runtime_delivers_repeat_and_volume_settings(self):
        state, camera = AppState(), FakeCamera()
        runtime = ControlRuntime(state,camera)
        backend = Mock()
        runtime.executor.backend=backend
        state.set_action_settings(state.active_profile_id,"Большой палец вверх", action="Громкость +",
                                  hold_time=.5,cooldown=1.,repeat_while_held=True,repeat_interval=.25,volume_step=3)
        runtime.set_enabled(True)
        for i in range(26):
            camera.frame_ready.emit({"timestamp":i*.05,"hand":{"ready":True,"found":True},
                "gesture":{"key":"thumbs_up","name":"Большой палец вверх","confidence":.99}})
        self.assertEqual(backend.change_volume.call_count,4)
        self.assertTrue(all(call.args==(.03,) for call in backend.change_volume.call_args_list))
        runtime.suspend()
        camera.frame_ready.emit({"timestamp":1.5})
        self.assertEqual(backend.change_volume.call_count,4)

    def test_remove_binding_keeps_library_and_other_profiles(self):
        state=AppState()
        first, second = [p["id"] for p in state.profiles[:2]]
        before=state.assignments[second]["Большой палец вверх"]
        state.remove_gesture_from_profile(first,"Большой палец вверх")
        self.assertNotIn("Большой палец вверх",state.assignments[first])
        self.assertEqual(state.assignments[second]["Большой палец вверх"],before)
        self.assertTrue(any(g["name"]=="Большой палец вверх" for g in state.gestures))
        with self.assertRaises(ValueError): state.delete_custom_gesture("Большой палец вверх")
        state.add_custom_gesture("Мой жест",{"template":[0.]*63})
        for pid in (first,second): state.set_assignment(pid,"Мой жест","Громкость +")
        state.delete_custom_gesture("Мой жест")
        self.assertFalse(any(g["name"]=="Мой жест" for g in state.gestures))
        self.assertTrue(all("Мой жест" not in mapping for mapping in state.assignments.values()))

    def test_ui_roundtrip_and_visibility(self):
        state=AppState();pid=state.active_profile_id
        state.set_action_settings(pid,"Большой палец вверх",action="Громкость +",
                                  repeat_while_held=True,repeat_interval=.25,volume_step=10)
        dialog=ActionSettingsDialog(state,pid,"Большой палец вверх")
        self.assertTrue(dialog.repeat.isChecked())
        self.assertEqual(dialog.repeat_interval.value(),.25)
        self.assertEqual(dialog.volume_step.value(),10)
        dialog.repeat.setChecked(False)
        self.assertTrue(dialog.repeat_interval.isHidden())
        dialog.action.setCurrentText("Play / Pause")
        self.assertTrue(dialog.volume_step.isHidden())
        dialog.save()
        self.assertFalse(state.get_action_settings(pid,"Большой палец вверх")["repeat_while_held"])
        dialog.close()

    def test_null_defaults_and_validation(self):
        self.assertEqual(action_parameters({"volume_step":None})["volume_step"],5)
        for values in ({"volume_step":26},{"volume_step":True},{"repeat_interval":-1},{"repeat_interval":float("nan")}):
            with self.assertRaises(ValueError): action_parameters(values)
        self.assertEqual(execution_mode("pinch_volume",{"repeat_while_held":True}),ExecutionMode.CONTINUOUS)

    def test_repeat_does_not_catch_up_missed_intervals(self):
        gate=GestureGate()
        settings=dict(self.settings(),repeat_interval=.1)
        for i in range(11): gate.update("up",.99,settings,i*.05)
        self.assertTrue(gate.update("up",.99,settings,.79))
        self.assertFalse(gate.update("up",.99,settings,.80))
        self.assertTrue(gate.update("up",.99,settings,.89))

    def test_repeat_motion_uses_confirmed_duration(self):
        gate=GestureGate();settings=self.settings()
        gesture={"key":"move","confidence":.99,"duration":1.}
        self.assertTrue(gate.trigger_motion(gesture,settings,1.))
        self.assertFalse(gate.trigger_motion(gesture,settings,1.1))
        self.assertTrue(gate.trigger_motion(gesture,settings,1.25))
        self.assertFalse(gate.update(None,0,{},1.3))
        self.assertIsNone(gate._repeat_key)

    def test_delete_confirmations_cancel_and_accept(self):
        from ui.pages.profiles_page import ProfilesPage
        from ui.pages.gestures_page import GesturesPage
        from PySide6.QtWidgets import QMessageBox
        state=AppState();pid=state.active_profile_id
        page=ProfilesPage(state)
        def choose(text):
            def click():
                dialog=QApplication.activeModalWidget()
                self.assertIsInstance(dialog,QMessageBox)
                next(button for button in dialog.buttons() if button.text()==text).click()
            QTimer.singleShot(0,click)
        choose("Отмена")
        page.remove_assignment(pid,"Большой палец вверх")
        self.assertIn("Большой палец вверх",state.assignments[pid])
        choose("Удалить")
        page.remove_assignment(pid,"Большой палец вверх")
        self.assertNotIn("Большой палец вверх",state.assignments[pid])
        state.add_custom_gesture("Удаляемый",{"template":[0.]*63})
        library=GesturesPage(state)
        choose("Отмена")
        library.delete_gesture("Удаляемый")
        self.assertTrue(any(g["name"]=="Удаляемый" for g in state.gestures))
        choose("Удалить")
        library.delete_gesture("Удаляемый")
        self.assertFalse(any(g["name"]=="Удаляемый" for g in state.gestures))
        page.close();library.close()
        page.deleteLater();library.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
