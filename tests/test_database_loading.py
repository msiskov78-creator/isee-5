"""Настоящий SDK и Qt; HTTP отвечает в формате существующей схемы Supabase."""

import base64
from copy import deepcopy
import json
import os
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
from supabase import ClientOptions, create_client
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app_state import AppState
from database.repository import SupabaseRepository, RepositoryError
from supabase_client import AuthService
from ui.login_window import LoginWindow
from ui.main_window import MainWindow
from ui.pages.settings_page import SettingsPage
from ui.action_settings_dialog import ActionSettingsDialog
from actions.action_executor import GestureGate
from test_camera_service import FakeCapture, PoseDetector
from test_recognition import pose
from hand_tracking.hand_detector import empty_hand


class SchemaServer:
    """Имена, типы id и шкала чувствительности соответствуют схеме пользователя."""
    def __init__(self):
        self.uid, self.pid, self.gid = str(uuid4()), 11, 21
        self.requests = []
        self.failures = {}
        self.rpc_error = {"code": "PGRST202", "message": "Could not find the function public.gc_load_workspace without parameters in the schema cache",
                          "details": "No matches were found in the schema cache.", "hint": None}
        self.user = {"id": self.uid, "aud": "authenticated", "email": "student@gesturecontrol.local",
                     "app_metadata": {}, "user_metadata": {"username": "student"}, "created_at": "2026-01-01T00:00:00Z"}
        claims = base64.urlsafe_b64encode(json.dumps({"sub": self.uid, "exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
        self.token = "header." + claims + ".signature"
        self.tables = {
            "profiles": [{"id": self.uid, "username": "student"}],
            "control_profiles": [{"id": self.pid, "user_id": self.uid, "name": "Серверный профиль", "description": "", "is_active": True}],
            "gestures": [{"id": self.gid, "user_id": self.uid, "name": "Большой палец вверх", "gesture_key": "thumbs_up",
                          "gesture_type": "standard", "gesture_data": {}}],
            "actions": [{"id": 31, "user_id": self.uid, "profile_id": self.pid, "gesture_id": self.gid,
                         "action_type": "play_pause", "action_value": "", "enabled": True, "hold_time": .6, "cooldown": 1.2, "sensitivity": .7}],
            "user_settings": [{"user_id": self.uid, "camera_index": 2, "sensitivity": .7, "hold_time": .6, "cooldown": 1.2,
                               "control_enabled": False, "mirror_camera": False, "show_landmarks": True, "auto_start_recognition": False, "onboarding_completed": True}],
        }
        self.columns = {table: set(rows[0]) for table, rows in self.tables.items()}

    def respond(self, request):
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path == "/auth/v1/token":
            return httpx.Response(200, json={"user": self.user, "access_token": self.token, "refresh_token": "fixture-refresh",
                                           "expires_in": 3600, "token_type": "bearer"})
        if path == "/auth/v1/user":
            return httpx.Response(200, json=self.user)
        if path == "/auth/v1/logout":
            return httpx.Response(204)
        if path == "/rest/v1/rpc/gc_load_workspace":
            return httpx.Response(404, json=self.rpc_error)
        table = path.rsplit("/", 1)[-1]
        if table not in self.tables:
            return httpx.Response(404, json={"code": "PGRST205", "message": "Unknown table " + table})
        if (method, table) in self.failures:
            return httpx.Response(403, json=self.failures[(method, table)])
        if request.headers.get("authorization") != "Bearer " + self.token:
            return httpx.Response(403, json={"code": "42501", "message": "Missing authenticated session"})
        filters = {key: value[3:] for key, value in request.url.params.multi_items() if value.startswith("eq.")}
        selected = [row for row in self.tables[table] if all(str(row.get(key)) == value for key, value in filters.items())]
        if method == "GET":
            return httpx.Response(200, json=selected)
        payload = json.loads(request.content) if request.content else None
        if method in ("POST", "PATCH"):
            values = payload if isinstance(payload, list) else [payload]
            for value in values:
                unexpected = set(value) - self.columns[table]
                if unexpected:
                    return httpx.Response(400, json={"code": "42703", "message": "Unknown columns: " + str(unexpected)})
                if value.get("user_id") != self.uid:
                    return httpx.Response(403, json={"code": "42501", "message": "Wrong owner"})
                for key in ("id", "profile_id", "gesture_id"):
                    if key in value and type(value[key]) is not int:
                        return httpx.Response(400, json={"code": "22P02", "message": "Expected bigint: " + key})
                sensitivity = value.get("sensitivity")
                if sensitivity is not None and not 0 <= sensitivity <= 1:
                    return httpx.Response(400, json={"code": "23514", "message": "sensitivity must be normalized"})
            if method == "POST":
                if table in ("control_profiles", "gestures", "actions"):
                    next_id = max((row["id"] for row in self.tables[table]), default=0) + 1
                    for value in values:
                        value.setdefault("id", next_id)
                        next_id += 1
                self.tables[table].extend(deepcopy(values))
                return httpx.Response(201, json=values)
            for row in selected:
                row.update(payload)
            return httpx.Response(200, json=selected)
        if method == "DELETE":
            self.tables[table] = [row for row in self.tables[table] if row not in selected]
            return httpx.Response(200, json=selected)
        return httpx.Response(405)


class DatabaseLoadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.server = SchemaServer()
        self.transport = httpx.Client(transport=httpx.MockTransport(self.server.respond))
        self.client = create_client("https://fixture.supabase.co", "sb_publishable_fixture",
            options=ClientOptions(persist_session=False, auto_refresh_token=False, httpx_client=self.transport))
        self.auth = AuthService(self.client)
        self.repository = SupabaseRepository(self.client, self.server.uid)
        self.errors = []
        self.previous_hook = sys.excepthook
        sys.excepthook = lambda kind, value, tb: self.errors.append(str(value))

    def tearDown(self):
        for window in self.app.topLevelWidgets():
            if isValid(window):
                window.close()
        QTest.qWait(30)
        self.client.auth.close()
        self.transport.close()
        sys.excepthook = self.previous_hook
        self.assertEqual(self.errors, [])

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
            time.sleep(.001)
        self.assertTrue(predicate())

    def login(self):
        return self.auth.sign_in("student", "abc123")

    def test_existing_schema_loads_profile_settings_active_profile_without_rpc(self):
        self.login()
        with self.assertLogs(level="INFO") as logs:
            snapshot = self.repository.load()
        self.assertEqual(snapshot["account_profile"]["id"], self.server.uid)
        self.assertEqual(snapshot["settings"]["camera"], 2)
        self.assertEqual(snapshot["settings"]["command_pause"], 1.2)
        self.assertFalse(snapshot["settings"]["mirror"])
        self.assertEqual(snapshot["active_profile_id"], self.server.pid)
        self.assertEqual(snapshot["assignments"][self.server.pid]["Большой палец вверх"], "Play / Pause")
        self.assertIn("Профиль загружен", " ".join(logs.output))
        self.assertIn("Настройки загружены", " ".join(logs.output))
        self.assertIn("sensitivity DB = 0.7", " ".join(logs.output))
        self.assertIn("sensitivity UI = 70%", " ".join(logs.output))
        self.assertFalse(any("/rpc/" in r.url.path for r in self.server.requests))

    def test_select_failure_keeps_exact_error_and_blocks_overwriting(self):
        self.login()
        self.server.failures[("GET", "user_settings")] = {"code": "42501", "message": "permission denied for table user_settings",
                                                         "details": "diagnostic detail", "hint": "Check authenticated role"}
        state = AppState()
        with self.assertLogs("Database", level="ERROR") as logs:
            state.attach_repository(self.repository)
            self.wait_for(lambda: not state.persistence_busy)
        self.assertIn("diagnostic detail", " ".join(logs.output))
        with self.assertRaisesRegex(ValueError, "permission denied for table user_settings") as error:
            state.add_custom_gesture("Поза", {"template": [0.] * 63})
        self.assertNotIn("migration 002", str(error.exception))
        self.assertFalse(state.can_persist)
        self.assertFalse(any(r.method in ("PATCH", "DELETE") for r in self.server.requests))
        self.server.failures.clear()
        state.load_async()
        self.wait_for(lambda: not state.persistence_busy)
        self.assertTrue(state.can_persist)
        self.assertEqual(state.user_id, self.server.uid)
        self.assertEqual(state.active_profile_name, "Серверный профиль")

    def test_actual_schema_does_not_call_obsolete_rpc(self):
        self.login()
        self.server.rpc_error = {"code": "42703", "message": "column s.camera does not exist", "details": "gc_load_workspace line 7", "hint": None}
        self.repository.load()
        self.assertFalse(any("/rpc/" in r.url.path for r in self.server.requests))
        self.assertTrue(any(r.url.path.endswith("/user_settings") for r in self.server.requests))

    def test_missing_account_row_is_distinct_from_query_error(self):
        self.login()
        self.server.tables["profiles"] = []
        with self.assertLogs("Profile", level="WARNING") as logs:
            snapshot = self.repository.load()
        self.assertIsNone(snapshot["account_profile"])
        self.assertIn("отсутствует или скрыта RLS", " ".join(logs.output))
        self.assertEqual(snapshot["active_profile_id"], self.server.pid)

    def test_settings_rls_failure_identifies_owner_and_does_not_write_other_tables(self):
        self.login()
        self.server.tables["user_settings"] = []
        state = AppState()
        state._apply_snapshot(self.repository.load())
        self.server.failures[("POST", "user_settings")] = {"code":"42501",
            "message":'new row violates row-level security policy for table "user_settings"',
            "details":"policy detail", "hint":None}
        self.server.requests.clear()
        with self.assertLogs("Database",level="ERROR") as logs, self.assertRaises(RepositoryError) as failure:
            self.repository.save(state.snapshot())
        self.assertIn("WITH CHECK",str(failure.exception))
        self.assertIn("policy detail"," ".join(logs.output))
        writes = [r for r in self.server.requests if r.method in ("POST","PATCH","DELETE")]
        self.assertEqual(len(writes),1)
        self.assertTrue(writes[0].url.path.endswith("/user_settings"))
        self.assertEqual(json.loads(writes[0].content)[0]["user_id"],self.server.uid)

    def test_changed_auth_user_cannot_write_old_account(self):
        self.login()
        state=AppState()
        state._apply_snapshot(self.repository.load())
        self.server.user["id"] = str(uuid4())
        self.server.requests.clear()
        with self.assertRaisesRegex(RepositoryError,"Пользователь сессии отличается"):
            self.repository.save(state.snapshot())
        self.assertFalse(any(r.method in ("POST","PATCH","DELETE") for r in self.server.requests))

    def test_database_authorization_is_restored_from_verified_session(self):
        self.login()
        self.client.postgrest.auth("expired-or-anonymous-token")
        self.assertEqual(self.repository.load()["user_id"],self.server.uid)
        requests=[r for r in self.server.requests if r.url.path.endswith("/user_settings")]
        self.assertEqual(requests[-1].headers["authorization"],"Bearer "+self.server.token)

    def test_sensitivity_ui_save_and_new_session_roundtrip(self):
        self.login()
        state = AppState()
        state.attach_repository(self.repository)
        self.wait_for(lambda: not state.persistence_busy)
        page = SettingsPage(state)
        self.assertEqual(state.settings["sensitivity"], .7)
        self.assertEqual(page.sensitivity_slider.value(), 70)
        page.sensitivity_slider.setValue(80)
        page.save_button.click()
        self.wait_for(lambda: not state.persistence_busy)
        self.assertEqual(self.server.tables["user_settings"][0]["sensitivity"], .8)
        self.assertEqual(self.server.tables["user_settings"][0]["hold_time"], .6)
        self.assertEqual(self.server.tables["user_settings"][0]["cooldown"], 1.2)
        self.assertFalse(self.server.tables["user_settings"][0]["control_enabled"])
        restored = AppState()
        restored.attach_repository(SupabaseRepository(self.client, self.server.uid))
        self.wait_for(lambda: not restored.persistence_busy)
        reopened = SettingsPage(restored)
        self.assertEqual(reopened.sensitivity_slider.value(), 80)
        self.assertIn("80%", reopened.sensitivity_value.text())

    def test_live_checkboxes_persist_without_save_button_and_reload(self):
        self.login()
        from camera.camera_service import CameraService
        state = AppState()
        state.attach_repository(self.repository)
        self.wait_for(lambda: not state.persistence_busy)
        camera = CameraService()
        page = SettingsPage(state, camera)
        page.mirror_check.setChecked(True)
        page.landmarks_check.setChecked(False)
        page.auto_start_check.setChecked(True)
        self.assertTrue(camera.mirror_camera)
        self.assertFalse(camera.show_landmarks)
        self.wait_for(lambda: not state.persistence_busy)
        saved = self.server.tables["user_settings"][0]
        self.assertTrue(saved["mirror_camera"])
        self.assertFalse(saved["show_landmarks"])
        self.assertTrue(saved["auto_start_recognition"])
        restored = AppState()
        restored._apply_snapshot(SupabaseRepository(self.client,self.server.uid).load())
        reopened = SettingsPage(restored)
        self.assertTrue(reopened.mirror_check.isChecked())
        self.assertFalse(reopened.landmarks_check.isChecked())
        self.assertTrue(reopened.auto_start_check.isChecked())
        page.mirror_check.setChecked(False)
        page.auto_start_check.setChecked(False)
        self.wait_for(lambda: not state.persistence_busy)
        self.assertFalse(saved["mirror_camera"])
        self.assertFalse(saved["auto_start_recognition"])

    def test_dynamic_gesture_metadata_and_assignment_roundtrip(self):
        self.login()
        self.server.columns["gestures"].add("recognition_type")
        self.server.tables["gestures"][0]["recognition_type"] = "static"
        state = AppState()
        state._apply_snapshot(self.repository.load())
        data = {"recognition_type":"dynamic", "dynamic_type":"trajectory", "version":2,
                "samples":[{"frames":[[i/30,0,1,.4] for i in range(30)]} for _ in range(5)]}
        state.add_custom_gesture("Вправо",data)
        state.set_assignment(state.active_profile_id,"Вправо","Следующий слайд")
        self.repository.save(state.snapshot())
        row = next(g for g in self.server.tables["gestures"] if g["name"]=="Вправо")
        self.assertEqual(row["recognition_type"],"dynamic")
        self.assertEqual(row["gesture_type"],"custom")
        restored = AppState()
        restored._apply_snapshot(self.repository.load())
        self.assertEqual(next(g for g in restored.gestures if g["name"]=="Вправо")["gesture_data"],data)
        self.assertEqual(restored.assignments[restored.active_profile_id]["Вправо"],"Следующий слайд")

    def test_action_nullable_settings_and_override_use_normalized_threshold(self):
        self.login()
        action = self.server.tables["actions"][0]
        action.update(sensitivity=None, hold_time=None, cooldown=None)
        state = AppState()
        state._apply_snapshot(self.repository.load())
        name = "Большой палец вверх"
        effective = state.get_action_settings(self.server.pid, name)
        self.assertEqual((effective["sensitivity"], effective["hold_time"], effective["cooldown"]), (.7, .6, 1.2))
        for confidence, expected in ((.69, False), (.71, True)):
            gate = GestureGate()
            fired = [gate.update("thumbs_up", confidence, effective, now=i / 10) for i in range(8)]
            self.assertEqual(any(fired), expected)
        dialog = ActionSettingsDialog(state, self.server.pid, name)
        self.assertEqual(dialog.inputs["sensitivity"].value(), 70)
        dialog.inherit["sensitivity"].setChecked(False)
        dialog.inputs["sensitivity"].setValue(85)
        dialog.save()
        self.repository.save(state.snapshot())
        self.assertEqual(action["sensitivity"], .85)
        self.assertIsNone(action["hold_time"])
        self.assertIsNone(action["cooldown"])
        restored = AppState()
        restored._apply_snapshot(self.repository.load())
        self.assertEqual(restored.get_action_settings(self.server.pid, name)["sensitivity"], .85)
        restored.set_action_settings(self.server.pid, name, sensitivity=None)
        self.repository.save(restored.snapshot())
        self.assertIsNone(action["sensitivity"])

    def test_invalid_database_sensitivity_blocks_loading_without_migration_advice(self):
        self.login()
        self.server.tables["user_settings"][0]["sensitivity"] = 70
        state = AppState()
        with self.assertLogs("Settings", level="ERROR") as logs:
            state.attach_repository(self.repository)
            self.wait_for(lambda: not state.persistence_busy)
        self.assertFalse(state.can_persist)
        self.assertIn("user_settings.sensitivity DB", " ".join(logs.output))
        self.assertIn("70", state._load_error)
        self.assertNotIn("migration", state._load_error)
        self.assertFalse(any(r.method in ("PATCH", "DELETE") for r in self.server.requests))

    def test_direct_save_retry_hotkey_and_reload_do_not_duplicate_rows(self):
        self.login()
        state = AppState()
        state._apply_snapshot(self.repository.load())
        custom_id = state.add_custom_gesture("Тестовая поза", {"template": [.1] * 63})
        state.set_action_settings(state.active_profile_id, "Тестовая поза", action="Своя комбинация клавиш", action_value="Ctrl+P")
        self.server.failures[("POST", "actions")] = {"code": "23514", "message": "fixture interrupted save", "details": "actions insert", "hint": None}
        with self.assertLogs("Database", level="ERROR"), self.assertRaisesRegex(RepositoryError, "fixture interrupted save"):
            self.repository.save(state.snapshot())
        self.server.failures.clear()
        self.repository.save(state.snapshot())
        self.repository.save(state.snapshot())
        saved = [g for g in self.server.tables["gestures"] if g["gesture_key"] == "custom_" + custom_id]
        self.assertEqual(len(saved), 1)
        custom_id = saved[0]["id"]
        self.assertIs(type(custom_id), int)
        binding = [a for a in self.server.tables["actions"] if a["gesture_id"] == custom_id]
        self.assertEqual(len(binding), 1)
        self.assertEqual(binding[0]["action_type"], "hotkey")
        self.assertEqual(binding[0]["action_value"], "Ctrl+P")
        restored = self.repository.load()
        self.assertEqual(restored["action_settings"][self.server.pid]["Тестовая поза"]["action_value"], "Ctrl+P")
        state.set_assignment(state.active_profile_id, "Тестовая поза", "Нет действия")
        self.repository.save(state.snapshot())
        self.assertFalse(any(a["gesture_id"] == custom_id for a in self.server.tables["actions"]))

    def test_login_mainwindow_gestures_add_gesture(self):
        self.server.tables["user_settings"][0]["auto_start_recognition"] = True
        FakeCapture.active = FakeCapture.maximum = 0
        FakeCapture.opened, FakeCapture.threads = [], []
        PoseDetector.hand = pose("custom")
        # Реальные окна, SDK, сервис, поток, запись и распознаватель; подменяем HTTP и устройство.
        with patch("cv2.VideoCapture", FakeCapture), patch("camera.camera_worker.HandDetector", PoseDetector):
            login = LoginWindow(self.auth)
            self.app.current_window = login
            login.show()
            login.username_input.setText("student")
            # Шестой символ запускает настоящий AuthService/get_user через HTTP SDK.
            for index, character in enumerate("abc123"):
                QTest.keyClicks(login.password_boxes.boxes[index], character)
            self.wait_for(lambda: isinstance(self.app.current_window, MainWindow), timeout=13)
            window = self.app.current_window
            camera = window.camera_service
            self.wait_for(lambda: window._data_loaded and not window.state.persistence_busy)
            self.assertEqual(window.user_id, self.server.uid)
            self.assertEqual(window.state.account_profile["id"], self.server.uid)
            self.assertEqual(window.state.active_profile_id, self.server.pid)
            self.wait_for(lambda: camera.last_packet is not None)
            self.assertEqual(FakeCapture.opened, [2])
            self.assertEqual(window.pages["settings"].sensitivity_slider.value(), 70)
            window.show_page("gestures")
            page = window.pages["gestures"]
            self.assertIs(page.state, window.state)
            page.add_button.click()
            self.assertIsNotNone(page._wizard)
            page._wizard.choose_type("static")
            page._wizard.name_input.setText("Проверка загрузки")
            page._wizard._next()
            self.assertEqual(page._wizard.step, 1)
            self.assertIs(page._wizard.camera_service, camera)
            self.assertTrue(any(r.url.path == "/auth/v1/user" for r in self.server.requests))
            wizard = page._wizard
            for example in range(5):
                PoseDetector.hand = pose("custom")
                self.wait_for(lambda: len(wizard.recorder.examples) == example + 1, timeout=4)
                if example < 4:
                    PoseDetector.hand = empty_hand()
                    self.wait_for(lambda: not wizard.recorder.wait_release)
            self.wait_for(lambda: wizard.step == 2)
            self.assertIs(window.pages["home"].preview.last_packet, wizard.preview.last_packet)
            samples = wizard.recorded_data["samples"]
            self.assertEqual(len(samples), 5)
            self.assertTrue(all(len(sample) == 63 and sample[:3] == [0., 0., 0.] for sample in samples))
            PoseDetector.hand = empty_hand()
            self.wait_for(lambda: wizard._verify_released)
            PoseDetector.hand = pose("custom")
            self.wait_for(lambda: wizard._verified)
            wizard._save()
            self.wait_for(lambda: page._wizard is None and not window.state.persistence_busy)
            saved = next(g for g in self.server.tables["gestures"] if g["name"] == "Проверка загрузки")
            self.assertEqual(saved["gesture_type"], "custom")
            self.assertEqual(saved["gesture_data"]["samples"], samples)
            self.assertIs(type(saved["id"]), int)
            self.assertEqual(FakeCapture.opened, [2])
            self.assertEqual(FakeCapture.maximum, 1)
            window.logout()
            self.wait_for(lambda: isinstance(self.app.current_window, LoginWindow))
            self.assertEqual(FakeCapture.active, 0)
            self.assertTrue(any(r.url.path == "/auth/v1/logout" for r in self.server.requests))
            self.wait_for(lambda: not isValid(window))

    def test_profile_switch_delete_and_settings_keep_other_users_untouched(self):
        self.login()
        foreign = {"id": 999, "user_id": str(uuid4()), "name": "Другой аккаунт", "description": "", "is_active": True}
        self.server.tables["control_profiles"].append(deepcopy(foreign))
        state = AppState()
        state._apply_snapshot(self.repository.load())
        old = state.active_profile_id
        new = state.add_profile("Новый профиль")
        state.set_active_profile(new)
        state.save_settings(camera=1, mirror=True, command_pause=2.)
        self.repository.save(state.snapshot())
        restored = self.repository.load()
        saved_new = next(p["id"] for p in restored["profiles"] if p["name"] == "Новый профиль")
        self.assertEqual(restored["active_profile_id"], saved_new)
        self.assertEqual(restored["settings"]["camera"], 1)
        self.assertEqual(restored["settings"]["command_pause"], 2.)
        state.delete_profile(old)
        self.repository.save(state.snapshot())
        self.assertFalse(any(p["id"] == old for p in self.server.tables["control_profiles"]))
        self.assertIn(foreign, self.server.tables["control_profiles"])
        for request in self.server.requests:
            if request.method in ("PATCH", "DELETE"):
                self.assertEqual(request.url.params["user_id"], "eq." + self.server.uid)


if __name__ == "__main__":
    unittest.main()
