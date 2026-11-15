"""Связываем распознавание, активный профиль и безопасное выполнение действия."""

from PySide6.QtCore import QObject, Signal

from actions.action_executor import ActionExecutor
from actions.gesture_gate import GestureGate
from actions.action_types import ACTION_KEYS
from gesture_control.dynamic_gesture_detector import PinchControl
from diagnostics import log_error
from actions.action_settings import execution_mode, ExecutionMode
import time
import logging

logger = logging.getLogger("Actions")


class ControlRuntime(QObject):
    changed = Signal()
    status_changed = Signal(str)
    action_performed = Signal(str)

    def __init__(self, state, camera, parent=None):
        super().__init__(parent)
        self.state = state
        self.camera = camera
        self.gate = GestureGate()
        self.pinch = PinchControl()
        self._zoom_anchor = None
        self._zoom_at = float("-inf")
        self.executor = ActionExecutor(self)
        self.enabled = False
        self.status = "Управление приостановлено"
        self.last_gesture = "—"
        self.last_action = "—"
        self._suspensions = 0
        self._configuration = None
        self._camera_configuration = None
        self._diagnostic = None
        self._pinch_conflict = False
        state.changed.connect(self.configure)
        camera.frame_ready.connect(self.process_frame)
        camera.error.connect(self.camera_error)
        camera.stopped.connect(self.camera_stopped)
        camera.status_changed.connect(self.camera_status)
        self.configure()

    def configure(self):
        settings = dict(self.state.settings)
        custom = [gesture for gesture in self.state.gestures if gesture.get("is_custom")]
        configuration = repr((self.state.active_profile_id, self.state.assignments,
                              self.state.action_settings, settings, self.state.gestures))
        if configuration != self._configuration:
            # После смены профиля жест должен заново пройти время удержания.
            self.gate.reset()
            self.pinch.reset()
            self._zoom_anchor = None
            self._configuration = configuration
            self._diagnostic = None
            self._log_bindings()
        camera_configuration = repr((settings, custom))
        if camera_configuration != self._camera_configuration:
            # Сохранение назначения не должно обнулять историю движений в камере.
            self.camera.configure(settings, custom)
            self._camera_configuration = camera_configuration
        self.changed.emit()

    def _gesture_name(self, gesture):
        # Название из БД может отличаться от встроенной подписи распознавателя.
        key = gesture.get("key")
        return next((g["name"] for g in self.state.gestures if g["key"] == key), None) if key else None

    def _binding(self, name):
        """Назначение и эффективные настройки всегда берём из активного профиля."""
        pid = self.state.active_profile_id
        action = self.state.assignments.get(pid, {}).get(name, "Нет действия")
        return action, self.state.get_action_settings(pid, name)

    def _select_dynamic_gesture(self, movements):
        # Сохраняем прежний приоритет: первое включённое дискретное движение
        # опережает статическую позу; непрерывный pinch обрабатывается отдельно.
        for movement in movements:
            name = self._gesture_name(movement)
            action, settings = self._binding(name)
            if (action != "Нет действия" and settings["enabled"]
                    and execution_mode(action, settings) != ExecutionMode.CONTINUOUS):
                return movement, name
        return None

    def _log_bindings(self):
        pid = self.state.active_profile_id
        if not pid:
            return
        count = 0
        for gesture in self.state.gestures:
            name = gesture["name"]
            action = self.state.assignments.get(pid, {}).get(name, "Нет действия")
            if action == "Нет действия":
                continue
            settings = self.state.get_action_settings(pid, name)
            count += bool(settings["enabled"])
            logger.info("Назначение: профиль=%s; key=%s; жест=%s; действие=%s; enabled=%s; "
                        "hold=%s с; cooldown=%s с; threshold=%.2f; режим=%s",
                        self.state.active_profile_name, gesture["key"], name, action, settings["enabled"],
                        settings["hold_time"], settings["cooldown"], settings["sensitivity"],
                        execution_mode(action, settings).value)
        logger.info("Профиль %s: включённых назначений %s", self.state.active_profile_name, count)

    def set_enabled(self, enabled):
        if enabled and not self.state.active_profile_id:
            self.set_status("Сначала создайте профиль управления")
            return
        self.enabled = bool(enabled)
        self._diagnostic = None
        logger.info("Управление %s; открытых проверок/мастеров: %s",
                    "включено" if self.enabled else "выключено", self._suspensions)
        self.gate.reset()
        self.pinch.reset()
        if self.enabled:
            self.set_status("Подключаем камеру…")
            self.camera.start()
        else:
            self.set_status("Управление приостановлено")
        self.changed.emit()

    def toggle(self):
        self.set_enabled(not self.enabled)

    def suspend(self):
        self._suspensions += 1
        logger.info("Команды приостановлены: открыт мастер/проверка; окон: %s", self._suspensions)
        self.gate.reset()
        self.pinch.reset()
        self.set_status("Управление приостановлено: настройка жестов")

    def resume(self):
        self._suspensions = max(0, self._suspensions - 1)
        logger.info("Мастер/проверка закрыты; оставшихся окон: %s; управление: %s", self._suspensions, self.enabled)
        self.gate.reset()
        self.set_status("Ожидание жеста" if self.enabled else "Управление приостановлено")

    def set_status(self, text):
        if text != self.status:
            self.status = text
            self.status_changed.emit(text)

    def diagnose(self, reason, gesture=None, action=None, *, packet=None, settings=None):
        # Пишем только смену причины, а не сообщение на каждом кадре.
        current = (self.state.active_profile_id, gesture, action, reason)
        if current != self._diagnostic:
            self._diagnostic = current
            detail = ""
            if packet is not None and settings is not None:
                hand, detected = packet.get("hand") or {}, packet.get("gesture") or {}
                detail = (f"; key={detected.get('key')}; confidence={detected.get('confidence', 0):.2f}; "
                          f"threshold={settings['sensitivity']:.2f}; ready={bool(hand.get('ready'))}; "
                          f"motion_ready={bool(hand.get('motion_ready', hand.get('ready')))}; "
                          f"hold={settings['hold_time']} с; fps={packet.get('fps', '—')}")
            logger.info("Профиль: %s; жест: %s; действие: %s; %s",
                        self.state.active_profile_name, gesture or "—", action or "—", reason + detail)

    def camera_status(self, text):
        if "подключена" not in text or "не подключена" in text:
            self.gate.reset()

    def camera_error(self, text):
        self.enabled = False
        self.gate.reset()
        self.pinch.reset()
        self.set_status(text)
        self.changed.emit()

    def camera_stopped(self):
        self.gate.reset()
        self.pinch.reset()
        self.set_status("Камера не подключена")

    def process_frame(self, packet):
        gesture = packet.get("gesture") or {}
        name, key = self._gesture_name(gesture), gesture.get("key")
        if key and name and self.last_gesture != name:
            self.last_gesture = name
            self.changed.emit()
        if not self.enabled or self._suspensions:
            self.diagnose("Проверка/настройка жестов: команды приостановлены" if self._suspensions
                          else "Управление выключено: нажмите «Включить управление»")
            return
        hand = packet.get("hand") or {}
        now = packet.get("timestamp", time.monotonic())
        if self._continuous(hand, now):
            self.gate.reset()
            return
        dynamic = self._select_dynamic_gesture(packet.get("dynamic_gestures") or [])
        if dynamic is not None:
            gesture, name = dynamic
            key = gesture["key"]
            self.last_gesture = name
        # Загружаем действие для текущего профиля из уже загруженных локальных данных.
        profile_id = self.state.active_profile_id
        action, settings = self._binding(name)
        diagnostic_packet = {**packet, "gesture": gesture}
        ready = hand.get("motion_ready", hand.get("ready")) if gesture.get("recognition_type") == "dynamic" else hand.get("ready")
        if not key or not ready:
            # Потеря качества той же позы не означает, что пользователь отпустил жест.
            self.gate.update(key if hand.get("found") else None, 0, {"enabled": False}, packet.get("timestamp"))
            self.set_status(hand.get("hint") or "Ожидание жеста")
            self.diagnose(self.status, name, action, packet=diagnostic_packet, settings=settings)
            return
        if name is None:
            self.gate.update(None, 0, {"enabled": False}, now)
            self.set_status(f"Жест {key} отсутствует среди загруженных жестов")
            self.diagnose(self.status, key, action)
            return
        if execution_mode(action, settings) == ExecutionMode.CONTINUOUS:
            self.gate.update(None, 0, {"enabled": False}, now)
            self.set_status("Регулировка pinch: оставьте одно включённое назначение и сомкните пальцы на 0,5 с")
            self.diagnose(self.status, name, action, packet=diagnostic_packet, settings=settings)
            return
        if action == "Нет действия" or not settings.get("enabled", True):
            self.gate.update(None, 0, {}, packet.get("timestamp"))
            self.set_status("Для этого жеста в активном профиле не назначено действие" if action == "Нет действия"
                            else "Назначение этого жеста выключено")
            self.diagnose(self.status, name, action)
            return
        fired = (self.gate.trigger_motion(gesture, settings, now) if gesture.get("recognition_type") == "dynamic"
                 else self.gate.update(key, gesture.get("confidence", 0), settings, now))
        if fired:
            logger.info("Запуск: профиль=%s; key=%s; действие=%s", self.state.active_profile_name, key, action)
            self.last_action = self.executor.execute(action, {**settings, "profile_id": profile_id, "gesture": key})
            self.action_performed.emit(self.last_action)
            self.set_status("Выполнено действие: " + action if self.executor.succeeded else self.last_action)
            if not self.executor.succeeded:
                self.enabled = False
            self.changed.emit()
        else:
            self.set_status(self.gate.status)
            self.diagnose(self.gate.status, name, action, packet=diagnostic_packet, settings=settings)

    def _continuous(self, hand, now):
        pid = self.state.active_profile_id
        bindings = []
        for gesture in self.state.gestures:
            action, settings = self._binding(gesture["name"])
            data = gesture.get("gesture_data") or {}
            if (execution_mode(action, settings) == ExecutionMode.CONTINUOUS
                    and data.get("dynamic_type") == "pinch" and settings["enabled"]):
                bindings.append((gesture, action, settings))
        if len(bindings) != 1:
            self.pinch.reset()
            if len(bindings) > 1 and not self._pinch_conflict:
                logger.warning("В профиле %s несколько назначений pinch: %s. Оставьте одно включённое; обычные жесты продолжают работать.",
                               self.state.active_profile_name, ", ".join(g["name"] for g, _, _ in bindings))
            self._pinch_conflict = len(bindings) > 1
            return False
        self._pinch_conflict = False
        gesture, action, settings = bindings[0]
        if hand.get("confidence", 0) < settings["sensitivity"]:
            hand = {}
        was_active = self.pinch.active
        value = self.pinch.update(hand, now, smoothing=settings["pinch_smoothing"],
                                  minimum=settings["pinch_min"], maximum=settings["pinch_max"])
        if not self.pinch.active:
            self._zoom_anchor = None
            if self.pinch.since is not None:
                self.set_status("Удерживайте pinch 0,5 с: остальные пальцы раскрыты")
                return True
            return False
        if not was_active and ACTION_KEYS[action] != "zoom_control":
            try:
                # Начинаем от текущей системной громкости, без скачка при активации.
                self.pinch.value = self.pinch.sent = self.executor.backend.get_volume()
            except Exception as error:
                log_error("Actions", "Чтение системной громкости", error)
                self.camera_error(f"Не удалось прочитать громкость: {error}")
                return True
            value = None
        self.last_gesture = gesture["name"]
        if value is not None:
            context = {"value": value, "gesture": gesture["key"], "profile_id": pid}
            if ACTION_KEYS[action] == "zoom_control":
                if self._zoom_anchor is None:
                    self._zoom_anchor = value
                    return True
                delta = value - self._zoom_anchor
                if abs(delta) < .12 or now - self._zoom_at < .25:
                    return True
                context["direction"] = 1 if delta > 0 else -1
                self._zoom_anchor, self._zoom_at = value, now
            self.last_action = self.executor.execute(action, context)
            if not self.executor.succeeded:
                self.camera_error(self.last_action)
                return True
            self.action_performed.emit(self.last_action)
        self.set_status(("Масштабирование" if ACTION_KEYS[action] == "zoom_control" else "Регулировка громкости")
                        + (f" · {self.pinch.sent:.0%}" if self.pinch.sent is not None else ""))
        self.changed.emit()
        return True
