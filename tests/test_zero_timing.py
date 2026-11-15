"""Нулевые задержки и отсутствие прежних верхних порогов команд."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
from PySide6.QtWidgets import QApplication
from app_state import AppState
from actions.action_executor import GestureGate

class ZeroTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_global_and_assignment_times_accept_zero_and_large_values(self):
        state=AppState();pid=state.active_profile_id
        for value in (0.,.01,30.,300.):
            state.save_settings(hold_time=value,command_pause=value)
            state.set_action_settings(pid,"Кулак",hold_time=value,cooldown=value,repeat_interval=value)
            restored=AppState();restored._apply_snapshot(state.snapshot())
            self.assertEqual(restored.get_action_settings(pid,"Кулак")["hold_time"],value)

    def test_zero_hold_fires_on_first_ready_frame_and_does_not_repeat(self):
        gate=GestureGate();settings={"hold_time":0.,"cooldown":0.,"sensitivity":.7}
        self.assertTrue(gate.update("fist",.99,settings,0.))
        self.assertFalse(gate.update("fist",.99,settings,.05))
        self.assertEqual(gate.status,"Ожидание отпускания жеста")

    def test_zero_repeat_fires_once_per_received_frame(self):
        gate=GestureGate();settings={"hold_time":0.,"cooldown":0.,"repeat_interval":0.,"repeat_while_held":True}
        self.assertTrue(all(gate.update("fist",.99,settings,i*.04) for i in range(20)))
        self.assertFalse(gate.update(None,0,{},.8))
