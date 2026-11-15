"""Параметры исполнения назначения; расширяются независимо от распознавателя."""

from enum import Enum
from math import isfinite
from actions.action_types import ACTION_KEYS, CONTINUOUS_ACTIONS, is_dangerous

ACTION_DEFAULTS = {"repeat_while_held": False, "repeat_interval": .5, "volume_step": 5,
                   "scroll_step": 3, "pinch_smoothing": .3, "pinch_min": .15, "pinch_max": 1.3}


class ExecutionMode(Enum):
    ONE_SHOT = "one_shot"
    REPEAT_WHILE_HELD = "repeat_while_held"
    CONTINUOUS = "continuous"


def execution_mode(action, settings):
    if is_dangerous(action, settings.get("action_value", "")):
        return ExecutionMode.ONE_SHOT
    if ACTION_KEYS.get(action, action) == "set_volume" and settings.get("action_value"):
        return ExecutionMode.REPEAT_WHILE_HELD if settings.get("repeat_while_held") else ExecutionMode.ONE_SHOT
    if ACTION_KEYS.get(action, action) in CONTINUOUS_ACTIONS:
        return ExecutionMode.CONTINUOUS
    return ExecutionMode.REPEAT_WHILE_HELD if settings.get("repeat_while_held") else ExecutionMode.ONE_SHOT


def action_parameters(values):
    result = {key: values[key] if values.get(key) is not None else default
              for key, default in ACTION_DEFAULTS.items()}
    if type(result["repeat_while_held"]) is not bool:
        raise ValueError("Повтор при удержании должен быть логическим значением.")
    interval = result["repeat_interval"]
    if type(interval) not in (int, float) or not isfinite(interval) or interval < 0:
        raise ValueError("Интервал повтора должен быть конечным неотрицательным числом.")
    step = result["volume_step"]
    if type(step) is not int or not 1 <= step <= 25:
        raise ValueError("Шаг громкости должен быть целым числом от 1 до 25%.")
    if type(result["scroll_step"]) is not int or not 1 <= result["scroll_step"] <= 10:
        raise ValueError("Шаг прокрутки должен быть целым числом от 1 до 10.")
    for key, low, high in (("pinch_smoothing", .05, 1.), ("pinch_min", .05, 2.), ("pinch_max", .1, 3.)):
        if type(result[key]) not in (int, float) or not low <= result[key] <= high:
            raise ValueError(f"{key}: допустимый диапазон {low}–{high}.")
    if result["pinch_min"] >= result["pinch_max"]:
        raise ValueError("Минимальное расстояние pinch должно быть меньше максимального.")
    return result
