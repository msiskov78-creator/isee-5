"""Пять движений: положение руки, явный старт, отсчёт и запись последовательности."""

import logging
from math import ceil
from diagnostics import log_error
from gesture_control.gesture_detector import normalize_landmarks
from gesture_control.dynamic_gesture_detector import motion_frame, normalize_trajectory, resample, trajectory_similarity

logger = logging.getLogger("DynamicGesture")


class DynamicGestureRecorder:
    def __init__(self, dynamic_type="trajectory"):
        self.dynamic_type = dynamic_type
        self.reset()

    def reset(self):
        self.examples = []
        self.wait_release = False
        self.restart_current()

    def start(self):
        self.reset()

    def restart_current(self):
        self.frames = []
        self.landmark_frames = []
        self.prepared_at = None
        self.recording_at = None
        self.last_sample_at = None
        self.last_frame_at = None
        self.ready = False
        self.hint = "Покажите руку"

    def begin_countdown(self, now):
        if not self.ready or self.wait_release or self.complete:
            return False
        self.prepared_at = now
        self.ready = False
        self.hint = "Подготовка к записи · 3"
        logger.info("Начало countdown")
        return True

    @property
    def complete(self):
        return len(self.examples) >= 5

    @property
    def progress(self):
        return min(1., (len(self.examples) + min(1., len(self.frames)/30)) / 5)

    def add_sample(self, hand, now):
        if self.complete:
            return 1.
        if self.wait_release:
            self.hint = f"Пример {len(self.examples)} из 5 сохранён. Уберите руку"
            if not hand.get("found"):
                self.wait_release = False
                self.restart_current()
                self.hint = "Покажите жест снова"
            return self.progress
        if self.last_frame_at is not None and (now - self.last_frame_at > 1. + 1e-9 or now < self.last_frame_at):
            self.restart_current()
            logger.warning("Поток кадров прерван; текущий пример сброшен")
        self.last_frame_at = now
        if (not hand.get("found") or not hand.get("motion_ready", hand.get("ready"))
                or hand.get("count", 1) != 1):
            self.restart_current()
            self.hint = hand.get("hint") or "Рука не обнаружена"
            return self.progress
        try:
            # Проверяем реальные landmarks, не имя и не уверенность статического жеста.
            frame = motion_frame(hand)
            landmarks = normalize_landmarks(hand["landmarks"])
            if self.prepared_at is None:
                if not self.ready:
                    logger.info("Готов к записи")
                self.ready = True
                self.hint = "Положение подходит"
                return self.progress
            remaining = 3 - (now - self.prepared_at)
            if remaining > 1e-9:
                self.hint = f"Подготовка к записи · {min(3, ceil(remaining))}"
                return self.progress
            if self.recording_at is None:
                self.recording_at = now
                logger.info("Запись началась")
            # Ограничиваем частоту: 30 кадров охватывают примерно полторы секунды движения.
            if self.last_sample_at is None or now - self.last_sample_at >= .05 - 1e-9:
                if len(self.frames) < 30:
                    self.frames.append(frame)
                    self.landmark_frames.append(landmarks)
                    self.last_sample_at = now
                    logger.info("frame %s/30", len(self.frames))
            self.hint = f"Запись {len(self.examples)+1}/5 · Выполните движение"
            duration = now - self.recording_at
            if duration < 1.5 or (len(self.frames) < 30 and duration < 2.):
                return self.progress
            if len(self.frames) < 20:
                raise ValueError("Слишком мало кадров за 2 секунды. Повторите запись")
            normalized = normalize_trajectory(self.frames, self.dynamic_type)
            if self.examples and trajectory_similarity(normalized, normalize_trajectory(self.examples[0]["motion_frames"], self.dynamic_type)) < .65:
                raise ValueError("Направление отличается. Повторите то же движение")
            origin, scale = self.frames[0], sum(f[2] for f in self.frames)/len(self.frames)
            motion = resample([[(f[0]-origin[0])/scale, (f[1]-origin[1])/scale, 1., f[3]] for f in self.frames], 30)
            self.examples.append({"frames": resample(self.landmark_frames, 30), "motion_frames": motion,
                                  "pinch": [f[3] for f in motion], "trajectory": [f[:2] for f in motion]})
            logger.info("Запись завершена: пример %s/5", len(self.examples))
            self.frames = []
            self.landmark_frames = []
            self.wait_release = True
            self.hint = f"Пример {len(self.examples)} из 5 сохранён. Уберите руку"
        except (ValueError, TypeError, KeyError, IndexError) as error:
            log_error("DynamicGesture", "Запись движения", error)
            self.restart_current()
            self.hint = str(error)
        return self.progress

    def gesture_data(self):
        if not self.complete:
            raise ValueError("Запишите пять вариантов движения.")
        return {"version": 3, "recognition_type": "dynamic", "dynamic_type": self.dynamic_type,
                "samples": self.examples}
