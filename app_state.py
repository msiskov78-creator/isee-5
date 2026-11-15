"""Общее состояние приложения и последовательное сохранение в Supabase."""

from copy import deepcopy
import json
from math import isfinite
import logging
from uuid import uuid4
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from actions.action_types import ACTION_KEYS
from diagnostics import error_text, log_error
from actions.action_settings import ACTION_DEFAULTS, action_parameters, execution_mode, ExecutionMode
from actions.action_types import normalize_action_value, is_dangerous
from sensitivity import validate_sensitivity

GESTURES = ["Большой палец вверх", "Два пальца", "Кулак", "Открытая ладонь"]
GESTURE_KEYS = ["thumbs_up", "two_fingers", "fist", "open_palm"]
PINCH_GESTURE = {"key": "pinch_volume", "name": "Pinch — регулировка", "is_custom": False,
                 "recognition_type": "dynamic", "gesture_data": {"recognition_type": "dynamic", "dynamic_type": "pinch", "samples": []}}
ACTIONS = list(ACTION_KEYS)
DEFAULT_SETTINGS = {"camera": 0, "sensitivity": 0.7, "hold_time": 0.5,
                    "command_pause": 1.0, "mirror": True, "show_landmarks": True,
                    "auto_start": False, "onboarding_completed": False}
_UNSET = object()


