"""Стабильные ключи действий для БД и названия для интерфейса."""

ACTION_KEYS = {
    "Нет действия": "none", "Play / Pause": "play_pause",
    "Следующий трек": "next_track", "Предыдущий трек": "previous_track",
    "Громкость +": "volume_up", "Громкость -": "volume_down",
    "Выключить звук": "mute", "Следующий слайд": "next_slide",
    "Предыдущий слайд": "previous_slide", "Своя комбинация клавиш": "hotkey",
    "Регулировка громкости": "pinch_volume", "Установить громкость": "set_volume",
    "Масштабирование": "zoom_control",
}

# Каталог — единый источник категорий и доступных действий для всех страниц.
ACTION_GROUPS = {
    "Система": [
        ("lock_pc", "Заблокировать компьютер"), ("sleep_pc", "Спящий режим"),
        ("shutdown_pc", "Выключить компьютер"), ("restart_pc", "Перезагрузить компьютер"),
        ("sign_out", "Выйти из Windows"), ("show_desktop", "Показать рабочий стол"),
        ("open_task_manager", "Открыть диспетчер задач"), ("open_settings", "Открыть параметры Windows"),
        ("open_explorer", "Открыть проводник")],
    "Окна": [("close_window", "Закрыть активное окно"), ("minimize_window", "Свернуть активное окно"),
        ("maximize_window", "Развернуть активное окно"), ("restore_window", "Восстановить окно"),
        ("switch_window", "Следующее окно"), ("switch_window_previous", "Предыдущее окно")],
    "Мультимедиа": [("play_pause", "Play / Pause"), ("media_play", "Воспроизвести"),
        ("media_pause", "Пауза"), ("next_track", "Следующий трек"), ("previous_track", "Предыдущий трек"),
        ("stop_media", "Остановить воспроизведение"), ("volume_up", "Громкость +"), ("volume_down", "Громкость -"),
        ("mute", "Выключить звук"), ("set_volume", "Установить громкость"), ("pinch_volume", "Регулировка громкости")],
    "Браузер": [("browser_back", "Назад"), ("browser_forward", "Вперёд"), ("browser_refresh", "Обновить страницу"),
        ("new_tab", "Новая вкладка"), ("close_tab", "Закрыть вкладку"), ("next_tab", "Следующая вкладка"),
        ("previous_tab", "Предыдущая вкладка"), ("focus_address_bar", "Адресная строка"),
        ("fullscreen", "Полноэкранный режим"), ("page_up", "Страница вверх"), ("page_down", "Страница вниз"),
        ("home_key", "В начало страницы"), ("end_key", "В конец страницы")],
    "Текст": [("copy", "Копировать"), ("paste", "Вставить"), ("cut", "Вырезать"), ("undo", "Отменить"),
        ("redo", "Повторить"), ("select_all", "Выделить всё"), ("save", "Сохранить"),
        ("save_as", "Сохранить как"), ("find", "Поиск"), ("print", "Печать")],
    "Презентация": [("next_slide", "Следующий слайд"), ("previous_slide", "Предыдущий слайд"),
        ("start_slideshow", "Начать показ"), ("end_slideshow", "Закончить показ"),
        ("black_screen", "Чёрный экран"), ("white_screen", "Белый экран"),
        ("presentation_first_slide", "Первый слайд"), ("presentation_last_slide", "Последний слайд")],
    "Масштаб и прокрутка": [("zoom_in", "Приблизить"), ("zoom_out", "Отдалить"), ("zoom_reset", "Сбросить масштаб"),
        ("zoom_control", "Масштабирование"), ("scroll_up", "Прокрутка вверх"), ("scroll_down", "Прокрутка вниз"),
        ("scroll_left", "Прокрутка влево"), ("scroll_right", "Прокрутка вправо")],
    "Устройства": [("brightness_up", "Яркость +"), ("brightness_down", "Яркость -"),
        ("set_brightness", "Установить яркость"), ("microphone_mute", "Отключить / включить микрофон")],
    "Рабочие столы": [("new_desktop", "Создать рабочий стол"), ("next_desktop", "Следующий рабочий стол"),
        ("previous_desktop", "Предыдущий рабочий стол"), ("close_desktop", "Закрыть рабочий стол")],
    "Другое": [("hotkey", "Своя комбинация клавиш"), ("open_application", "Запустить программу"),
        ("open_file", "Открыть файл"), ("open_folder", "Открыть папку"), ("open_url", "Открыть ссылку"),
        ("screenshot", "Сделать скриншот"), ("screenshot_area", "Снимок области экрана")],
}
ACTION_KEYS.update({title: key for group in ACTION_GROUPS.values() for key, title in group})
DANGEROUS_ACTIONS = {"shutdown_pc", "restart_pc", "sign_out", "sleep_pc"}
ACTION_CATALOG = {key: {"label": title, "category": category, "dangerous_action": key in DANGEROUS_ACTIONS}
                  for category, items in ACTION_GROUPS.items() for key, title in items}
