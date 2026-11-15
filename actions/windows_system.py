"""Команды Windows без shell=True и без подстановки пользовательского текста в команды."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import webbrowser
from contextlib import contextmanager
from actions.action_types import normalize_action_value


@contextmanager
def shutdown_privilege():
    """Временно включаем уже доступную сеансу привилегию сна и восстанавливаем токен."""
    class Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]
    class Privileges(ctypes.Structure):
        _fields_ = [("count", wintypes.DWORD), ("luid", Luid), ("attributes", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
    security.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(Privileges),
        wintypes.DWORD, ctypes.POINTER(Privileges), ctypes.POINTER(wintypes.DWORD)]
    token = wintypes.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x20 | 0x8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    previous = Privileges()
    adjusted = False
    try:
        requested = Privileges()
        requested.count, requested.attributes = 1, 2
        if not security.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(requested.luid)):
            raise ctypes.WinError(ctypes.get_last_error())
        length = wintypes.DWORD()
        ctypes.set_last_error(0)
        adjusted = bool(security.AdjustTokenPrivileges(token, False, ctypes.byref(requested), ctypes.sizeof(previous),
                                                      ctypes.byref(previous), ctypes.byref(length)))
        error = ctypes.get_last_error()
        if not adjusted or error:
            raise ctypes.WinError(error)
        yield
    finally:
        if adjusted and previous.count:
            security.AdjustTokenPrivileges(token, False, ctypes.byref(previous), 0, None, None)
        kernel.CloseHandle(token)


class WindowsSystemActions:
    def _user32(self):
        if sys.platform != "win32":
            raise RuntimeError("Действие доступно только в Windows.")
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.GetForegroundWindow.restype = wintypes.HWND
        return api

    def system(self, action):
        # Системные действия вызываются исполнителем только в однократном режиме.
        if sys.platform != "win32":
            raise RuntimeError("Действие доступно только в Windows.")
        if action == "lock_pc":
            if not self._user32().LockWorkStation():
                raise ctypes.WinError(ctypes.get_last_error())
        elif action == "sleep_pc":
            api = ctypes.WinDLL("powrprof", use_last_error=True)
            api.SetSuspendState.argtypes = [ctypes.c_ubyte] * 3
            api.SetSuspendState.restype = ctypes.c_ubyte
            with shutdown_privilege():
                if not api.SetSuspendState(False, False, False):
                    raise ctypes.WinError(ctypes.get_last_error())
        else:
            arguments = {"shutdown_pc": ["/s", "/t", "0"], "restart_pc": ["/r", "/t", "0"], "sign_out": ["/l"]}
            command = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "shutdown.exe")
            subprocess.run([command, *arguments[action]], check=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)

    def window(self, action):
        api = self._user32()
        window = api.GetForegroundWindow()
        if not window:
            raise RuntimeError("Активное окно не найдено.")
        api.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        api.ShowWindowAsync.restype = wintypes.BOOL
        if not api.ShowWindowAsync(window, {"minimize_window":6, "maximize_window":3, "restore_window":9}[action]):
            raise RuntimeError("Windows не смогла изменить состояние окна.")

    def media_command(self, command):
        # Раздельные Play и Pause передаются как WM_APPCOMMAND, а не переключатель Play/Pause.
        api = self._user32()
        window = api.GetForegroundWindow()
        if not window:
            raise RuntimeError("Нет активного окна для мультимедийной команды.")
        api.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
            ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        api.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        result = ctypes.c_size_t()
        if not api.SendMessageTimeoutW(window, 0x0319, window, int(command) << 16, 2, 1000, ctypes.byref(result)):
            raise RuntimeError("Приложение не ответило на мультимедийную команду.")
        if not result.value:
            raise RuntimeError("Приложение не поддерживает эту мультимедийную команду.")

    def open_target(self, action, value):
        value = normalize_action_value(action, value)
        if action == "open_url":
            if not webbrowser.open(value):
                raise RuntimeError("Не удалось открыть стандартный браузер.")
            return
        target = Path(value)
        if action == "open_folder":
            if not target.is_dir():
                raise ValueError("Папка не найдена: " + value)
        elif not target.is_file():
            raise ValueError("Файл не найден: " + value)
        if action == "open_application":
            subprocess.Popen([value], shell=False, cwd=str(target.parent))
        else:
            os.startfile(value)

    def scroll(self, horizontal, vertical):
        from pynput.mouse import Controller
        Controller().scroll(horizontal, vertical)

    def brightness(self, delta=None, value=None):
        # Необязательная функция для дисплеев с WMI: только фиксированный скрипт и целые числа.
        if sys.platform != "win32":
            raise RuntimeError("Управление яркостью не поддерживается на этом устройстве.")
        adjustment = f"$level = {int(value)}" if value is not None else f"$level = [int]$screen.CurrentBrightness + {int(delta)}"
        script = ("$ErrorActionPreference='Stop'; "
                  "$screen = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Where-Object Active | Select-Object -First 1; "
                  "if ($null -eq $screen) { throw 'No supported display' }; " + adjustment + "; "
                  "$level=[byte][Math]::Max(0,[Math]::Min(100,$level)); "
                  "$method=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Where-Object { $_.InstanceName -eq $screen.InstanceName }; "
                  "if ($null -eq $method) { throw 'No brightness method' }; "
                  "$result=Invoke-CimMethod -InputObject $method -MethodName WmiSetBrightness -Arguments @{Timeout=[uint32]0;Brightness=$level}; "
                  "if ($result.ReturnValue -ne 0) { throw 'Brightness rejected' }")
        executable = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        try:
            subprocess.run([executable,"-NoProfile","-NonInteractive","-WindowStyle","Hidden","-Command",script],
                           check=True, capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError("Управление яркостью не поддерживается на этом устройстве.") from error

    def microphone_mute(self):
        try:
            import comtypes
            from pycaw.pycaw import AudioUtilities
            comtypes.CoInitialize()
            endpoint = None
            try:
                endpoint = AudioUtilities.GetMicrophone().EndpointVolume
                endpoint.SetMute(not bool(endpoint.GetMute()), None)
            finally:
                endpoint = None
                comtypes.CoUninitialize()
        except Exception as error:
            raise RuntimeError("Управление микрофоном недоступно на этом устройстве.") from error
