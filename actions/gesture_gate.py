"""Удержание, отпускание и повтор жеста: чистая логика без Qt и команд Windows."""

from math import isfinite
import time

from actions.action_settings import action_parameters


class GestureGate:
    """После команды нужна другая поза/отсутствие руки не менее release_time."""

    def __init__(self, release_time=0.25):
        self.release_time = release_time
        self.reset()

    def reset(self):
        self._candidate = None
        self._candidate_since = None
        self._latched = None
        self._release_since = None
        self._last_trigger = float("-inf")
        self._cooldown_until = float("-inf")
        self._last_seen = None
        self._repeat_key = None
        self._repeat_at = float("inf")
        self._repeat_cooldown = 1.
        self.status = "Ожидание жеста"
        self.progress = 0.0

    def update(self, key, confidence, settings, now=None, *, confirmed_duration=0.):
        now = time.monotonic() if now is None else float(now)
        # Модель и распознаватель используют ту же шкалу 0…1, что и Supabase.
        sensitivity = settings.get("sensitivity", 0.7)
        threshold = float(sensitivity if sensitivity is not None else 0.7)
        observed_key = key
        valid = bool(key) and isfinite(float(confidence)) and confidence >= threshold and settings.get("enabled", True)
        key = key if valid else None
        self.progress = 0.0
        # Длительная потеря кадров не засчитывается как удержание неподвижного жеста.
        gap = self._last_seen is not None and (now - self._last_seen > 0.3 or now < self._last_seen)
        if gap:
            self._candidate, self._candidate_since, self._release_since = None, None, None
        self._last_seen = now
        if self._repeat_key is not None:
            # В режиме повтора действие выполняется, пока качественно распознаётся тот же жест.
            if key == self._repeat_key and settings.get("repeat_while_held") and not gap:
                if now + 1e-9 >= self._repeat_at:
                    # Интервал повтора не зависит от FPS; пропущенные команды не догоняем пачкой.
                    self._repeat_at = now + action_parameters(settings)["repeat_interval"]
                    self._last_trigger = now
                    self.status = "Выполнено действие"
                    return True
                self.status = "Ожидание следующего повтора"
                return False
            # Исчезновение/смена жеста немедленно останавливает повтор. Cooldown — перед новым циклом.
            self._repeat_key = None
            self._candidate, self._candidate_since = None, None
            self._cooldown_until = now + self._repeat_cooldown
        # Защищаем систему от повторного срабатывания даже после окончания cooldown.
        if self._latched is not None:
            if observed_key == self._latched:
                self._release_since = None
            elif self._release_since is None:
                self._release_since = now
            elif now - self._release_since >= self.release_time:
                self._latched, self._release_since = None, None
            if self._latched is not None:
                self.status = "Ожидание отпускания жеста"
                return False
        if now < self._cooldown_until:
            self._candidate, self._candidate_since = None, None
            self.status = "Пауза между действиями"
            return False
        if key is None:
            self._candidate, self._candidate_since = None, None
            self.status = ("Уверенность ниже порога: удерживайте позу чётче или уменьшите порог в настройках действия"
                           if observed_key and settings.get("enabled", True) else "Ожидание жеста")
            return False
        if key != self._candidate:
            self._candidate, self._candidate_since = key, now - confirmed_duration
        hold_time = settings.get("hold_time", 0.5)
        hold_time = max(0., float(0.5 if hold_time is None else hold_time))
        # Проверяем, достаточно ли долго удерживается жест.
        self.progress = min(1.0, (now - self._candidate_since) / hold_time if hold_time else 1.0)
        if now - self._candidate_since + 1e-9 < hold_time:
            self.status = "Удерживайте жест"
            return False
        cooldown = settings.get("cooldown", settings.get("command_pause", 1.0))
        self._last_trigger, self._latched = now, key
        if settings.get("repeat_while_held"):
            self._repeat_key, self._latched = key, None
            self._repeat_at = now + action_parameters(settings)["repeat_interval"]
            self._repeat_cooldown = max(0., float(cooldown if cooldown is not None else 1.))
        self._cooldown_until = now + max(0., float(1.0 if cooldown is None else cooldown))
        self._candidate, self._candidate_since = None, None
        self.status = "Выполнено действие"
        return True

    def trigger_motion(self, gesture, settings, now):
        # Удержанием для движения служит длительность подтверждённой последовательности.
        key = gesture["key"]
        if settings.get("repeat_while_held"):
            duration = gesture.get("duration", 0)
            confidence = gesture.get("confidence", 0) if duration >= settings["hold_time"] else 0
            return self.update(key, confidence, settings, now, confirmed_duration=duration)
        self.update(key, 0, {"enabled": False}, now)
        if (self._latched is not None or now < self._cooldown_until
                or gesture.get("duration", 0) < settings["hold_time"]
                or gesture.get("confidence", 0) < settings["sensitivity"]):
            return False
        self._latched, self._release_since = key, None
        self._cooldown_until = now + settings["cooldown"]
        self.status = "Выполнено действие"
        return True
