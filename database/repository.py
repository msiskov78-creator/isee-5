"""Работа с фактическими таблицами Supabase; сеть выполняется вне UI-потока."""

from uuid import UUID
import logging

from actions.action_types import ACTION_KEYS, normalize_action_value
from actions.action_settings import ACTION_DEFAULTS, action_parameters
from diagnostics import error_text, log_error
from sensitivity import validate_sensitivity, sensitivity_to_percent

ACTION_NAMES = {key: name for name, key in ACTION_KEYS.items()}
# Слева — реальные столбцы существующей БД, справа — ключи модели интерфейса.
SETTINGS_FIELDS = {
    "camera_index": "camera", "sensitivity": "sensitivity", "hold_time": "hold_time",
    "cooldown": "command_pause", "mirror_camera": "mirror", "show_landmarks": "show_landmarks",
    "auto_start_recognition": "auto_start", "onboarding_completed": "onboarding_completed",
}


class RepositoryError(Exception):
    def __init__(self, message, *, code="", operation=""):
        super().__init__(message)
        self.code, self.operation = code, operation


class SupabaseRepository:
    def __init__(self, client, user_id):
        if client is None:
            raise ValueError("Сначала выполните вход.")
        self.client = client
        self.user_id = str(UUID(str(user_id)))
        self._mode = None
        # Временные UUID существуют только в UI; в БД идут серверные int8.
        self._entity_ids = {"control_profiles": {}, "gestures": {}}

    def _request(self, operation, query):
        try:
            return query().execute().data
        except Exception as error:
            # Точный ответ PostgREST (code/message/details/hint) остаётся в консоли.
            log_error("Database", operation, error)
            code = str(getattr(error, "code", ""))
            message = getattr(error, "message", None)
            message = error_text(message if message is not None else error)
            if code == "23514" and "action_type" in message:
                message += " Выполните вручную database/migrations/005_more_action_types.sql для новых типов действий."
            marker = f" [{code}]" if code else ""
            raise RepositoryError(f"{operation}{marker}: {message}", code=code, operation=operation) from error

    def _select_rows(self, table, owner_column="user_id"):
        result = self._request(f"SELECT {table}", lambda: self.client.table(table).select("*").eq(owner_column, self.user_id))
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise RepositoryError(f"SELECT {table}: ожидался список строк.")
        return result

    def _verify_session(self):
        try:
            session = self.client.auth.get_session()
            if session is None:
                raise RepositoryError("Нет активной сессии Supabase. Войдите заново.")
            response = self.client.auth.get_user(session.access_token)
            actual_id = str(getattr(getattr(response, "user", None), "id", ""))
            if actual_id != self.user_id:
                raise RepositoryError("Пользователь сессии отличается от владельца данных. Войдите заново.")
            # Передаём PostgREST тот же проверенный JWT; ключ проекта не заменяет сессию.
            self.client.postgrest.auth(session.access_token)
            logging.getLogger("Auth").info("Сессия БД проверена: user_id = %s; PostgREST авторизован", actual_id)
        except RepositoryError as error:
            logging.getLogger("Auth").error("Проверка сессии БД: %s", error)
            raise
        except Exception as error:
            log_error("Auth", "Проверка сессии БД", error)
            raise RepositoryError("Не удалось проверить сессию Supabase: " + error_text(error)) from error

    def _load_account_profile(self):
        rows = self._select_rows("profiles", "id")
        if len(rows) > 1:
            raise RepositoryError("SELECT profiles: одному пользователю соответствует несколько строк.")
        if not rows:
            logging.getLogger("Profile").warning("Строка profiles для %s отсутствует или скрыта RLS; используем данные Auth", self.user_id)
            return None
        if str(rows[0].get("id")) != self.user_id:
            raise RepositoryError("SELECT profiles: профиль принадлежит другому пользователю.")
        logging.getLogger("Profile").info("Профиль загружен: %s", self.user_id)
        logging.getLogger("Profile").info("username = %s", rows[0].get("username"))
        return rows[0]

    def load(self):
        self._mode = None
        self._verify_session()
        profile = self._load_account_profile()
        # Фактическая схема пользователя не требует дополнительных RPC или миграций.
        result = self._load_tables()
        self._mode = "tables"
        if not isinstance(result, dict) or result.get("user_id") != self.user_id:
            self._mode = None
            raise RepositoryError("Хранилище вернуло данные другого сеанса или неподдерживаемый формат.")
        result["account_profile"] = profile
        settings = result.get("settings")
        if settings:
            logging.getLogger("Settings").info("Настройки загружены: %s", self.user_id)
        else:
            logging.getLogger("Settings").warning("SELECT user_settings вернул 0 строк для user_id=%s: строка отсутствует ИЛИ скрыта RLS; начальные настройки ещё не сохранены", self.user_id)
        logging.getLogger("Profiles").info("Профилей управления загружено: %s", len(result.get("profiles") or []))
        logging.getLogger("Gestures").info("loaded = %s", len(result.get("gestures") or []))
        return result

    def _read_workspace_tables(self):
        return {table: self._select_rows(table) for table in ("user_settings", "control_profiles", "gestures", "actions")}

    def _load_tables(self):
        rows = self._read_workspace_tables()
        if len(rows["user_settings"]) > 1:
            raise RepositoryError("SELECT user_settings: найдено несколько строк одного пользователя.")
        settings = rows["user_settings"][0] if rows["user_settings"] else {}
        self._recognition_column = any("recognition_type" in row for row in rows["gestures"])
        if not rows["gestures"]:
            try:
                # Даже для пустого аккаунта определяем колонку до первого INSERT.
                self._request("SELECT gestures.recognition_type", lambda: self.client.table("gestures")
                              .select("recognition_type").eq("user_id", self.user_id).limit(0))
                self._recognition_column = True
            except RepositoryError as error:
                if error.code not in ("42703", "PGRST204"):
                    raise
                self._recognition_column = False
        if "sensitivity" in settings:
            validate_sensitivity(settings["sensitivity"], source="user_settings.sensitivity DB")
            logging.getLogger("Settings").info("sensitivity DB = %s", settings["sensitivity"])
            logging.getLogger("Settings").info("sensitivity UI = %s%%", sensitivity_to_percent(settings["sensitivity"]))
        profiles = [{"id": row["id"], "name": row["name"], "description": row.get("description") or ""}
                    for row in rows["control_profiles"]]
        active = [row["id"] for row in rows["control_profiles"] if row.get("is_active")]
        if len(active) > 1:
            raise RepositoryError("SELECT control_profiles: у пользователя несколько активных профилей.")
        gestures = [{"id": row["id"], "name": row["name"], "key": row.get("gesture_key") or "custom_" + str(row["id"]),
                     "is_custom": row.get("gesture_type") == "custom", "gesture_data": row.get("gesture_data") or {},
                     "recognition_type": (row.get("gesture_data") or {}).get("recognition_type", row.get("recognition_type", "static"))}
                    for row in rows["gestures"]]
        names = {row["id"]: row["name"] for row in gestures}
        assignments, options = {}, {}
        for row in rows["actions"]:
            validate_sensitivity(row.get("sensitivity"), nullable=True, source=f"actions[{row['id']}].sensitivity DB")
            if row.get("gesture_id") not in names:
                raise RepositoryError("SELECT actions: связанный жест отсутствует среди доступных жестов пользователя.")
            action_key = row.get("action_type") or "none"
            if action_key not in ACTION_NAMES:
                raise RepositoryError(f"SELECT actions: неизвестный action_type {action_key!r}.")
            pid, name = row["profile_id"], names[row["gesture_id"]]
            assignments.setdefault(pid, {})[name] = ACTION_NAMES[action_key]
            options.setdefault(pid, {})[name] = {key: row.get(key) for key in
                ("enabled", "hold_time", "cooldown", "sensitivity", "action_value", *ACTION_DEFAULTS)}
        return {"user_id": self.user_id, "profiles": profiles, "gestures": gestures,
                "active_profile_id": active[0] if active else None,
                "settings": {key: settings[column] for column, key in SETTINGS_FIELDS.items() if column in settings},
                "assignments": assignments, "action_settings": options}

    def save(self, snapshot):
        if self._mode != "tables":
            raise RepositoryError("Сначала успешно загрузите данные аккаунта.")
        self._verify_session()
        # Проверяем до первой записи: проценты в БД попасть не могут.
        validate_sensitivity(snapshot["settings"]["sensitivity"], source="user_settings.sensitivity")
        for options in snapshot.get("action_settings", {}).values():
            for value in options.values():
                validate_sensitivity(value.get("sensitivity"), nullable=True, source="actions.sensitivity")
        self._save_tables(snapshot)

    def _write_entities(self, table, desired, existing, natural_key):
        """Создаём int8 на сервере, связывая ответ с временным идентификатором UI."""
        known = {row["id"]: row for row in existing}
        aliases = self._entity_ids.get(table, {})
        result_rows = []
        for source in desired:
            row = dict(source)
            local_id = row.pop("id", None)
            server_id = aliases.get(local_id, local_id)
            old = known.get(server_id)
            if old is None:
                if type(server_id) is int:
                    raise RepositoryError(f"UPDATE {table}: запись {server_id} отсутствует или недоступна.")
                # После частичной записи повторно используем уже созданную строку.
                matches = [item for item in known.values() if all(item.get(k) == row.get(k) for k in natural_key)]
                if len(matches) > 1:
                    raise RepositoryError(f"{table}: несколько строк с одинаковым ключом {natural_key}.")
                old = matches[0] if matches else None
            if old is None:
                inserted = self._request(f"INSERT {table}", lambda: self.client.table(table).insert(row))
                if (not isinstance(inserted, list) or len(inserted) != 1
                        or type(inserted[0].get("id")) is not int
                        or inserted[0].get("user_id") != self.user_id
                        or any(inserted[0].get(k) != row.get(k) for k in natural_key)):
                    raise RepositoryError(f"INSERT {table}: сервер не вернул числовой id созданной строки.")
                old = inserted[0]
            server_id = old["id"]
            if local_id is not None:
                aliases[local_id] = server_id
            row["id"] = server_id
            if any(old.get(field) != value for field, value in row.items()):
                self._update_row(table, row)
            known[server_id] = row
            result_rows.append(row)
        return result_rows

    def _update_row(self, table, row, key="id"):
        result = self._request(f"UPDATE {table}", lambda: self.client.table(table).update(row)
                              .eq("user_id", self.user_id).eq(key, row[key]))
        if not isinstance(result, list) or len(result) != 1:
            raise RepositoryError(f"UPDATE {table}: строка не обновлена; проверьте RLS и текущий аккаунт.")

    def _write_rows(self, table, desired, existing, key="id"):
        known = {row[key]: row for row in existing}
        missing = []
        for row in desired:
            old = known.get(row[key])
            if old is None:
                missing.append(row)
            elif any(old.get(field) != value for field, value in row.items()):
                self._update_row(table, row, key)
        if missing:
            if table == "user_settings":
                logging.getLogger("Settings").info("INSERT user_settings: user_id=%s; SELECT вернул 0 строк", self.user_id)
            try:
                result = self._request(f"INSERT {table}", lambda: self.client.table(table).insert(missing))
            except RepositoryError as error:
                if table == "user_settings" and error.code == "42501":
                    raise RepositoryError(str(error) + " Сессия и user_id проверены. SELECT вернул 0 строк: запись отсутствует или скрыта RLS. Проверьте политики SELECT и INSERT (WITH CHECK) для authenticated в user_settings.",
                                          code=error.code, operation=error.operation) from error
                raise
            if not isinstance(result, list) or {row.get(key) for row in result} != {row[key] for row in missing}:
                raise RepositoryError(f"INSERT {table}: сервер не подтвердил создание всех строк.")

    def _save_tables(self, snapshot):
        # Порядок операций важен: сначала настройки, затем владельцы связей,
        # затем назначения и удаления. Это не транзакция; повтор должен быть безопасен.
        # В существующей БД RPC нет. Пишем только строки владельца; при ошибке
        # не сообщаем об успехе. Повтор читает актуальные строки и не создаёт копии.
        rows = self._read_workspace_tables()
        # Проверяем только действительно нужные отсутствующие поля: миграции 004 и 005 независимы.
        extra_columns = set(rows["actions"][0]) & set(ACTION_DEFAULTS) if rows["actions"] else set()
        required = set()
        for pid, mappings in snapshot.get("action_settings", {}).items():
            for name, opts in mappings.items():
                if snapshot["assignments"].get(pid, {}).get(name, "Нет действия") != "Нет действия":
                    required.update(key for key, value in action_parameters(opts).items() if value != ACTION_DEFAULTS[key])
        migrations = {
            "004_action_repeat_settings.sql": {"repeat_while_held", "repeat_interval", "volume_step"},
            "005_more_action_types.sql": {"scroll_step", "pinch_smoothing", "pinch_min", "pinch_max"},
        }
        for migration, fields in migrations.items():
            missing = (required - extra_columns) & fields
            if not missing:
                continue
            try:
                self._request("SELECT actions parameters", lambda: self.client.table("actions")
                              .select(",".join(sorted(missing))).eq("user_id", self.user_id).limit(0))
                extra_columns.update(missing)
            except RepositoryError as error:
                if error.code in ("42703", "PGRST204"):
                    raise RepositoryError(str(error) + f" Для этих параметров выполните вручную database/migrations/{migration} и повторите сохранение.",
                                          code=error.code, operation=error.operation) from error
                raise
        uid, active_id = self.user_id, snapshot["active_profile_id"]
        profiles = snapshot["profiles"]
        if active_id not in {p["id"] for p in profiles}:
            raise RepositoryError("Активный профиль отсутствует в сохраняемых данных.")
        # Отказ записи настроек выявляем до изменения профилей и назначений.
        settings = {column: snapshot["settings"][key] for column, key in SETTINGS_FIELDS.items()}
        self._write_rows("user_settings", [dict(settings, user_id=uid)], rows["user_settings"], "user_id")
        for old in rows["control_profiles"]:
            if old.get("is_active") and old["id"] != self._entity_ids["control_profiles"].get(active_id, active_id):
                changed = {"id": old["id"], "user_id": uid, "is_active": False}
                self._update_row("control_profiles", changed)
                old["is_active"] = False
        saved_profiles = self._write_entities("control_profiles",
            [dict(p, user_id=uid, is_active=p["id"] == active_id) for p in profiles], rows["control_profiles"], ("name",))
        profile_ids_by_local = {p["id"]: saved["id"] for p, saved in zip(profiles, saved_profiles)}
        gestures = [{"id": g["id"], "user_id": uid, "name": g["name"], "gesture_key": g["key"],
                     "gesture_type": "custom" if g.get("is_custom") else "standard", "gesture_data": g.get("gesture_data") or {}}
                    for g in snapshot["gestures"]]
        # До ручной миграции тип также хранится в JSONB, существующие записи остаются доступны.
        if getattr(self, "_recognition_column", False):
            for row, gesture in zip(gestures, snapshot["gestures"]):
                row["recognition_type"] = gesture.get("recognition_type", gesture.get("gesture_data", {}).get("recognition_type", "static"))
        gestures = self._write_entities("gestures", gestures, rows["gestures"], ("gesture_key",))
        gesture_ids = {g["name"]: g["id"] for g in gestures}
        known_actions = {(row["profile_id"], row["gesture_id"]): row["id"] for row in rows["actions"]}
        actions = []
        for pid, mappings in snapshot["assignments"].items():
            server_pid = profile_ids_by_local[pid]
            for name, action in mappings.items():
                gid = gesture_ids[name]
                opts = snapshot.get("action_settings", {}).get(pid, {}).get(name, {})
                action_key = ACTION_KEYS[action]
                if action_key == "none":
                    # Отсутствие назначения представлено отсутствием строки actions.
                    continue
                actions.append({"id": known_actions.get((server_pid, gid)), "user_id": uid,
                    "profile_id": server_pid, "gesture_id": gid, "action_type": action_key,
                    "action_value": normalize_action_value(action_key, opts.get("action_value") or ""),
                    "enabled": opts.get("enabled") if opts.get("enabled") is not None else True,
                    **{key: value for key, value in action_parameters(opts).items() if key in extra_columns},
                    **{key: opts.get(key) for key in ("hold_time", "cooldown", "sensitivity")}})
        self._write_entities("actions", actions, rows["actions"], ("profile_id", "gesture_id"))
        desired_pairs = {(row["profile_id"], row["gesture_id"]) for row in actions}
        profile_ids = {p["id"] for p in saved_profiles}
        for old in rows["actions"]:
            if old["profile_id"] in profile_ids and (old["profile_id"], old["gesture_id"]) not in desired_pairs:
                deleted = self._request("DELETE actions снятого назначения", lambda: self.client.table("actions").delete()
                                        .eq("user_id", uid).eq("id", old["id"]))
                if not isinstance(deleted, list) or len(deleted) != 1:
                    raise RepositoryError("DELETE actions: сервер не подтвердил снятие назначения.")
        remaining = profile_ids
        for old in rows["control_profiles"]:
            if old["id"] not in remaining:
                self._request("DELETE actions удалённого профиля", lambda: self.client.table("actions").delete()
                              .eq("user_id", uid).eq("profile_id", old["id"]))
                deleted = self._request("DELETE control_profiles", lambda: self.client.table("control_profiles").delete()
                                        .eq("user_id", uid).eq("id", old["id"]))
                if not isinstance(deleted, list) or len(deleted) != 1:
                    raise RepositoryError("DELETE control_profiles: сервер не подтвердил удаление профиля.")
        # Назначения удалены выше явно: не полагаемся на наличие CASCADE в пользовательской БД.
        desired_gestures = {g["id"] for g in gestures}
        for old in rows["gestures"]:
            if old["id"] not in desired_gestures and old.get("gesture_type") == "custom":
                deleted = self._request("DELETE gestures", lambda: self.client.table("gestures").delete()
                                        .eq("user_id", uid).eq("id", old["id"]))
                if not isinstance(deleted, list) or len(deleted) != 1:
                    raise RepositoryError("DELETE gestures: сервер не подтвердил удаление жеста.")
        logging.getLogger("Database").info("Изменения сохранены в существующих таблицах пользователя %s", uid)
