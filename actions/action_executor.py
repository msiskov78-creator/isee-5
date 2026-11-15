"""Защита от повторов и выполнение команд Windows."""

from math import isfinite
import logging
from PySide6.QtCore import QObject, Signal
from actions.action_types import normalize_hotkey, ACTION_KEYS, normalize_action_value, is_dangerous, DANGEROUS_ACTIONS
from actions.windows_actions import WindowsActions
from diagnostics import log_error
from actions.action_settings import action_parameters
# Сохраняем старый путь импорта для тестов и внешнего кода.
from actions.gesture_gate import GestureGate as GestureGate




# Простые клавиатурные команды собраны отдельно от системного API и параметров.
KEY_ACTIONS = {
    "play_pause": ("media_play_pause",), "next_track": ("media_next",), "previous_track": ("media_previous",),
    "stop_media": ("media_stop",), "next_slide": ("right",), "previous_slide": ("left",),
    "show_desktop": ("win","d"), "open_task_manager": ("ctrl","shift","esc"),
    "open_settings": ("win","i"), "open_explorer": ("win","e"),
    "close_window": ("alt","f4"), "switch_window": ("alt","tab"), "switch_window_previous": ("alt","shift","tab"),
    "browser_back": ("alt","left"), "browser_forward": ("alt","right"), "browser_refresh": ("f5",),
    "new_tab": ("ctrl","t"), "close_tab": ("ctrl","w"), "next_tab": ("ctrl","tab"),
    "previous_tab": ("ctrl","shift","tab"), "focus_address_bar": ("ctrl","l"), "fullscreen": ("f11",),
    "page_up": ("pageup",), "page_down": ("pagedown",), "home_key": ("ctrl","home"), "end_key": ("ctrl","end"),
    "copy": ("ctrl","c"), "paste": ("ctrl","v"), "cut": ("ctrl","x"), "undo": ("ctrl","z"),
    "redo": ("ctrl","y"), "select_all": ("ctrl","a"), "save": ("ctrl","s"),
    "save_as": ("ctrl","shift","s"), "find": ("ctrl","f"), "print": ("ctrl","p"),
    "screenshot": ("win","print_screen"), "screenshot_area": ("win","shift","s"),
    "start_slideshow": ("f5",), "end_slideshow": ("esc",), "black_screen": ("b",), "white_screen": ("w",),
    "presentation_first_slide": ("home",), "presentation_last_slide": ("end",),
    "zoom_in": ("ctrl","+"), "zoom_out": ("ctrl","-"), "zoom_reset": ("ctrl","0"),
    "new_desktop": ("win","ctrl","d"), "next_desktop": ("win","ctrl","right"),
    "previous_desktop": ("win","ctrl","left"), "close_desktop": ("win","ctrl","f4"),
}


class ActionExecutor(QObject):
    executed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None, backend=None, test_mode=False):
        super().__init__(parent)
        self.backend = backend if backend is not None else WindowsActions()
        self.test_mode = bool(test_mode)
        self.calls = []
        self.succeeded = False

    def _invoke(self, method, *args, **kwargs):
        # В тестовом режиме не вызываем ни клавиши, ни файлы, ни выключение компьютера.
        if self.test_mode:
            self.calls.append((method, args, kwargs))
            return None
        return getattr(self.backend, method)(*args, **kwargs)

    def execute_volume_action(self, key, context):
        # Изменяем системную громкость в пределах 0–100%.
        if key in ("volume_up", "volume_down"):
            step = action_parameters(context)["volume_step"] / 100.
            self._invoke("change_volume", step if key == "volume_up" else -step)
        elif key == "mute":
            self._invoke("toggle_mute")
        else:
            value = context.get("value")
            if value is None:
                value = float(normalize_action_value(key, context.get("action_value", ""))) / 100.
            if not isfinite(float(value)):
                raise ValueError("Некорректное значение громкости.")
            self._invoke("set_volume", max(0., min(1., float(value))))

    def execute_application_action(self, key, context):
        value = normalize_action_value(key, context.get("action_value", ""))
        self._invoke("open_target", key, value)

    def execute_keyboard_action(self, key, context):
        if key == "hotkey":
            self._invoke("hotkey", normalize_hotkey(context.get("action_value", "")))
        elif key == "zoom_control":
            self._invoke("keys", "ctrl", "+" if context["direction"] > 0 else "-")
        else:
            self._invoke("keys", *KEY_ACTIONS[key])

    def execute_device_action(self, key, context):
        if key == "microphone_mute":
            self._invoke("microphone_mute")
        elif key == "set_brightness":
            self._invoke("brightness", value=int(normalize_action_value(key, context.get("action_value", ""))))
        else:
            self._invoke("brightness", delta=5 if key == "brightness_up" else -5)

    def execute(self, action, context=None):
        self.succeeded = False
        key = ACTION_KEYS.get(action, action)
        if not key or key == "none":
            return "Действие не назначено"
        context = context or {}
        message = f"Действие: {action}"
        logger = logging.getLogger("Action")
        try:
            if is_dangerous(key, context.get("action_value", "")):
                logger.warning("%s requested", key)
                if context.get("repeat_while_held"):
                    raise ValueError("Опасные действия нельзя выполнять в режиме повтора.")
            if key in KEY_ACTIONS or key in ("hotkey", "zoom_control"):
                self.execute_keyboard_action(key, context)
            elif key in ("volume_up", "volume_down", "mute", "set_volume", "pinch_volume"):
                self.execute_volume_action(key, context)
            elif key in ("open_application", "open_file", "open_folder", "open_url"):
                self.execute_application_action(key, context)
            elif key in DANGEROUS_ACTIONS or key == "lock_pc":
                self._invoke("system", key)
            elif key in ("minimize_window", "maximize_window", "restore_window"):
                self._invoke("window", key)
            elif key in ("media_play", "media_pause"):
                # Выполняем мультимедийную команду, не подменяя паузу переключателем.
                self._invoke("media_command", 46 if key == "media_play" else 47)
            elif key in ("brightness_up", "brightness_down", "set_brightness", "microphone_mute"):
                self.execute_device_action(key, context)
            elif key in ("scroll_up", "scroll_down", "scroll_left", "scroll_right"):
                step = action_parameters(context)["scroll_step"]
                dx, dy = {"scroll_up":(0,1),"scroll_down":(0,-1),"scroll_left":(-1,0),"scroll_right":(1,0)}[key]
                self._invoke("scroll", dx*step, dy*step)
            else:
                raise ValueError(f"Неизвестное действие: {key}")
        except Exception as error:
            log_error("Actions", str(key), error)
            message = f"Не удалось выполнить {action}: {error}"
            self.failed.emit(message)
            return message
        self.succeeded = True
        detail = ""
        if key in ("volume_up", "volume_down"):
            detail = f" {'+' if key == 'volume_up' else '-'}{action_parameters(context)['volume_step']}%"
        elif key == "hotkey":
            detail = " · " + normalize_hotkey(context.get("action_value", ""))
        elif key == "open_application":
            import ntpath
            detail = ": " + ntpath.basename(context.get("action_value", ""))
        message += detail
        if self.test_mode:
            message = "[TEST] " + key + detail
        logger.info("%s%s", "[TEST] " if self.test_mode else "", key + detail)
        self.executed.emit(message)
        return message
