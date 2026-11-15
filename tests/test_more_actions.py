"""Новые действия проверяются без клавиш Windows, блокировки и завершения сеанса."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from actions.action_types import ACTION_CATALOG, ACTION_KEYS, DANGEROUS_ACTIONS, normalize_action_value, is_dangerous
from actions.action_executor import ActionExecutor, KEY_ACTIONS, GestureGate
from actions.windows_actions import WindowsActions
from app_state import AppState
from ui.action_settings_dialog import ActionSettingsDialog


class MoreActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def context(self,key):
        values={"hotkey":"Ctrl+Shift+S","open_application":r"C:\Program Files\Spotify\Spotify.exe",
                "open_file":r"C:\Users\Maks\example.txt","open_folder":r"C:\Users\Maks",
                "open_url":"https://example.com","set_brightness":"50","set_volume":"50"}
        return {"action_value":values.get(key,""),"value":.5,"direction":1,"scroll_step":4}

    def test_every_catalog_action_has_a_safe_test_route(self):
        backend=Mock()
        executor=ActionExecutor(backend=backend,test_mode=True)
        for key in ACTION_CATALOG:
            with self.subTest(action=key):
                message=executor.execute(key,self.context(key))
                self.assertTrue(executor.succeeded,message)
                self.assertIn("[TEST]",message)
        self.assertEqual(len(executor.calls),len(ACTION_CATALOG))
        self.assertEqual(backend.mock_calls,[])

    def test_required_keyboard_routes_and_windows_key_names(self):
        backend=Mock();executor=ActionExecutor(backend=backend)
        expected={"show_desktop":("win","d"),"close_window":("alt","f4"),"switch_window":("alt","tab"),
                  "copy":("ctrl","c"),"paste":("ctrl","v"),"save":("ctrl","s"),
                  "browser_back":("alt","left"),"browser_refresh":("f5",),"new_tab":("ctrl","t"),
                  "next_slide":("right",),"previous_slide":("left",),"zoom_in":("ctrl","+"),"zoom_out":("ctrl","-"),
                  "play_pause":("media_play_pause",),"next_track":("media_next",),"previous_track":("media_previous",)}
        for key,keys in expected.items():
            executor.execute(key)
            backend.keys.assert_called_with(*keys)
        native=WindowsActions();native._keyboard=Mock()
        for keys in KEY_ACTIONS.values():
            native.keys(*keys)
        self.assertEqual(native._keyboard.press.call_count,native._keyboard.release.call_count)

    def test_lock_and_power_commands_are_only_mocked(self):
        backend=Mock();executor=ActionExecutor(backend=backend,test_mode=True)
        for key in ("lock_pc",*DANGEROUS_ACTIONS):
            executor.execute(key)
            self.assertEqual(executor.calls[-1],("system",(key,),{}))
        self.assertEqual(backend.mock_calls,[])
        with patch("actions.windows_system.subprocess.run") as run:
            native=WindowsActions()
            for key,flags in (("shutdown_pc",["/s","/t","0"]),("restart_pc",["/r","/t","0"]),("sign_out",["/l"])):
                native.system(key)
                self.assertEqual(run.call_args.args[0][1:],flags)
                self.assertNotIn("/f",run.call_args.args[0])

    def test_power_assignment_confirmation_and_runtime_defaults(self):
        state=AppState();pid=state.active_profile_id;name="Большой палец вверх"
        before=state.assignments[pid][name]
        dialog=ActionSettingsDialog(state,pid,name)
        dialog.action.setCurrentText("Выключить компьютер")
        self.assertFalse(dialog.repeat.isEnabled())
        self.assertEqual(dialog.inputs["hold_time"].minimum(),0.)
        with patch.object(dialog,"confirm_dangerous",return_value=False): dialog.save()
        self.assertEqual(state.assignments[pid][name],before)
        with patch.object(dialog,"confirm_dangerous",return_value=True): dialog.save()
        raw=state.action_settings[pid][name]
        raw.update(hold_time=0.,repeat_while_held=True)
        settings=state.get_action_settings(pid,name)
        self.assertEqual(settings["hold_time"],0.)
        self.assertFalse(settings["repeat_while_held"])
        gate=GestureGate()
        fired=[i*.05 for i in range(101) if gate.update("up",.99,settings,i*.05)]
        self.assertEqual(fired,[0.])
        dialog.close()

    def test_dangerous_hotkey_and_invalid_targets(self):
        self.assertTrue(is_dangerous("hotkey","alt+f4"))
        self.assertTrue(is_dangerous("hotkey","win+ctrl+f4"))
        self.assertFalse(is_dangerous("hotkey","ctrl+shift+s"))
        for key,value in (("open_url","javascript:alert(1)"),("open_url","file:///C:/x"),
                          ("open_application",r"C:\Windows\notepad.exe /x"),("open_application","cmd /c del x"),
                          ("set_brightness","101")):
            with self.assertRaises(ValueError): normalize_action_value(key,value)
        executor=ActionExecutor(test_mode=True)
        executor.execute("shutdown_pc",{"repeat_while_held":True})
        self.assertFalse(executor.succeeded)
        self.assertEqual(executor.calls,[])

    def test_dynamic_fields_and_file_picker(self):
        state=AppState();dialog=ActionSettingsDialog(state,state.active_profile_id,"Большой палец вверх")
        dialog.action.setCurrentText("Прокрутка вниз")
        self.assertFalse(dialog.scroll_step.isHidden())
        self.assertTrue(dialog.volume_step.isHidden())
        dialog.action.setCurrentText("Запустить программу")
        self.assertFalse(dialog.browse_button.isHidden())
        with patch("ui.action_settings_dialog.QFileDialog.getOpenFileName",return_value=("C:/Windows/notepad.exe","")):
            dialog.browse()
        self.assertEqual(dialog.hotkey_input.text(),"C:/Windows/notepad.exe")
        self.assertEqual(dialog.action.currentData(),"open_application")
        dialog.close()

    def test_scroll_fixed_volume_and_optional_errors(self):
        backend=Mock();executor=ActionExecutor(backend=backend)
        executor.execute("scroll_left",{"scroll_step":7})
        backend.scroll.assert_called_with(-7,0)
        executor.execute("set_volume",{"action_value":"35"})
        backend.set_volume.assert_called_with(.35)
        executor.execute("media_play");backend.media_command.assert_called_with(46)
        executor.execute("media_pause");backend.media_command.assert_called_with(47)
        backend.brightness.side_effect=RuntimeError("Управление яркостью не поддерживается на этом устройстве.")
        message=executor.execute("brightness_up")
        self.assertFalse(executor.succeeded)
        self.assertIn("не поддерживается",message)
        backend.microphone_mute.side_effect=RuntimeError("Управление микрофоном недоступно на этом устройстве.")
        self.assertIn("недоступно",executor.execute("microphone_mute"))

    def test_migration_contains_every_action(self):
        from pathlib import Path
        sql=Path("database/migrations/005_more_action_types.sql").read_text(encoding="utf-8")
        for key in ACTION_KEYS.values(): self.assertIn("''"+key+"''",sql)

    def test_sleep_lock_and_launch_native_calls_are_mocked(self):
        from contextlib import nullcontext
        native=WindowsActions()
        api=Mock()
        with patch.object(native,"_user32",return_value=api):
            native.system("lock_pc")
            api.LockWorkStation.assert_called_once_with()
        with patch("actions.windows_system.ctypes.WinDLL",return_value=api), patch("actions.windows_system.shutdown_privilege",return_value=nullcontext()):
            native.system("sleep_pc")
            api.SetSuspendState.assert_called_once_with(False,False,False)
        with patch("actions.windows_system.webbrowser.open",return_value=True) as browser:
            native.open_target("open_url","https://example.com")
            browser.assert_called_once_with("https://example.com")
        with patch("actions.windows_system.Path.is_file",return_value=True), patch("actions.windows_system.subprocess.Popen") as process:
            native.open_target("open_application",r"C:\Program Files\Spotify\Spotify.exe")
            self.assertEqual(process.call_args.args[0],[r"C:\Program Files\Spotify\Spotify.exe"])
            self.assertFalse(process.call_args.kwargs["shell"])

    def test_static_set_volume_and_legacy_continuous_can_coexist(self):
        from control_runtime import ControlRuntime
        from test_control_runtime import FakeCamera
        state=AppState();camera=FakeCamera();runtime=ControlRuntime(state,camera)
        backend=Mock();runtime.executor.backend=backend
        state.set_action_settings(state.active_profile_id,"Большой палец вверх",action="Установить громкость",action_value="35")
        runtime.set_enabled(True)
        for i in range(20):
            camera.frame_ready.emit({"timestamp":i*.05,"hand":{"ready":True,"found":True},
                "gesture":{"key":"thumbs_up","name":"Большой палец вверх","confidence":.99}})
        backend.set_volume.assert_called_once_with(.35)
        state.set_action_settings(state.active_profile_id,"Pinch — регулировка",action="Установить громкость",action_value="")
        self.assertEqual(state.get_action_settings(state.active_profile_id,"Pinch — регулировка")["action_value"],"")