CONTINUOUS_ACTIONS = {"pinch_volume", "set_volume", "zoom_control"}
VALUE_ACTIONS = {"hotkey", "open_application", "open_file", "open_folder", "open_url", "set_brightness", "set_volume"}


def is_dangerous(action, value=""):
    key = ACTION_KEYS.get(action, action)
    if key in DANGEROUS_ACTIONS:
        return True
    if key == "hotkey" and value:
        try:
            return normalize_hotkey(value) in {"Alt+F4", "Ctrl+Alt+Delete", "Win+L", "Ctrl+Win+F4", "Ctrl+W", "Ctrl+Shift+W"}
        except ValueError:
            return False
    return False


def normalize_action_value(action, value):
    import ntpath
    from urllib.parse import urlsplit
    key = ACTION_KEYS.get(action, action)
    if key not in VALUE_ACTIONS:
        return ""
    if not isinstance(value, str):
        raise ValueError("Параметр действия должен быть строкой.")
    value = value.strip()
    if key == "hotkey":
        return normalize_hotkey(value)
    if key == "set_volume" and not value:
        return ""  # Старые назначения set_volume остаются непрерывной регулировкой pinch.
    if key in ("set_volume", "set_brightness"):
        if not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 100:
            raise ValueError("Введите целое значение от 0 до 100%.")
        return str(int(value))
    if not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError("Укажите корректный путь или URL.")
    if key == "open_url":
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in ("http", "https") and parsed.hostname and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or any(c.isspace() for c in value):
            raise ValueError("Разрешены только ссылки http:// или https:// с именем сайта.")
    else:
        if not ntpath.isabs(value) or '"' in value:
            raise ValueError("Выберите полный путь без аргументов командной строки.")
        if key == "open_application" and ntpath.splitext(value)[1].lower() != ".exe":
            raise ValueError("Выберите исполняемый файл .exe, без команд и аргументов.")
    return value


def normalize_hotkey(value):
    """Храним одну комбинацию клавиш, не команду оболочки и не последовательность."""
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Введите комбинацию, например Ctrl+Shift+P.")
    parts = [part.strip().lower() for part in value.split("+")]
    modifiers = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    special = {"space": "Space", "enter": "Enter", "tab": "Tab", "esc": "Esc",
               "up": "Up", "down": "Down", "left": "Left", "right": "Right",
               "home": "Home", "end": "End", "pageup": "PageUp", "pagedown": "PageDown",
               "delete": "Delete", "backspace": "Backspace", "insert": "Insert"}
    key = parts[-1]
    if (any(part not in modifiers for part in parts[:-1])
            or len(set(parts[:-1])) != len(parts[:-1])):
        raise ValueError("Используйте Ctrl, Alt, Shift или Win и одну клавишу.")
    valid_key = (len(key) == 1 and key.isascii() and key.isalnum()) or key in special
    valid_key = valid_key or (key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24)
    if not valid_key:
        raise ValueError("Укажите одну клавишу: A–Z, 0–9, F1–F24 или Enter, Space и т. п.")
    return "+".join([modifiers[part] for part in modifiers if part in parts[:-1]]
                    + [special.get(key, key.upper())])
