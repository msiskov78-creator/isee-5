"""Подготовка пользовательского кэша до импорта сторонних библиотек."""

import os
from pathlib import Path
import sys

base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "GestureControl"
base.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(base / "matplotlib"))
# В windowed-режиме потоки отсутствуют; библиотеки иногда вызывают write/flush напрямую.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(base / "native-errors.log", "a", encoding="utf-8", buffering=1)

# Предотвращаем создание comtypes/gen внутри каталога установки.
import comtypes
import types
cache = base / "comtypes_cache"
cache.mkdir(parents=True, exist_ok=True)
generated = types.ModuleType("comtypes.gen")
generated.__path__ = [str(cache)]
generated.__package__ = "comtypes.gen"
sys.modules["comtypes.gen"] = generated
comtypes.gen = generated
