"""Комбинация привязана к профилю и жесту, сохраняется без исполнения Windows."""

import os
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from types import SimpleNamespace
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from actions.action_types import normalize_hotkey
from app_state import AppState
from control_runtime import ControlRuntime
from ui.action_settings_dialog import ActionSettingsDialog
from test_control_runtime import FakeCamera
import test_persistence
from test_persistence import RepositoryDouble
from database.repository import SupabaseRepository, RepositoryError


class HotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app = QApplication.instance() or QApplication([])

    def test_normalization_and_invalid_combinations(self):
        self.assertEqual(normalize_hotkey(" shift + ctrl + p "), "Ctrl+Shift+P")
        self.assertEqual(normalize_hotkey("F12"), "F12")
        for value in ("", "Ctrl", "Ctrl+", "Ctrl+Ctrl+P", "Ctrl+A+B", "run.exe", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_hotkey(value)

    def test_repository_cannot_save_before_successful_load(self):
        uid = str(uuid4())
        client = Mock()
        repository = SupabaseRepository(client, uid)
        hotkey = {"action_settings": {"profile": {"gesture": {"action_value": "Ctrl+P"}}}}
        with self.assertRaises(RepositoryError):
            repository.save(hotkey)
        client.rpc.assert_not_called()
        client.table.assert_not_called()

    def test_profile_isolation_duplicate_and_reload(self):
        state = AppState()
        first, second = [p["id"] for p in state.profiles[:2]]
        state.set_action_settings(first, "Кулак", action="Своя комбинация клавиш", action_value="ctrl+p")
        state.set_action_settings(second, "Кулак", action="Своя комбинация клавиш", action_value="ctrl+shift+p")
        duplicate = state.duplicate_profile(first)
        repository = RepositoryDouble(state.snapshot())
        restored = AppState()
        restored.attach_repository(repository)
        test_persistence.PersistenceTests.wait_idle(self, restored)
        self.assertEqual(restored.get_action_settings(first, "Кулак")["action_value"], "Ctrl+P")
        self.assertEqual(restored.get_action_settings(second, "Кулак")["action_value"], "Ctrl+Shift+P")
        self.assertEqual(restored.get_action_settings(duplicate, "Кулак")["action_value"], "Ctrl+P")
        restored.set_action_settings(first, "Кулак", action_value="Alt+F4", dangerous_confirmed=True)
        test_persistence.PersistenceTests.wait_idle(self, restored)
        self.assertEqual(repository.data["action_settings"][first]["Кулак"]["action_value"], "Alt+F4")

    def test_invalid_hotkey_does_not_mutate_state(self):
        state = AppState()
        before = deepcopy(state.snapshot())
        with self.assertRaises(ValueError):
            state.set_action_settings(state.active_profile_id, "Кулак", action="Своя комбинация клавиш", action_value="")
        self.assertEqual(state.snapshot(), before)

    def test_dialog_saves_value_and_runtime_displays_it(self):
        state = AppState()
        camera = FakeCamera()
        runtime = ControlRuntime(state, camera)
        dialog = ActionSettingsDialog(state, state.active_profile_id, "Кулак")
        dialog.action.setCurrentText("Своя комбинация клавиш")
        dialog.hotkey_input.setText("Ctrl+Shift+P")
        dialog.save()
        runtime.set_enabled(True)
        with patch.object(runtime.executor, "execute", wraps=runtime.executor.execute) as execute:
            for index in range(20):
                camera.frame_ready.emit({"timestamp": index * .05, "hand": {"ready": True},
                    "gesture": {"key": "fist", "name": "Кулак", "confidence": .99}})
            self.assertEqual(execute.call_count, 1)
        self.assertIn("Ctrl+Shift+P", runtime.last_action)
        dialog.reject()


if __name__ == "__main__":
    unittest.main()
