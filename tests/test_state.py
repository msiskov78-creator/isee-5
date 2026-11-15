"""Целостность профилей, назначений и настроек без сети и камеры."""

from copy import deepcopy
import unittest
from uuid import UUID

from app_state import ACTIONS, GESTURES, DEFAULT_SETTINGS, AppState


class AppStateTests(unittest.TestCase):
    def setUp(self):
        self.state = AppState()
        self.notifications = []
        self.state.changed.connect(lambda: self.notifications.append(True))

    def snapshot(self):
        return deepcopy((
            self.state.profiles,
            self.state.active_profile_id,
            self.state.assignments,
            self.state.settings,
        ))

    def assert_rejected_without_change(self, operation):
        # Ошибка не должна частично менять данные или уведомлять страницы.
        before = self.snapshot()
        notification_count = len(self.notifications)
        with self.assertRaises(ValueError):
            operation()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.notifications), notification_count)

    def test_default_profiles_have_valid_independent_assignments(self):
        self.assertEqual([p["name"] for p in self.state.profiles], ["Музыка", "Презентация", "Видео"])
        self.assertEqual(self.state.active_profile_name, "Музыка")
        ids = [p["id"] for p in self.state.profiles]
        self.assertEqual(len(set(ids)), 3)
        for profile_id in ids:
            self.assertEqual(str(UUID(profile_id)), profile_id)
            self.assertEqual(set(self.state.assignments[profile_id]), {g["name"] for g in self.state.gestures})
            self.assertTrue(set(self.state.assignments[profile_id].values()) <= set(ACTIONS))
        self.assertEqual(set(self.state.assignments), set(ids))

    def test_create_and_rename_preserve_identity_and_assignments(self):
        original_active = self.state.active_profile_id
        profile_id = self.state.add_profile("  Работа  ")
        self.assertEqual(self.state.profiles[-1], {"id": profile_id, "name": "Работа", "description": ""})
        self.assertEqual(self.state.active_profile_id, original_active)
        self.assertEqual(set(self.state.assignments[profile_id].values()), {"Нет действия"})
        self.state.set_assignment(profile_id, "Два пальца", "Следующий слайд")
        self.state.set_active_profile(profile_id)
        self.state.rename_profile(profile_id, "Учёба")
        self.assertEqual(self.state.active_profile_id, profile_id)
        self.assertEqual(self.state.active_profile_name, "Учёба")
        self.assertEqual(self.state.assignments[profile_id]["Два пальца"], "Следующий слайд")
        self.assertEqual(len(self.notifications), 4)

    def test_invalid_names_do_not_mutate_existing_state(self):
        profile_id = self.state.profiles[1]["id"]
        for name in ("", "   ", "x" * 33, None, 42, [], " МУЗЫКА "):
            with self.subTest(name=name):
                self.assert_rejected_without_change(lambda: self.state.add_profile(name))
                self.assert_rejected_without_change(lambda: self.state.rename_profile(profile_id, name))
        # Максимальная длина допустима; собственное имя не является дубликатом.
        self.state.rename_profile(profile_id, "x" * 32)
        self.state.rename_profile(profile_id, "X" * 32)
        self.assertEqual(self.state.profiles[1]["name"], "X" * 32)

    def test_unknown_profiles_cannot_be_changed(self):
        for operation in (
            lambda: self.state.rename_profile("missing", "Работа"),
            lambda: self.state.delete_profile("missing"),
            lambda: self.state.set_active_profile("missing"),
            lambda: self.state.set_assignment("missing", GESTURES[0], ACTIONS[0]),
        ):
            with self.subTest(operation=operation):
                self.assert_rejected_without_change(operation)

    def test_deleting_inactive_profile_preserves_active_selection(self):
        active_id = self.state.active_profile_id
        removed_id = self.state.profiles[-1]["id"]
        self.state.delete_profile(removed_id)
        self.assertEqual(self.state.active_profile_id, active_id)
        self.assertNotIn(removed_id, self.state.assignments)
        self.assertEqual({p["id"] for p in self.state.profiles}, set(self.state.assignments))
        self.assertEqual(len(self.notifications), 1)

    def test_deleting_active_profile_selects_remaining_and_keeps_last(self):
        removed_id = self.state.active_profile_id
        self.state.delete_profile(removed_id)
        self.assertNotEqual(self.state.active_profile_id, removed_id)
        self.assertIn(self.state.active_profile_id, self.state.assignments)
        self.assertEqual(self.state.active_profile_name, "Презентация")
        self.state.delete_profile(self.state.active_profile_id)
        self.assertEqual(len(self.state.profiles), 1)
        self.assertEqual(self.state.active_profile_name, "Видео")
        self.assert_rejected_without_change(lambda: self.state.delete_profile(self.state.active_profile_id))

    def test_assignment_changes_are_isolated_between_profiles(self):
        first_id, second_id = [p["id"] for p in self.state.profiles[:2]]
        second_before = self.state.assignments[second_id].copy()
        self.state.set_assignment(first_id, GESTURES[0], "Выключить звук")
        self.assertEqual(self.state.assignments[first_id][GESTURES[0]], "Выключить звук")
        self.assertEqual(self.state.assignments[second_id], second_before)
        self.assertEqual(len(self.notifications), 1)
        for gesture, action in (("Неизвестный жест", ACTIONS[0]), (GESTURES[0], "Выполнить код"), (None, None)):
            with self.subTest(gesture=gesture, action=action):
                self.assert_rejected_without_change(lambda: self.state.set_assignment(first_id, gesture, action))

    def test_settings_defaults_and_inclusive_boundaries(self):
        self.assertEqual(self.state.settings, DEFAULT_SETTINGS)
        for sensitivity, hold_time, command_pause in ((0, 0.1, 0.1), (1.0, 3.0, 5.0), (.7, 1, 2)):
            with self.subTest(sensitivity=sensitivity):
                self.state.save_settings(0, sensitivity, hold_time, command_pause)
                self.assertEqual(self.state.settings, {
                    **DEFAULT_SETTINGS,
                    "camera": 0,
                    "sensitivity": sensitivity,
                    "hold_time": hold_time,
                    "command_pause": command_pause,
                })
        self.assertEqual(len(self.notifications), 3)

    def test_invalid_settings_values_never_partially_save(self):
        # Список включает обход ограничений виджетов прямым вызовом модели.
        invalid_values = {
            "camera": (-1, 16, False, True, 0.0, "0", None, []),
            "sensitivity": (-1, 1.01, 70, True, "0.7", None, [], float("nan"), float("inf")),
            "hold_time": (-1, True, "0.5", None, [], float("nan"), float("inf"), float("-inf")),
            "command_pause": (-1, True, "1.0", None, [], float("nan"), float("inf"), float("-inf")),
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    settings = {"camera": 0, "sensitivity": .8, "hold_time": 1.5, "command_pause": 2.0}
                    settings[field] = value
                    self.assert_rejected_without_change(lambda: self.state.save_settings(**settings))

    def test_new_session_does_not_share_user_settings_or_profiles(self):
        profile_id = self.state.add_profile("Только этот сеанс")
        self.state.set_active_profile(profile_id)
        self.state.set_assignment(profile_id, GESTURES[0], "Play / Pause")
        self.state.save_settings(0, .05, 2.5, 4.5)
        other_session = AppState()
        self.assertEqual(len(other_session.profiles), 3)
        self.assertEqual(other_session.active_profile_name, "Музыка")
        self.assertNotIn(profile_id, other_session.assignments)
        self.assertEqual(other_session.settings, DEFAULT_SETTINGS)


if __name__ == "__main__":
    unittest.main()
