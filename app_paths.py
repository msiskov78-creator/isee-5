"""Разделяем ресурсы сборки, внешнюю конфигурацию и изменяемые данные пользователя."""

import os
from pathlib import Path
import sys


RESOURCE_DIRECTORY = Path(__file__).resolve().parent
APP_DIRECTORY = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else RESOURCE_DIRECTORY


def user_data_directory():
    # Не записываем логи и кэш в Program Files или во внутреннюю папку PyInstaller.
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    directory = base / "GestureControl"
    directory.mkdir(parents=True, exist_ok=True)
    return directory
