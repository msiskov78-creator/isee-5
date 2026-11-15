"""Работа с Supabase Auth. Пароли и сессии не записываются в файлы."""

import base64
import json
import logging
import os
import re
from app_paths import APP_DIRECTORY
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from supabase import Client, ClientOptions, create_client
from diagnostics import log_error


# ==========================================
# НАСТРОЙКИ ПОДКЛЮЧЕНИЯ
# ==========================================

# Для будущего .exe файл настроек должен находиться рядом с программой.

# Загружаем данные из .env рядом с main.py (или рядом с будущим .exe).
# Существующие переменные окружения не перезаписываем.
ENV_PATH = APP_DIRECTORY / ".env"
load_dotenv(ENV_PATH, encoding="utf-8-sig", interpolate=False)

# Сохраняем чтение прежнего config.json для совместимости с существующим кодом.
# Новые настройки подключения нужно вводить в .env.
CONFIG_PATH = APP_DIRECTORY / "config.json"
_config = {}
_config_error = ""
try:
    if CONFIG_PATH.exists():
        _config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(_config, dict):
            raise ValueError("Configuration must be an object")
except (OSError, ValueError):
    _config = {}
    _config_error = "Не удалось прочитать config.json. Проверьте формат файла по config.example.json."

# Получаем адрес проекта Supabase из окружения, включая загруженный .env.
SUPABASE_URL = os.getenv("SUPABASE_URL", _config.get("SUPABASE_URL", ""))

# Получаем публичный ключ. Значение ключа нигде не выводим.
SUPABASE_KEY = os.getenv("SUPABASE_KEY", _config.get("SUPABASE_KEY", ""))


class AuthError(Exception):
    """Понятная ошибка, которую безопасно показать пользователю в QLabel."""


def validate_username(username: str) -> str:
    """Проверяем логин и приводим регистр к одному виду."""
    username = username.strip()
    if not username:
        raise AuthError("Введите логин.")
    if not 3 <= len(username) <= 20:
        raise AuthError("Логин должен содержать от 3 до 20 символов.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", username):
        raise AuthError("В логине разрешены латинские буквы, цифры и знак _.")
    return username.lower()


def validate_password(password: str) -> None:
    # Пробелы не обрезаем: пароль должен передаваться точно в введённом виде.
    if len(password) != 6:
        raise AuthError("Введите все 6 символов пароля.")


def get_username(user, fallback: str = "Пользователь") -> str:
    """Берём имя из metadata; технический адрес никогда не показываем."""
    metadata = getattr(user, "user_metadata", None) or {}
    if isinstance(metadata, dict):
        for field in ("username", "name"):
            value = metadata.get(field)
            if isinstance(value, str):
                value = value.strip()
                if value and "@" not in value and len(value) <= 64 and value.isprintable():
                    return value
    if isinstance(fallback, str) and fallback.strip() and "@" not in fallback:
        return fallback.strip()[:64]
    return "Пользователь"


def _public_key_error(key: str) -> str:
    """Проверяем тип ключа, чтобы случайно не встроить серверный секрет."""
    if key.startswith("sb_publishable_") and re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key):
        return ""
    # Старый anon key имеет формат JWT. Читаем только название его роли.
    # Это проверка настроек, а подлинность ключа проверяет сам Supabase.
    try:
        parts = key.split(".")
        if len(parts) == 3:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            if isinstance(claims, dict) and claims.get("role") == "anon":
                return ""
    except (ValueError, UnicodeError):
        pass
    return "В SUPABASE_KEY укажите публичный publishable или anon key. Серверные секретные ключи запрещены."


def _configuration_error() -> str:
    if not isinstance(SUPABASE_URL, str) or not isinstance(SUPABASE_KEY, str):
        return "SUPABASE_URL и SUPABASE_KEY в config.json должны быть строками."
    if not SUPABASE_URL.strip() or not SUPABASE_KEY.strip():
        return _config_error or "Настройте Supabase: заполните SUPABASE_URL и SUPABASE_KEY в .env. Прежний config.json также поддерживается."
    # Заглушки ожидаемы до ручной настройки: не пытаемся отправлять их на сервер.
    if SUPABASE_URL.strip().startswith("ВСТАВЬ_СЮДА_") or SUPABASE_KEY.strip().startswith("ВСТАВЬ_СЮДА_"):
        return "Подключение пока не настроено. Замените заглушки SUPABASE_URL и SUPABASE_KEY в .env своими значениями."
    try:
        address = urlparse(SUPABASE_URL.strip())
        local = address.hostname in {"localhost", "127.0.0.1", "::1"}
        valid_scheme = address.scheme == "https" or (address.scheme == "http" and local)
        if (not valid_scheme or not address.hostname or address.username or address.password
                or address.query or address.fragment or address.path not in {"", "/"}):
            return "Проверьте SUPABASE_URL: нужен адрес проекта Supabase, начинающийся с https://."
    except ValueError:
        return "Проверьте адрес проекта в SUPABASE_URL."
    return _public_key_error(SUPABASE_KEY.strip())


