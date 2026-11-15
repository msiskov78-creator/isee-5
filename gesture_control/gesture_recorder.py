"""Запись нескольких устойчивых образцов одной статической позы."""

from collections import Counter
from gesture_control.gesture_detector import feature_distance, normalize_landmarks, standard_gesture


class GestureRecorder:
    def __init__(self, target_samples=40):
        self.target_samples = max(20, min(50, int(target_samples)))
        self.reset()

    def reset(self):
        self._samples = []
        self._standard_keys = []
        self._active = False
        self.hint = "Покажите одну руку"

    def start(self):
        self.reset()
        self._active = True

    @property
    def progress(self):
        return len(self._samples) / self.target_samples

    @property
    def complete(self):
        return len(self._samples) >= self.target_samples

    def add_sample(self, hand, now=None):
        if not self._active or self.complete:
            return self.progress
        if not hand.get("found") or not hand.get("ready") or hand.get("count", 1) != 1:
            # Прерванную запись начинаем заново, чтобы не смешать разные позы.
            self._samples.clear()
            self._standard_keys.clear()
            self.hint = hand.get("hint", "Покажите одну руку")
            return self.progress
        try:
            features = normalize_landmarks(hand.get("landmarks", []))
        except (TypeError, ValueError) as exc:
            self.hint = str(exc)
            return self.progress
        if self._samples and feature_distance(features, self._samples[0]) > 0.12:
            self._samples.clear()
            self._standard_keys.clear()
            self.hint = "Поза изменилась. Держите жест неподвижно"
        else:
            self.hint = "Готово. Удерживайте жест..."
        # Записываем несколько образцов пользовательского жеста, а не один кадр.
        self._samples.append(features)
        self._standard_keys.append(standard_gesture(hand)["key"])
        if self.complete:
            self._active = False
            self.hint = "Жест успешно записан"
        return self.progress

    def gesture_data(self):
        if not self.complete:
            raise ValueError("Сначала завершите запись устойчивой позы.")
        template = [round(sum(column) / len(self._samples), 6) for column in zip(*self._samples)]
        key, count = Counter(self._standard_keys).most_common(1)[0]
        return {"version": 1, "type": "static", "template": template,
                "samples": [[round(v, 6) for v in sample] for sample in self._samples],
                "standard_key": key if count / self.target_samples >= 0.7 else None}


class MultiStaticRecorder:
    """Пять независимых удержаний, каждое усредняет 25 качественных кадров."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.examples = []
        self.current = GestureRecorder(25)
        self.wait_release = False
        self.hint = "Покажите жест снова"

    def start(self):
        self.reset()
        self.current.start()

    def restart_current(self):
        self.current.start()

    @property
    def complete(self):
        return len(self.examples) >= 5

    @property
    def progress(self):
        return min(1., (len(self.examples) + (0 if self.wait_release else self.current.progress)) / 5)

    def add_sample(self, hand, now=None):
        if self.complete:
            return 1.
        if self.wait_release:
            self.hint = "Уберите руку"
            if not hand.get("found"):
                self.wait_release = False
                self.current.start()
                self.hint = "Покажите жест снова"
            return self.progress
        self.current.add_sample(hand)
        self.hint = f"Пример {len(self.examples)+1} из 5 · {self.current.hint}"
        if self.current.complete:
            data = self.current.gesture_data()
            # Сохраняем несколько вариантов одного статического жеста.
            if self.examples and feature_distance(data["template"], self.examples[0]["template"]) > .3:
                self.current.start()
                self.hint = "Поза слишком отличается. Повторите тот же жест"
                return self.progress
            self.examples.append(data)
            self.wait_release = True
            self.hint = "Готово" if self.complete else "Уберите руку"
        return self.progress

    def gesture_data(self):
        if not self.complete:
            raise ValueError("Запишите пять вариантов жеста.")
        samples = [item["template"] for item in self.examples]
        standard_keys = [item["standard_key"] for item in self.examples]
        return {"version": 2, "recognition_type": "static", "samples": samples,
                "template": [sum(column)/5 for column in zip(*samples)],
                "standard_key": standard_keys[0] if len(set(standard_keys)) == 1 else None}
