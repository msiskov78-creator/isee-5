"""Ограниченная история движения и нормализованное расстояние pinch."""

from collections import deque
from math import dist, isfinite, sqrt

MIN_PINCH, MAX_PINCH = .15, 1.3


def pinch_distance(landmarks):
    if len(landmarks) != 21 or any(len(p) != 3 for p in landmarks):
        raise ValueError("Нужны 21 landmark.")
    if not all(isfinite(v) for p in landmarks for v in p):
        raise ValueError("Некорректные координаты.")
    scale = dist(landmarks[0], landmarks[9])
    if scale < 1e-5:
        raise ValueError("Кисть слишком мала.")
    # Нормализуем расстояние между большим и указательным пальцами размером ладони.
    return dist(landmarks[4], landmarks[8]) / scale


def pinch_to_volume(distance):
    return max(0., min(1., (distance - MIN_PINCH) / (MAX_PINCH - MIN_PINCH)))


def motion_frame(hand):
    points = hand["landmarks"]
    scale = dist(points[0], points[9])
    pinch = pinch_distance(points)
    return [points[0][0], points[0][1], scale, pinch]


def resample(points, count=24):
    if len(points) < 2:
        raise ValueError("Недостаточно кадров движения.")
    result = []
    for i in range(count):
        position = i * (len(points) - 1) / (count - 1)
        left = min(int(position), len(points) - 2)
        fraction = position - left
        result.append([a + (b - a) * fraction for a, b in zip(points[left], points[left + 1])])
    return result


def normalize_trajectory(frames, dynamic_type="trajectory"):
    if len(frames) < 2 or any(len(f) != 4 or not all(isfinite(v) for v in f) for f in frames):
        raise ValueError("Некорректная последовательность движения.")
    if dynamic_type == "pinch":
        values = [[f[3] - frames[0][3]] for f in frames]
        extent = max(abs(p[0]) for p in values)
        if extent < .25:
            raise ValueError("Разведите или сомкните пальцы заметнее.")
    else:
        scale = max(sum(f[2] for f in frames) / len(frames), 1e-5)
        values = [[(f[0] - frames[0][0]) / scale, (f[1] - frames[0][1]) / scale] for f in frames]
        extent = max(sqrt(sum(v*v for v in p)) for p in values)
        if extent < .45:
            raise ValueError("Переместите руку заметнее.")
    # Сохраняем направление, убирая зависимость от начального положения и размаха.
    return resample([[v / extent for v in p] for p in values])


def trajectory_similarity(first, second):
    if len(first) != len(second) or not first or len(first[0]) != len(second[0]):
        return 0.
    error = sqrt(sum((a-b)**2 for p, q in zip(first, second) for a, b in zip(p, q)) / (len(first)*len(first[0])))
    return max(0., 1. - error)


class DynamicGestureDetector:
    def __init__(self, gestures=()):
        self.history = deque(maxlen=40)
        self.configure(gestures)

    def configure(self, gestures):
        self.templates = []
        self.history.clear()
        for gesture in gestures:
            data = gesture.get("gesture_data") or {}
            if data.get("recognition_type", gesture.get("recognition_type")) != "dynamic":
                continue
            kind = data.get("dynamic_type", "trajectory")
            for sample in data.get("samples", []):
                try:
                    self.templates.append((gesture, kind, normalize_trajectory(sample.get("motion_frames", sample["frames"]), kind)))
                except (ValueError, TypeError, KeyError):
                    continue

    def update(self, hand, now):
        # Анализируем последовательность кадров динамического жеста, не отдельную позу.
        if not hand.get("motion_ready", hand.get("ready")) or hand.get("count", 1) != 1:
            self.history.clear()
            return []
        if self.history and (now - self.history[-1][0] > .3 or now <= self.history[-1][0]):
            self.history.clear()
        try:
            self.history.append((now, motion_frame(hand)))
        except (ValueError, TypeError, KeyError):
            self.history.clear()
            return []
        if len(self.history) < 20:
            return []
        matches = {}
        # Несколько длин окна допускают разную скорость выполнения.
        for length in (20, 30, 40):
            if len(self.history) < length:
                continue
            window = list(self.history)[-length:]
            duration = now - window[0][0]
            if not .5 <= duration <= 3:
                continue
            for gesture, kind, template in self.templates:
                try:
                    confidence = trajectory_similarity(normalize_trajectory([f for _, f in window], kind), template)
                except ValueError:
                    continue
                if confidence >= .75 and confidence > matches.get(gesture["key"], {}).get("confidence", 0):
                    matches[gesture["key"]] = {"key": gesture["key"], "name": gesture["name"],
                        "confidence": confidence, "duration": duration, "recognition_type": "dynamic"}
        return sorted(matches.values(), key=lambda item: item["confidence"], reverse=True)


class PinchControl:
    """Активация удержанием сомкнутых пальцев; фильтр и предел 10 обновлений/с."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.since = self.last_seen = self.missing_since = None
        self.value = self.sent = None
        self.last_update = float("-inf")

    def update(self, hand, now, *, smoothing=.3, minimum=MIN_PINCH, maximum=MAX_PINCH):
        if self.last_seen is not None and (now - self.last_seen > .3 or now < self.last_seen):
            self.reset()
        self.last_seen = now
        try:
            points = hand["landmarks"]
            # Кулак не включает регулировку: нужны хотя бы два раскрытых остальных пальца.
            pose_ok = sum(dist(points[t], points[0]) > dist(points[t-2], points[0])*1.1 for t in (12,16,20)) >= 2
            valid = hand.get("motion_ready", hand.get("ready")) and hand.get("count", 1) == 1 and pose_ok
            distance = pinch_distance(points) if valid else None
        except (KeyError, ValueError, TypeError, IndexError):
            distance = None
        if distance is None:
            self.since = None
            self.missing_since = now if self.missing_since is None else self.missing_since
            if now - self.missing_since >= .35:
                self.reset()
            return None
        self.missing_since = None
        if not self.active:
            if distance > .25:
                self.since = None
                return None
            self.since = now if self.since is None else self.since
            if now - self.since < .5:
                return None
            self.active = True
        raw = max(0., min(1., (distance - minimum) / (maximum - minimum)))
        # Сглаживаем значение, чтобы громкость не дрожала, независимо от частоты кадров.
        self.value = raw if self.value is None else self.value * (1 - smoothing) + raw * smoothing
        if now - self.last_update < .1 or (self.sent is not None and abs(self.value - self.sent) < .025):
            return None
        if self.sent is not None:
            self.value = max(self.sent - .04, min(self.sent + .04, self.value))
        self.sent, self.last_update = self.value, now
        return self.value
