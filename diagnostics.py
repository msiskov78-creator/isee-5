"""Диагностика этапов без вывода паролей, заголовков запросов и сессий."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import traceback


COMPONENTS = ("Auth", "Profile", "Settings", "Profiles", "Database", "Camera", "Gesture",
              "Gestures", "DynamicGesture", "Actions", "Action")


class ComponentFormatter(logging.Formatter):
    def format(self, record):
        suffix = "" if record.levelno == logging.INFO else " " + record.levelname
        name = {"Database": "DB", "Settings": "SETTINGS"}.get(record.name, record.name) if record.levelno >= logging.ERROR else record.name
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info))
        return f"[{name}{suffix}] {error_text(message)}"


class FileFormatter(ComponentFormatter):
    def format(self, record):
        return f"{self.formatTime(record)} pid={record.process} {super().format(record)}"


def setup_logging(log_directory=None):
    for name in COMPONENTS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(ComponentFormatter())
            logger.addHandler(handler)
        logger.propagate = False
    if log_directory is None:
        return None
    path = Path(log_directory).resolve() / "gesture_control.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = next((h for h in logging.getLogger("Actions").handlers
                        if isinstance(h, RotatingFileHandler) and h.baseFilename == str(path)), None)
        if handler is None:
            # Ограничиваем размер журнала; он доступен и после закрытия консоли.
            handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            handler.setFormatter(FileFormatter())
        for name in COMPONENTS:
            logging.getLogger(name).addHandler(handler)
    except OSError as error:
        log_error("Actions", "Не удалось открыть журнал диагностики", error)
        return None
    return path


def error_text(error):
    # Серверный текст сохраняем, удаляя лишь возможные секреты из нестандартных ошибок.
    text = str(error)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[JWT скрыт]", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s,'\"}]+", r"\1[скрыто]", text)
    text = re.sub(r"(?i)((?:access_token|refresh_token|password|apikey|token)[\"']?\s*[:=]\s*[\"']?)[^\s,'\"}]+",
                  r"\1[скрыто]", text)
    return text


def log_error(component, operation, error):
    logging.getLogger(component).error("%s: %s: %s", operation, type(error).__name__, error_text(error))