def _friendly_error(error: Exception) -> str:
    # Никогда не передаём str(error) в интерфейс: там могут оказаться адреса
    # или служебные данные. Серверный текст используем только для сравнения.
    code = str(getattr(error, "code", "")).lower()
    message = str(error).lower()
    status = str(getattr(error, "status", getattr(error, "status_code", "")))
    if code in {"invalid_credentials", "user_not_found"} or "invalid login credentials" in message:
        return "Неверный логин или пароль."
    if code in {"user_already_exists", "email_exists"} or "already registered" in message or "already exists" in message:
        return "Этот логин уже занят. Выберите другой или войдите в аккаунт."
    if status == "429" or "rate_limit" in code or "rate limit" in message or "too many requests" in message:
        return "Слишком много попыток. Подождите немного и попробуйте снова."
    if code == "email_not_confirmed" or "email not confirmed" in message:
        return "Аккаунт ожидает подтверждения. Для этого проекта отключите Confirm email в настройках Supabase Auth."
    if code in {"weak_password", "validation_failed"} and ("password" in message or code == "weak_password"):
        return "Пароль отклонён сервером. Проверьте, что Supabase разрешает пароли длиной 6 символов, или выберите более сложный пароль."
    if code in {"signup_disabled", "email_provider_disabled"}:
        return "Регистрация отключена в Supabase. Проверьте настройки провайдера Email и разрешение регистрации."
    if code == "captcha_failed":
        return "Сервер требует CAPTCHA. Проверьте настройки защиты Supabase для учебного приложения."
    if "invalid api key" in message or status == "401":
        return "Не удалось подключиться к Supabase. Проверьте адрес проекта и публичный ключ."
    if (isinstance(error, (httpx.TransportError, ConnectionError, TimeoutError))
            or "timeout" in message or "timed out" in message or "connection" in message):
        return "Нет соединения с Supabase. Проверьте интернет и повторите попытку."
    return "Не удалось выполнить запрос к Supabase. Попробуйте позже и проверьте настройки проекта."


