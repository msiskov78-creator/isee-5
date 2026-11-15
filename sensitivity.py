"""Единицы чувствительности: в модели и БД — 0…1, проценты — только в UI."""

from math import isfinite
from diagnostics import log_error


def validate_sensitivity(value, *, nullable=False, source="sensitivity"):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        error = ValueError(f"{source}: ожидалось число от 0.0 до 1.0, получено {value!r}.")
        log_error("Settings", "Проверка чувствительности", error)
        raise error
    return float(value)


def sensitivity_to_percent(value):
    # Проценты нужны только слайдерам и подписям интерфейса.
    return round(validate_sensitivity(value) * 100)


def sensitivity_from_percent(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("Чувствительность в интерфейсе должна быть от 0 до 100%.")
    return value / 100.0
