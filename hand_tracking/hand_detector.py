"""MediaPipe и оценка положения кисти. Модуль не зависит от интерфейса Qt."""

from math import hypot
from pathlib import Path
import gzip
import time


MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
FINGERTIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}
# Пороги в долях кадра: это оценка видимости кисти, а не расстояние в сантиметрах.
HAND_FRAME_MARGIN = 0.025
MIN_HAND_SIZE = 0.23
MAX_HAND_SIZE = 0.85
MAX_WRIST_MOVEMENT = 0.035
STABLE_HAND_FRAMES = 4
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
    (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)


def empty_hand(hint="Рука не обнаружена"):
    return {"found": False, "count": 0, "handedness": None, "landmarks": [],
            "bbox": None, "fingertips": {}, "size": 0.0, "hint": hint,
            "ready": False, "confidence": 0.0}


def describe_hand(landmarks, handedness=None, confidence=1.0, count=1):
    """Оцениваем размер в долях кадра, без попыток получить сантиметры."""
    if len(landmarks) != 21:
        return empty_hand()
    points = [[float(p[0]), float(p[1]), float(p[2])] for p in landmarks]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    bbox = [min(xs), min(ys), max(xs), max(ys)]
    size = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    ready = False
    if count != 1:
        hint = "Покажите одну руку"
    elif min(bbox[:2]) < HAND_FRAME_MARGIN or max(bbox[2:]) > 1 - HAND_FRAME_MARGIN:
        hint = "Поместите всю кисть в кадр"
    elif size < MIN_HAND_SIZE:
        hint = "Поднесите руку ближе"
    elif size > MAX_HAND_SIZE:
        hint = "Отодвиньте руку немного дальше"
    else:
        hint, ready = "Отлично, рука обнаружена", True
    return {"found": True, "count": count, "handedness": handedness,
            "landmarks": points, "bbox": bbox, "size": size, "hint": hint,
            "ready": ready, "confidence": float(confidence),
            "fingertips": {name: points[index] for name, index in FINGERTIPS.items()}}


class HandDetector:
    """Создаётся, используется и закрывается только внутри потока камеры."""

    def __init__(self, model_path=None):
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise RuntimeError("Установите MediaPipe: python -m pip install mediapipe") from exc
        self._mp = mp
        self._timestamp_ms = -1
        self._previous = None
        self._stable_frames = 0
        model_path = Path(model_path) if model_path else MODEL_PATH
        compressed_path = model_path.with_suffix(model_path.suffix + ".gz")
        self._legacy = not model_path.is_file() and not compressed_path.is_file() and hasattr(mp, "solutions")
        if self._legacy:
            self._detector = mp.solutions.hands.Hands(
                max_num_hands=2, model_complexity=1,
                min_detection_confidence=0.6, min_tracking_confidence=0.6)
        elif model_path.is_file() or compressed_path.is_file():
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            # Сжатая модель распаковывается в память, не занимая дополнительное место на диске.
            base_options = (python.BaseOptions(model_asset_path=str(model_path.resolve())) if model_path.is_file()
                            else python.BaseOptions(model_asset_buffer=gzip.decompress(compressed_path.read_bytes())))
            options = vision.HandLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO, num_hands=2,
                min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.6, min_tracking_confidence=0.6)
            self._detector = vision.HandLandmarker.create_from_options(options)
        else:
            raise RuntimeError("Не найдена модель MediaPipe: hand_tracking/models/hand_landmarker.task. "
                               "Скачайте официальную модель по инструкции README.")

    def detect(self, rgb_frame, timestamp=None):
        # Получаем 21 ключевую точку руки; второй результат нужен для запрета двух рук.
        if self._legacy:
            result = self._detector.process(rgb_frame)
            hands = result.multi_hand_landmarks or []
            categories = result.multi_handedness or []
            landmarks = hands[0].landmark if hands else []
            category = categories[0].classification[0] if categories else None
            side = category.label.lower() if category else None
        else:
            timestamp_ms = int((timestamp if timestamp is not None else time.monotonic()) * 1000)
            self._timestamp_ms = max(timestamp_ms, self._timestamp_ms + 1)
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
            result = self._detector.detect_for_video(image, self._timestamp_ms)
            hands = result.hand_landmarks or []
            landmarks = hands[0] if hands else []
            category = result.handedness[0][0] if result.handedness else None
            side = category.category_name.lower() if category else None
        if not hands:
            self._previous, self._stable_frames = None, 0
            return empty_hand()
        hand = describe_hand([[p.x, p.y, p.z] for p in landmarks], side,
                             category.score if category else 1.0, len(hands))
        wrist = hand["landmarks"][0]
        movement = (hypot(wrist[0] - self._previous[0], wrist[1] - self._previous[1])
                    if self._previous else 1.0)
        self._previous = wrist
        self._stable_frames = self._stable_frames + 1 if movement < MAX_WRIST_MOVEMENT else 0
        # Движению нужна качественная рука, но не неподвижность запястья.
        hand["motion_ready"] = hand["ready"]
        if hand["ready"] and self._stable_frames < STABLE_HAND_FRAMES:
            hand.update(ready=False, hint="Держите руку неподвижно")
        return hand

    def close(self):
        self._detector.close()