class AuthService:
    """Один сервис передаётся между окнами; сеть вызывается в рабочем потоке."""

    def __init__(self, client=None):
        # Клиент создаём только по первому запросу, поэтому окно открывается
        # даже без настроенного Supabase. Подставной клиент нужен для тестов.
        self._client = client
        self._injected_client = client is not None

    def configuration_error(self) -> str:
        return "" if self._injected_client else _configuration_error()

    @property
    def configured(self) -> bool:
        return not self.configuration_error()

    def _create_client(self, auto_refresh_token: bool = True):
        error = self.configuration_error()
        if error:
            raise AuthError(error)
        transport = httpx.Client(timeout=15.0)
        try:
            return create_client(
                SUPABASE_URL.strip(),
                SUPABASE_KEY.strip(),
                options=ClientOptions(
                    persist_session=False,
                    auto_refresh_token=auto_refresh_token,
                    httpx_client=transport,
                ),
            )
        except Exception:
            transport.close()
            raise AuthError("Не удалось создать подключение. Проверьте настройки Supabase.") from None

    def sign_up(self, username: str, password: str):
        username = validate_username(username)
        validate_password(password)
        # Регистрация может автоматически создать сессию. Отдельный клиент
        # не даст этой сессии заменить обычный вход пользователя.
        client = self._client if self._injected_client else self._create_client(auto_refresh_token=False)
        try:
            response = client.auth.sign_up({
                "email": f"{username}@gesturecontrol.local",
                "password": password,
                "options": {"data": {"username": username}},
            })
            user = response.user
            if user is None:
                raise AuthError("Supabase не вернул аккаунт. Проверьте настройки регистрации.")
            if getattr(user, "identities", None) == []:
                raise AuthError("Этот логин уже занят. Выберите другой или войдите в аккаунт.")
            if response.session is None:
                raise AuthError("Аккаунт создан, но требует подтверждения. Отключите Confirm email в Supabase Auth; уже созданный аккаунт подтвердите в панели проекта.")
            return user
        except AuthError:
            raise
        except Exception as error:
            raise AuthError(_friendly_error(error)) from None
        finally:
            # Успешно созданный аккаунт не превращаем в ошибку регистрации,
            # если сеть пропала именно во время очистки временной сессии.
            try:
                client.auth.sign_out({"scope": "local"})
            except Exception:
                pass
            if not self._injected_client:
                try:
                    client.auth.close()
                except Exception:
                    pass

    def sign_in(self, username: str, password: str):
        username = validate_username(username)
        validate_password(password)
        if self._client is None:
            self._client = self._create_client()
        try:
            # Создаём технический адрес только внутри сетевого слоя.
            response = self._client.auth.sign_in_with_password({
                "email": f"{username}@gesturecontrol.local",
                "password": password,
            })
            if response.user is None or response.session is None:
                raise AuthError("Сервер не создал сессию. Повторите вход.")
            # Дополнительно проверяем текущую сессию на сервере, а не только ответ входа.
            user = self.get_current_user()
            if user.id != response.user.id:
                raise AuthError("Пользователь текущей сессии отличается от пользователя входа. Войдите заново.")
            return user
        except AuthError:
            raise
        except Exception as error:
            log_error("Auth", "sign_in_with_password", error)
            raise AuthError(_friendly_error(error)) from None

    def get_current_user(self):
        if self._client is None:
            raise AuthError("Нет активной сессии. Выполните вход.")
        try:
            response = self._client.auth.get_user()
            user = getattr(response, "user", None)
            if user is None or not getattr(user, "id", None):
                raise AuthError("Supabase не подтвердил пользователя текущей сессии. Войдите заново.")
            logging.getLogger("Auth").info("user_id = %s (get_user подтверждён)", user.id)
            return user
        except AuthError as error:
            log_error("Auth", "get_user", error)
            raise
        except Exception as error:
            log_error("Auth", "get_user", error)
            raise AuthError(_friendly_error(error)) from None

    def sign_out(self) -> None:
        if self._client is None:
            return
        try:
            # Выходим только из текущей сессии приложения.
            self._client.auth.sign_out({"scope": "local"})
        except Exception as error:
            raise AuthError(_friendly_error(error)) from None
        if not self._injected_client:
            # Сессия уже завершена; ошибка закрытия транспорта не отменяет выход.
            try:
                self._client.auth.close()
            except Exception:
                pass
            self._client = None


def get_supabase_client() -> Client:
    """Создаём клиент по настройкам .env, не выполняя вход и сетевые запросы."""
    # Клиент создаётся при вызове функции, а не при импорте файла.
    # Поэтому незаполненный .env не мешает открывать существующий интерфейс.
    return AuthService()._create_client()


def check_connection() -> int:
    """Проверка из терминала: без регистрации, входа и изменения данных."""
    error = _configuration_error()
    if error:
        # Пока стоят заглушки, это только подсказка о ручной настройке.
        print(error)
        return 0

    supabase = None
    try:
        # Проверяем создание клиента Supabase с публичным ключом.
        supabase = get_supabase_client()
        # Проверяем доступность сервера через служебный запрос только для чтения.
        # В консоль не выводим ни URL, ни ключ, ни тело ответа.
        with httpx.Client(timeout=15.0) as connection:
            response = connection.get(
                SUPABASE_URL.strip().rstrip("/") + "/auth/v1/health",
                headers={"apikey": SUPABASE_KEY.strip()},
            )
        if response.status_code == 200:
            print("Подключение к Supabase проверено. Клиент создан, сервер доступен.")
            return 0
        print(f"Supabase вернул HTTP {response.status_code}. Проверьте URL, публичный ключ и состояние проекта.")
        return 1
    except AuthError as error:
        print(str(error))
        return 1
    except httpx.HTTPError:
        print("Не удалось связаться с Supabase. Проверьте интернет и настройки подключения.")
        return 1
    finally:
        if supabase is not None:
            try:
                supabase.auth.close()
            except Exception:
                # Ошибка освобождения ресурсов не раскрывает служебные данные.
                pass


if __name__ == "__main__":
    raise SystemExit(check_connection())
