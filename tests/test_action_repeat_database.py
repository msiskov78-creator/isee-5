"""Проверяем payload SDK, удаление только нужных строк и восстановление после входа."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
from copy import deepcopy
import httpx
from supabase import create_client, ClientOptions
from PySide6.QtWidgets import QApplication
from app_state import AppState
from actions.action_settings import ACTION_DEFAULTS
from database.repository import SupabaseRepository, RepositoryError
from test_database_loading import SchemaServer


class RepeatDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.server=SchemaServer()
        def respond(request):
            columns=request.url.params.get("select","*")
            if request.url.path.endswith("/actions") and columns != "*":
                if set(columns.split(","))-self.server.columns["actions"]:
                    missing=sorted(set(columns.split(","))-self.server.columns["actions"])[0]
                    return httpx.Response(400,json={"code":"42703","message":f"column actions.{missing} does not exist", "hint":None, "details":None})
            return self.server.respond(request)
        self.transport=httpx.Client(transport=httpx.MockTransport(respond))
        self.client=create_client("https://fixture.supabase.co","sb_publishable_fixture",
            options=ClientOptions(persist_session=False,auto_refresh_token=False,httpx_client=self.transport))
        self.client.auth.sign_in_with_password({"email":"student@gesturecontrol.local","password":"fixture"})
        self.repository=SupabaseRepository(self.client,self.server.uid)
        self.state=AppState()

    def tearDown(self):
        self.client.auth.close()
        self.transport.close()

    def migrated(self):
        self.server.columns["actions"].update(ACTION_DEFAULTS)
        for row in self.server.tables["actions"]:
            row.update({key:None for key in ACTION_DEFAULTS})
        self.state._apply_snapshot(self.repository.load())

    def test_roundtrip_new_fields_and_null_defaults(self):
        self.migrated()
        pid=self.state.active_profile_id
        self.assertEqual(self.state.get_action_settings(pid,"Большой палец вверх")["volume_step"],5)
        self.state.set_action_settings(pid,"Большой палец вверх",action="Громкость +",
            repeat_while_held=True,repeat_interval=.25,volume_step=10)
        self.repository.save(self.state.snapshot())
        new_repository=SupabaseRepository(self.client,self.server.uid)
        restarted=AppState()
        restarted._apply_snapshot(new_repository.load())
        settings=restarted.get_action_settings(pid,"Большой палец вверх")
        for key,value in (("repeat_while_held",True),("repeat_interval",.25),("volume_step",10)):
            self.assertEqual(settings[key],value)
            self.assertEqual(self.server.tables["actions"][0][key],value)

    def test_old_schema_rejects_new_values_before_any_write(self):
        self.state._apply_snapshot(self.repository.load())
        self.state.set_action_settings(self.state.active_profile_id,"Большой палец вверх",volume_step=10)
        before=deepcopy(self.server.tables)
        with self.assertRaisesRegex(RepositoryError,"004_action_repeat_settings.sql"):
            self.repository.save(self.state.snapshot())
        self.assertEqual(self.server.tables,before)

    def test_repeat_migration_does_not_require_scroll_column(self):
        old_fields={"repeat_while_held":False,"repeat_interval":.5,"volume_step":5}
        self.server.columns["actions"].update(old_fields)
        self.server.tables["actions"][0].update(old_fields)
        self.state._apply_snapshot(self.repository.load())
        self.state.set_action_settings(self.state.active_profile_id,"Большой палец вверх",volume_step=10,repeat_while_held=True)
        self.repository.save(self.state.snapshot())
        self.assertEqual(self.server.tables["actions"][0]["volume_step"],10)
        self.state.set_action_settings(self.state.active_profile_id,"Большой палец вверх",action="Прокрутка вниз",scroll_step=7)
        with self.assertRaisesRegex(RepositoryError,"005_more_action_types.sql") as caught:
            self.repository.save(self.state.snapshot())
        self.assertIn("scroll_step",str(caught.exception))
        self.assertNotIn("004_action_repeat_settings",str(caught.exception))

    def test_paths_urls_and_extended_parameters_survive_reload(self):
        self.migrated()
        pid=self.state.active_profile_id
        for action,value in (("Открыть ссылку","https://example.com/a?q=1"),
                             ("Запустить программу",r"C:\Program Files\Spotify\Spotify.exe")):
            self.state.set_action_settings(pid,"Большой палец вверх",action=action,action_value=value,scroll_step=7,pinch_smoothing=.5)
            self.repository.save(self.state.snapshot())
            self.state._apply_snapshot(self.repository.load())
            settings=self.state.get_action_settings(pid,"Большой палец вверх")
            self.assertEqual(settings["action_value"],value)
            self.assertEqual(settings["scroll_step"],7)
            self.assertEqual(settings["pinch_smoothing"],.5)

    def test_profile_delete_and_library_delete_are_separate(self):
        self.migrated()
        pid=self.state.active_profile_id
        other=self.state.duplicate_profile(pid)
        self.state.add_custom_gesture("Пользовательский",{"template":[0.]*63})
        for profile in (pid,other): self.state.set_assignment(profile,"Пользовательский","Громкость +")
        self.repository.save(self.state.snapshot())
        self.state._apply_snapshot(self.repository.load())
        gesture=next(g for g in self.state.gestures if g["name"]=="Пользовательский")
        self.state.remove_gesture_from_profile(pid,"Пользовательский")
        self.repository.save(self.state.snapshot())
        remaining=[a for a in self.server.tables["actions"] if a["gesture_id"]==gesture["id"]]
        self.assertEqual(len(remaining),1)
        self.assertNotEqual(remaining[0]["profile_id"],pid)
        self.assertTrue(any(g["id"]==gesture["id"] for g in self.server.tables["gestures"]))
        self.state.delete_custom_gesture("Пользовательский")
        self.repository.save(self.state.snapshot())
        self.assertFalse(any(a["gesture_id"]==gesture["id"] for a in self.server.tables["actions"]))
        self.assertFalse(any(g["id"]==gesture["id"] for g in self.server.tables["gestures"]))
        self.assertTrue(any(g["gesture_type"]=="standard" for g in self.server.tables["gestures"]))