class _RepositoryThread(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.result, self.error = operation, None, ""

    def run(self):
        from database.repository import RepositoryError
        try:
            self.result = self.operation()
        except RepositoryError as error:
            self.error = str(error)
        except Exception as error:
            log_error("Database", "Рабочий поток загрузки/сохранения", error)
            self.error = f"Ошибка данных ({type(error).__name__}): {error_text(error)}"
        finally:
            self.operation = None


class AppState(QObject):
    """UI меняет модель; сеть работает только в одном отдельном потоке."""

    changed = Signal()
    loaded = Signal()
    persistence_status = Signal(str, bool)
    busy_changed = Signal(bool)
    idle = Signal()
    save_completed = Signal(int)
    save_failed = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles = [{"id": str(uuid4()), "name": name, "description": ""}
                         for name in ("Музыка", "Презентация", "Видео")]
        self.active_profile_id = self.profiles[0]["id"]
        self.gestures = [{"id": str(uuid4()), "key": key, "name": name,
                          "gesture_data": {}, "is_custom": False}
                         for key, name in zip(GESTURE_KEYS, GESTURES)]
        defaults = [["Play / Pause", "Следующий трек", "Громкость -", "Нет действия"],
                    ["Следующий слайд", "Предыдущий слайд", "Нет действия", "Нет действия"],
                    ["Play / Pause", "Громкость +", "Громкость -", "Выключить звук"]]
        self.assignments = {p["id"]: dict(zip(GESTURES, actions)) for p, actions in zip(self.profiles, defaults)}
        self.gestures.append(dict(deepcopy(PINCH_GESTURE), id=str(uuid4())))
        for mapping in self.assignments.values():
            mapping[PINCH_GESTURE["name"]] = "Нет действия"
        self.action_settings = {p["id"]: {} for p in self.profiles}
        self.settings = deepcopy(DEFAULT_SETTINGS)
        self.revision = 0
        self._repository = None
        self._remote_loaded = False
        self.user_id = None
        self.account_profile = None
        self._load_error = ""
        self._worker = None
        self._job = None
        self._pending_snapshot = None
        self._dirty = False
        self._finishing_job = False

    @property
    def persistence_busy(self):
        return self._worker is not None or self._pending_snapshot is not None or self._finishing_job

    @property
    def has_unsaved_changes(self):
        return self._repository is not None and self._dirty

    @property
    def can_persist(self):
        return self._repository is not None and self._remote_loaded

    @property
    def active_profile_name(self):
        return self._get_profile(self.active_profile_id)["name"]

    def attach_repository(self, repository):
        if self._repository is not None:
            raise ValueError("Хранилище уже подключено к этому сеансу.")
        self._repository = repository
        self.user_id = getattr(repository, "user_id", self.user_id)
        self.load_async()

    def load_async(self):
        if not self._repository or self.persistence_busy:
            return
        # После неудачной загрузки запрещаем запись стартовых данных поверх серверных.
        self._load_error = ""
        self._start_job("load", 0, self._repository.load)

    def _start_job(self, kind, revision, operation):
        self._job = (kind, revision)
        self._worker = _RepositoryThread(operation, self)
        self._worker.finished.connect(self._job_finished)
        self.busy_changed.emit(True)
        self._worker.start()

    @Slot()
    def _job_finished(self):
        worker, (kind, revision) = self._worker, self._job
        self._finishing_job = True
        self._worker = None
        result, error = worker.result, worker.error
        worker.deleteLater()
        if not error and kind == "load":
            try:
                empty = not result.get("profiles")
                self._apply_snapshot(result)
                self._remote_loaded = True
                self.account_profile = result.get("account_profile")
                self._load_error = ""
                logging.getLogger("Profiles").info("active profile = %s (%s)", self.active_profile_name, self.active_profile_id)
                self.changed.emit()
                self.loaded.emit()
                if empty and self._pending_snapshot is None:
                    self._dirty = True
                    self._pending_snapshot = (self.revision, self.snapshot())
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as cause:
                self._remote_loaded = False
                log_error("Database", "Применение данных аккаунта", cause)
                error = f"Не удалось обработать данные аккаунта: {error_text(cause)}"
        if error:
            if kind == "load":
                self._remote_loaded = False
                self._load_error = error
            self._pending_snapshot = None
            self.persistence_status.emit(error, False)
            if kind == "save":
                self._dirty = True
                self.save_failed.emit(self.revision, error)
        elif kind == "save":
            self._dirty = self.revision > revision
            self.persistence_status.emit("Данные сохранены в Supabase.", True)
            self.save_completed.emit(revision)
        else:
            self.persistence_status.emit("Данные аккаунта загружены.", True)
        self._finishing_job = False
        if self._pending_snapshot is not None:
            revision, snapshot = self._pending_snapshot
            self._pending_snapshot = None
            self._start_job("save", revision, lambda: self._repository.save(snapshot))
        else:
            self.busy_changed.emit(False)
            self.idle.emit()

    def snapshot(self):
        return deepcopy({"profiles": self.profiles, "active_profile_id": self.active_profile_id,
                         "gestures": self.gestures, "assignments": self.assignments,
                         "action_settings": self.action_settings, "settings": self.settings})

    def _apply_snapshot(self, snapshot):
        if not isinstance(snapshot, dict):
            raise ValueError("Некорректные данные.")
        # Сначала проверяем отдельную копию: плохой ответ не меняет видимую модель.
        profiles = deepcopy(snapshot.get("profiles") or self.profiles)
        if not isinstance(profiles, list) or any(not p.get("id") or not p.get("name") for p in profiles):
            raise ValueError("Некорректные профили.")
        gestures = deepcopy(snapshot.get("gestures") or [])
        if not isinstance(gestures, list) or any(not g.get("id") or not g.get("name") or not g.get("key") for g in gestures):
            raise ValueError("Некорректные жесты.")
        existing_keys = {g["key"] for g in gestures}
        if "pinch_volume" not in existing_keys:
            gestures.append(dict(deepcopy(PINCH_GESTURE), id=str(uuid4())))
        for key, name in zip(GESTURE_KEYS, GESTURES):
            if key not in existing_keys:
                gestures.append({"id": str(uuid4()), "key": key, "name": name,
                                 "gesture_data": {}, "is_custom": False})
        settings = deepcopy(DEFAULT_SETTINGS)
        raw_settings = snapshot.get("settings") or {}
        if not isinstance(raw_settings, dict):
            raise ValueError("Некорректные настройки.")
        settings.update({k: v for k, v in raw_settings.items() if k in DEFAULT_SETTINGS and v is not None})
        self._validate_settings(settings)
        active_id = snapshot.get("active_profile_id")
        if active_id not in {p["id"] for p in profiles}:
            active_id = profiles[0]["id"]
        assignments = deepcopy(snapshot.get("assignments") or (self.assignments if not snapshot.get("profiles") else {}))
        action_settings = deepcopy(snapshot.get("action_settings") or {})
        if not isinstance(assignments, dict) or not isinstance(action_settings, dict):
            raise ValueError("Некорректные назначения.")
        for profile in profiles:
            mapping = assignments.setdefault(profile["id"], {})
            options = action_settings.setdefault(profile["id"], {})
            if not isinstance(mapping, dict) or not isinstance(options, dict):
                raise ValueError("Некорректные назначения.")
            for gesture in gestures:
                mapping.setdefault(gesture["name"], "Нет действия")
            if any(action not in ACTIONS for action in mapping.values()):
                raise ValueError("Неизвестное действие.")
            for gesture_name, values in options.items():
                if not isinstance(values, dict) or (values.get("enabled") is not None and type(values["enabled"]) is not bool):
                    raise ValueError("Некорректные параметры назначения.")
                validate_sensitivity(values.get("sensitivity"), nullable=True, source="actions.sensitivity")
                values.update(action_parameters(values))
                for key, low, high in (("hold_time", 0, float("inf")), ("cooldown", 0, float("inf"))):
                    value = values.get(key)
                    if value is not None and (type(value) not in (int, float) or not isfinite(value) or not low <= value <= high):
                        raise ValueError("Некорректные параметры назначения.")
                action_value = values.get("action_value", "")
                if action_value:
                    values["action_value"] = normalize_action_value(mapping.get(gesture_name), action_value)
        self.profiles, self.gestures, self.settings = profiles, gestures, settings
        self.active_profile_id, self.assignments, self.action_settings = active_id, assignments, action_settings

    def _ensure_editable(self):
        if self._repository is not None and not self._remote_loaded:
            if self._load_error:
                raise ValueError("Данные аккаунта не загружены. " + self._load_error)
            raise ValueError("Данные аккаунта ещё загружаются. Дождитесь завершения загрузки.")

    def _notify(self):
        self.revision += 1
        self._dirty = True
        self.changed.emit()
        self.flush_async()

    def flush_async(self):
        if self._repository is None:
            revision = self.revision
            QTimer.singleShot(0, lambda: self.save_completed.emit(revision))
            return
        self._ensure_editable()
        if not self._dirty:
            return
        self._pending_snapshot = (self.revision, self.snapshot())
        if self._worker is None and not self._finishing_job:
            revision, snapshot = self._pending_snapshot
            self._pending_snapshot = None
            self._start_job("save", revision, lambda: self._repository.save(snapshot))

    def _get_profile(self, profile_id):
        for profile in self.profiles:
            if profile["id"] == profile_id:
                return profile
        raise ValueError("Профиль не найден.")

    def _validate_name(self, name, excluding_id=None):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Введите название профиля.")
        name = name.strip()
        if len(name) > 32:
            raise ValueError("Название должно содержать не больше 32 символов.")
        if any(p["id"] != excluding_id and p["name"].casefold() == name.casefold() for p in self.profiles):
            raise ValueError("Профиль с таким названием уже существует.")
        return name

    def add_profile(self, name, description=""):
        self._ensure_editable()
        name = self._validate_name(name)
        if not isinstance(description, str) or len(description) > 250:
            raise ValueError("Описание должно быть не длиннее 250 символов.")
        profile_id = str(uuid4())
        self.profiles.append({"id": profile_id, "name": name, "description": description.strip()})
        self.assignments[profile_id] = {g["name"]: "Нет действия" for g in self.gestures}
        self.action_settings[profile_id] = {}
        self._notify()
        return profile_id

    def rename_profile(self, profile_id, name, description=None):
        self._ensure_editable()
        profile = self._get_profile(profile_id)
        name = self._validate_name(name, excluding_id=profile_id)
        if description is not None and (not isinstance(description, str) or len(description) > 250):
            raise ValueError("Описание должно быть не длиннее 250 символов.")
        profile["name"] = name
        if description is not None:
            profile["description"] = description.strip()
        self._notify()

    def duplicate_profile(self, profile_id, name=None):
        self._ensure_editable()
        source = self._get_profile(profile_id)
        if name is None:
            base, number = source["name"][:23], 1
            name = base + " (копия)"
            while any(p["name"].casefold() == name.casefold() for p in self.profiles):
                number += 1
                name = f"{base} ({number})"
        name = self._validate_name(name)
        new_id = str(uuid4())
        self.profiles.append({"id": new_id, "name": name, "description": source.get("description", "")})
        self.assignments[new_id] = deepcopy(self.assignments[profile_id])
        self.action_settings[new_id] = deepcopy(self.action_settings[profile_id])
        self._notify()
        return new_id

    def delete_profile(self, profile_id):
        self._ensure_editable()
        self._get_profile(profile_id)
        if len(self.profiles) == 1:
            raise ValueError("Нужно оставить хотя бы один профиль.")
        self.profiles = [p for p in self.profiles if p["id"] != profile_id]
        self.assignments.pop(profile_id)
        self.action_settings.pop(profile_id, None)
        if self.active_profile_id == profile_id:
            self.active_profile_id = self.profiles[0]["id"]
        self._notify()

    def set_active_profile(self, profile_id):
        self._ensure_editable()
        self._get_profile(profile_id)
        self.active_profile_id = profile_id
        self._notify()

    def set_assignment(self, profile_id, gesture, action, *, dangerous_confirmed=False):
        self._ensure_editable()
        self._get_profile(profile_id)
        if gesture not in {g["name"] for g in self.gestures} or action not in ACTIONS:
            raise ValueError("Неизвестный жест или действие.")
        self._validate_action_target(gesture, action)
        if is_dangerous(action, self.action_settings.get(profile_id, {}).get(gesture, {}).get("action_value", "")) and not dangerous_confirmed:
            raise ValueError("Подтвердите назначение опасного действия в настройках жеста.")
        self.assignments[profile_id][gesture] = action
        self._notify()

    def _validate_action_target(self, name, action, action_value=""):
        if execution_mode(action, {"action_value": action_value}) == ExecutionMode.CONTINUOUS:
            gesture = next(g for g in self.gestures if g["name"] == name)
            data = gesture.get("gesture_data") or {}
            if data.get("recognition_type") != "dynamic" or data.get("dynamic_type") != "pinch":
                raise ValueError("Непрерывная регулировка доступна для динамического pinch-жеста.")

    def get_action_settings(self, profile_id, gesture):
        self._get_profile(profile_id)
        # Загружаем действие для текущего профиля; NULL наследует глобальную настройку.
        raw = self.action_settings.get(profile_id, {}).get(gesture, {})
        fallback = {"enabled": True, "hold_time": self.settings["hold_time"],
                    "cooldown": self.settings["command_pause"], "sensitivity": self.settings["sensitivity"],
                    "action_value": "", **ACTION_DEFAULTS}
        result = {key: raw[key] if raw.get(key) is not None else value for key, value in fallback.items()}
        result["dangerous_action"] = is_dangerous(self.assignments.get(profile_id, {}).get(gesture), result["action_value"])
        if result["dangerous_action"]:
            # Системные действия выполняются только однократно, даже при старых настройках в БД.
            result["repeat_while_held"] = False
        return result

    def set_action_settings(self, profile_id, gesture, *, action=None, enabled=True,
                            hold_time=None, cooldown=None, sensitivity=None, action_value=_UNSET,
                            repeat_while_held=_UNSET, repeat_interval=_UNSET, volume_step=_UNSET,
                            scroll_step=_UNSET, pinch_smoothing=_UNSET, pinch_min=_UNSET, pinch_max=_UNSET,
                            dangerous_confirmed=False):
        self._ensure_editable()
        self._get_profile(profile_id)
        if gesture not in {g["name"] for g in self.gestures} or (action is not None and action not in ACTIONS):
            raise ValueError("Неизвестный жест или действие.")
        if type(enabled) is not bool:
            raise ValueError("Включение должно быть логическим значением.")
        validate_sensitivity(sensitivity, nullable=True, source="actions.sensitivity")
        for value, low, high in ((hold_time, 0, float("inf")), (cooldown, 0, float("inf"))):
            if value is not None and (type(value) not in (float, int) or not isfinite(value) or not low <= value <= high):
                raise ValueError("Параметры жеста вне допустимого диапазона.")
        if action_value is _UNSET:
            action_value = self.action_settings.get(profile_id, {}).get(gesture, {}).get("action_value", "")
        chosen_action = action if action is not None else self.assignments[profile_id].get(gesture)
        action_value = normalize_action_value(chosen_action, action_value or "")
        self._validate_action_target(gesture, chosen_action, action_value)
        dangerous = is_dangerous(chosen_action, action_value)
        if dangerous and not dangerous_confirmed:
            raise ValueError("Подтвердите назначение опасного действия.")
        extras = self.get_action_settings(profile_id, gesture)
        for key, value in (("repeat_while_held", repeat_while_held), ("repeat_interval", repeat_interval), ("volume_step", volume_step),
                           ("scroll_step", scroll_step), ("pinch_smoothing", pinch_smoothing), ("pinch_min", pinch_min), ("pinch_max", pinch_max)):
            if value is not _UNSET:
                extras[key] = value
        extras = action_parameters(extras)
        if execution_mode(chosen_action, {"action_value": action_value}) == ExecutionMode.CONTINUOUS or dangerous:
            extras["repeat_while_held"] = False
        self.action_settings[profile_id][gesture] = {"enabled": enabled, "hold_time": hold_time,
                                                   "cooldown": cooldown, "sensitivity": sensitivity,
                                                   "action_value": action_value, **extras}
        if action is not None:
            self.assignments[profile_id][gesture] = action
        self._notify()

    def remove_gesture_from_profile(self, profile_id, name):
        self._ensure_editable()
        self._get_profile(profile_id)
        # Удаляем только назначение жеста из конкретного профиля.
        # Сам жест остаётся в библиотеке пользователя.
        self.assignments[profile_id].pop(name, None)
        self.action_settings[profile_id].pop(name, None)
        self._notify()

    def delete_custom_gesture(self, name):
        self._ensure_editable()
        gesture = next((g for g in self.gestures if g["name"] == name), None)
        if gesture is None or not gesture.get("is_custom"):
            raise ValueError("Полностью удалить можно только пользовательский жест.")
        for pid in self.assignments:
            self.assignments[pid].pop(name, None)
            self.action_settings[pid].pop(name, None)
        self.gestures = [g for g in self.gestures if g["name"] != name]
        self._notify()

    def add_custom_gesture(self, name, gesture_data):
        self._ensure_editable()
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ValueError("Введите название жеста от 1 до 40 символов.")
        name = name.strip()
        if any(g["name"].casefold() == name.casefold() for g in self.gestures):
            raise ValueError("Жест с таким названием уже существует.")
        if not isinstance(gesture_data, dict) or not gesture_data:
            raise ValueError("Сначала запишите образцы жеста.")
        try:
            json.dumps(gesture_data, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("Некорректные образцы жеста.") from None
        gesture_id = str(uuid4())
        self.gestures.append({"id": gesture_id, "key": "custom_" + gesture_id, "name": name,
                              "gesture_data": deepcopy(gesture_data), "is_custom": True,
                              "recognition_type": gesture_data.get("recognition_type", "static")})
        for mapping in self.assignments.values():
            mapping[name] = "Нет действия"
        self._notify()
        return gesture_id

    def save_settings(self, camera=_UNSET, sensitivity=_UNSET, hold_time=_UNSET, command_pause=_UNSET,
                      *, mirror=_UNSET, show_landmarks=_UNSET, auto_start=_UNSET, onboarding_completed=_UNSET):
        self._ensure_editable()
        values = dict(self.settings)
        inputs = locals()
        for key in DEFAULT_SETTINGS:
            if inputs[key] is not _UNSET:
                values[key] = inputs[key]
        self._validate_settings(values)
        self.settings = values
        self._notify()

    @staticmethod
    def _validate_settings(values):
        if type(values["camera"]) is not int or not 0 <= values["camera"] <= 15:
            raise ValueError("Номер камеры должен быть от 0 до 15.")
        validate_sensitivity(values["sensitivity"], source="user_settings.sensitivity")
        for key, maximum in (("hold_time", float("inf")), ("command_pause", float("inf"))):
            if type(values[key]) not in (int, float) or not isfinite(values[key]) or not 0 <= values[key] <= maximum:
                raise ValueError("Время находится вне допустимого диапазона.")
        for key in ("mirror", "show_landmarks", "auto_start", "onboarding_completed"):
            if type(values[key]) is not bool:
                raise ValueError("Переключатель должен быть логическим значением.")
