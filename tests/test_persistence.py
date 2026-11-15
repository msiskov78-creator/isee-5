"""Проверяем очередь сохранения, восстановление сеанса и отсутствие записи после ошибки загрузки."""

import os
import threading
import time
from copy import deepcopy
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app_state import AppState
from database.repository import RepositoryError, SupabaseRepository


class RepositoryDouble:
    def __init__(self, snapshot=None):
        self.data=deepcopy(snapshot or {})
        self.saved=[]
        self.failure=False
        self.gate=threading.Event()
        self.gate.set()
    def load(self):
        if self.failure: raise RepositoryError("Нет соединения")
        return deepcopy(self.data)
    def save(self, snapshot):
        if not self.gate.wait(3): raise RepositoryError("Тестовая задержка")
        if self.failure: raise RepositoryError("Нет соединения")
        self.data=deepcopy(snapshot)
        self.saved.append(deepcopy(snapshot))


class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def wait_idle(self,state):
        deadline=time.monotonic()+4
        while state.persistence_busy and time.monotonic()<deadline: QTest.qWait(10)
        self.assertFalse(state.persistence_busy)

    def test_reload_profiles_custom_gesture_and_per_profile_action_settings(self):
        repository=RepositoryDouble()
        state=AppState()
        state.attach_repository(repository)
        self.wait_idle(state)
        profile=state.add_profile("Игры","Управление играми")
        state.set_active_profile(profile)
        state.add_custom_gesture("Своя поза",{"template":[0.]*63,"samples":[[0.]*63]})
        state.set_action_settings(profile,"Своя поза",action="Следующий слайд",hold_time=.8,cooldown=2.,sensitivity=.83)
        state.save_settings(camera=1,mirror=False,show_landmarks=False,auto_start=True,onboarding_completed=True)
        duplicate=state.duplicate_profile(profile)
        state.set_assignment(duplicate,"Своя поза","Play / Pause")
        self.wait_idle(state)
        restored=AppState()
        restored.attach_repository(repository)
        self.wait_idle(restored)
        self.assertEqual(restored.snapshot(),state.snapshot())
        self.assertEqual(restored.assignments[profile]["Своя поза"],"Следующий слайд")
        self.assertEqual(restored.assignments[duplicate]["Своя поза"],"Play / Pause")
        self.assertEqual(restored.get_action_settings(profile,"Своя поза")["hold_time"],.8)
        self.assertTrue(restored.settings["onboarding_completed"])

    def test_load_failure_blocks_overwriting_remote_and_retry_works(self):
        repository=RepositoryDouble()
        repository.failure=True
        state=AppState()
        state.attach_repository(repository)
        self.wait_idle(state)
        with self.assertRaises(ValueError): state.add_profile("Не сохранять")
        self.assertEqual(repository.saved,[])
        repository.failure=False
        state.load_async()
        self.wait_idle(state)
        self.assertTrue(state.can_persist)

    def test_failed_save_stays_dirty_and_can_retry(self):
        repository=RepositoryDouble()
        state=AppState()
        state.attach_repository(repository)
        self.wait_idle(state)
        repository.failure=True
        state.save_settings(camera=2)
        self.wait_idle(state)
        self.assertTrue(state.has_unsaved_changes)
        self.assertEqual(repository.data["settings"]["camera"],0)
        repository.failure=False
        state.flush_async()
        self.wait_idle(state)
        self.assertFalse(state.has_unsaved_changes)
        self.assertEqual(repository.data["settings"]["camera"],2)

    def test_pending_changes_are_coalesced_without_blocking_ui(self):
        repository=RepositoryDouble()
        state=AppState()
        state.attach_repository(repository)
        self.wait_idle(state)
        count=len(repository.saved)
        repository.gate.clear()
        try:
            state.save_settings(sensitivity=.71)
            state.save_settings(sensitivity=.72)
            state.save_settings(sensitivity=.73)
            self.assertTrue(state.persistence_busy)
            QTest.qWait(40)
            self.assertEqual(len(repository.saved),count)
        finally:
            repository.gate.set()
            self.wait_idle(state)
        self.assertEqual(len(repository.saved),count+2)
        self.assertEqual(repository.data["settings"]["sensitivity"],.73)

    def test_malformed_loaded_data_leaves_state_unchanged(self):
        state=AppState()
        before=state.snapshot()
        bad=deepcopy(before)
        bad["profiles"][0]["name"]="Не применять"
        bad["action_settings"][state.active_profile_id]={"Кулак":{"hold_time":float("nan")}}
        with self.assertRaises(ValueError): state._apply_snapshot(bad)
        self.assertEqual(state.snapshot(),before)

    def test_existing_gestures_survive_first_profile_creation(self):
        repository=RepositoryDouble({"profiles":[],"gestures":[{"id":"custom-id","key":"custom-key","name":"Ранее созданный","is_custom":True,"gesture_data":{"template":[0.]*63}}]})
        state=AppState()
        state.attach_repository(repository)
        self.wait_idle(state)
        self.assertIn("Ранее созданный",[g["name"] for g in repository.data["gestures"]])


if __name__ == "__main__": unittest.main()
