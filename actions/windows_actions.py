"""Адаптер Windows: только системное аудио и клавиши, без управления мышью."""

import sys
from math import isfinite
from actions.action_types import normalize_hotkey
from actions.windows_system import WindowsSystemActions


class WindowsActions(WindowsSystemActions):
    def __init__(self):
        self._keyboard = None

    def _audio(self, operation):
        if sys.platform != "win32":
            raise RuntimeError("Системное аудио доступно только в Windows.")
        import comtypes
        from pycaw.pycaw import AudioUtilities
        # Получаем системную громкость Windows в том же COM-потоке, где используем её.
        comtypes.CoInitialize()
        endpoint = None
        try:
            endpoint = AudioUtilities.GetSpeakers().EndpointVolume
            return operation(endpoint)
        finally:
            endpoint = None
            comtypes.CoUninitialize()

    def get_volume(self):
        return float(self._audio(lambda endpoint: endpoint.GetMasterVolumeLevelScalar()))

    def set_volume(self, value):
        value = float(value)
        if not isfinite(value):
            raise ValueError("Громкость должна быть конечным числом.")
        value = max(0., min(1., value))
        self._audio(lambda endpoint: endpoint.SetMasterVolumeLevelScalar(value, None))
        return value

    def change_volume(self, delta):
        return self.set_volume(self.get_volume() + delta)

    def toggle_mute(self):
        def toggle(endpoint):
            muted = not bool(endpoint.GetMute())
            endpoint.SetMute(muted, None)
            return muted
        return self._audio(toggle)

    def keys(self, *names):
        if sys.platform != "win32":
            raise RuntimeError("Клавиши управления доступны только в Windows.")
        from pynput.keyboard import Controller, Key
        if self._keyboard is None:
            self._keyboard = Controller()
        aliases = {"win": "cmd", "pageup": "page_up", "pagedown": "page_down"}
        keys = [getattr(Key, aliases.get(name.lower(), name.lower())) if len(name) > 1 else name.lower() for name in names]
        pressed = []
        try:
            for key in keys:
                self._keyboard.press(key)
                pressed.append(key)
        finally:
            # Даже при ошибке освобождаем модификаторы, чтобы Ctrl/Shift не залипали.
            release_error = None
            for key in reversed(pressed):
                try:
                    self._keyboard.release(key)
                except Exception as error:
                    release_error = error
            if release_error is not None:
                raise RuntimeError("Не удалось отпустить клавишу Windows") from release_error

    def hotkey(self, value):
        self.keys(*normalize_hotkey(value).split("+"))
