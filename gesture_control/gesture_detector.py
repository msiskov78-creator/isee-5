"""Геометрическое распознавание статических поз одной руки."""

from math import acos, degrees, dist, isfinite, sqrt


STANDARD_GESTURES = {
    "thumbs_up": "Большой палец вверх", "fist": "Кулак",
    "two_fingers": "Два пальца", "open_palm": "Открытая ладонь",
}
# Запрет сохранения только при очень близком совпадении (оценка >= 90%).
DUPLICATE_MAX_DISTANCE = 0.05


def normalize_landmarks(landmarks):
    """Перенос, масштаб, поворот в плоскости и отражение приводим к виду кисти."""
    if len(landmarks) != 21 or any(len(p) != 3 for p in landmarks):
        raise ValueError("Для записи нужны 21 трёхмерная точка руки.")
    points = [[float(v) for v in p] for p in landmarks]
    if not all(isfinite(v) for p in points for v in p):
        raise ValueError("Координаты руки должны быть конечными числами.")
    # Нормализуем координаты руки перед сохранением относительно запястья и ладони.
    wrist = points[0]
    axis = [points[9][0] - wrist[0], points[9][1] - wrist[1]]
    scale = sqrt(axis[0] ** 2 + axis[1] ** 2)
    if scale < 1e-5:
        raise ValueError("Кисть слишком мала для записи.")
    yx, yy = axis[0] / scale, axis[1] / scale
    xx, xy = yy, -yx
    side = (points[5][0] - wrist[0]) * xx + (points[5][1] - wrist[1]) * xy
    if side < 0:
        xx, xy = -xx, -xy
    values = []
    for point in points:
        x, y, z = [point[i] - wrist[i] for i in range(3)]
        values.extend(((x * xx + y * xy) / scale, (x * yx + y * yy) / scale, z / scale))
    return values


def feature_distance(first, second):
    if len(first) != 63 or len(second) != 63:
        return float("inf")
    try:
        return sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(first, second)) / 63)
    except (TypeError, ValueError):
        return float("inf")


def _angle(a, b, c):
    first, second = [a[i] - b[i] for i in range(3)], [c[i] - b[i] for i in range(3)]
    denominator = sqrt(sum(v * v for v in first) * sum(v * v for v in second))
    if denominator < 1e-9:
        return 0.0
    return degrees(acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second)) / denominator))))


def standard_gesture(hand):
    points = hand.get("landmarks", [])
    if not hand.get("found") or len(points) != 21 or hand.get("count", 1) != 1:
        return {"key": None, "name": "Ожидание жеста", "confidence": 0.0}
    # Определяем положение пальцев по сгибу суставов и расстоянию до запястья.
    fingers = []
    angles = []
    for base in (5, 9, 13, 17):
        angle = _angle(points[base], points[base + 1], points[base + 3])
        reach = dist(points[base + 3], points[0]) / max(dist(points[base + 1], points[0]), 1e-6)
        fingers.append(angle > 155 and reach > 1.12)
        angles.append(angle)
        if 145 < angle <= 155 and reach > 1.05:
            return {"key": None, "name": "Удерживайте позу чётче", "confidence": 0.0}
    thumb_angle = _angle(points[2], points[3], points[4])
    thumb_out = (thumb_angle > 150 and dist(points[4], points[17]) > dist(points[3], points[17]) * 1.10)
    thumb_up = (thumb_out and points[4][1] < points[3][1] < points[2][1]
                and (points[2][1] - points[4][1]) > abs(points[2][0] - points[4][0]) * 0.65)
    key = None
    if all(fingers) and thumb_out:
        key = "open_palm"
    elif fingers == [True, True, False, False]:
        key = "two_fingers"
    elif not any(fingers) and thumb_up:
        key = "thumbs_up"
    elif not any(fingers) and not thumb_out:
        key = "fist"
    # Это геометрическая оценка качества совпадения, а не вероятность модели.
    margins = [min(1.0, abs(angle - 150) / 30) for angle in angles]
    confidence = min(0.98, 0.78 + min(margins) * 0.20) if key else 0.0
    return {"key": key, "name": STANDARD_GESTURES.get(key, "Ожидание жеста"), "confidence": confidence}


class GestureDetector:
    def __init__(self, custom_gestures=None):
        self.configure(custom_gestures or [])

    def configure(self, custom_gestures):
        self._templates = []
        for gesture in custom_gestures:
            data = gesture.get("gesture_data") or {}
            if data.get("recognition_type", gesture.get("recognition_type", "static")) != "static":
                continue
            template = data.get("template", []) if isinstance(data, dict) else []
            samples = data.get("samples", []) if data.get("version", 1) >= 2 else [template]
            valid = [sample for sample in samples if isinstance(sample, list) and len(sample) == 63
                     and all(type(v) in (int, float) and isfinite(v) for v in sample)]
            if valid and gesture.get("id") and gesture.get("name"):
                self._templates.append((str(gesture.get("key") or gesture["id"]), str(gesture["name"]), valid))

    def detect(self, hand):
        if not hand.get("found") or hand.get("count", 1) != 1:
            return {"key": None, "name": "Ожидание жеста", "confidence": 0.0}
        try:
            features = normalize_landmarks(hand.get("landmarks", []))
        except (TypeError, ValueError):
            return {"key": None, "name": "Ожидание жеста", "confidence": 0.0}
        # Достаточно совпасть с одним вариантом, не со всеми углами сразу.
        matches = sorted((min(feature_distance(features, sample) for sample in samples), key, name)
                         for key, name, samples in self._templates)
        if matches and matches[0][0] < 0.16:
            distance, key, name = matches[0]
            if len(matches) == 1 or matches[1][0] - distance > 0.025:
                return {"key": key, "name": name, "confidence": max(0.0, 1.0 - distance / 0.5)}
        return standard_gesture(hand)

    def find_similar(self, gesture_data, samples=None):
        """Не разрешаем записать вторую копию стандартной или пользовательской позы."""
        key = gesture_data.get("standard_key")
        if key in STANDARD_GESTURES:
            return {"key": key, "name": STANDARD_GESTURES[key], "confidence": 1.0}
        template = gesture_data.get("template", [])
        candidates = gesture_data.get("samples", [template]) if gesture_data.get("version", 1) >= 2 else [template]
        matches = sorted((min(feature_distance(sample, other) for sample in candidates for other in samples), key, name)
                         for key, name, samples in self._templates)
        if matches and matches[0][0] < DUPLICATE_MAX_DISTANCE:
            distance, key, name = matches[0]
            return {"key": key, "name": name, "confidence": max(0.0, 1.0 - distance / 0.5)}
        return None
