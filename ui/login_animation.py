"""Анимация после подтверждённого входа. Пароль сюда никогда не передаётся."""

import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget


def _progress(value, start, end):
    """Плавный переход от нуля к единице на заданном участке времени."""
    fraction = max(0.0, min(1.0, (value - start) / (end - start)))
    return fraction * fraction * (3.0 - 2.0 * fraction)


def _mix(start, end, progress):
    return start + (end - start) * progress


def _color(hex_value, opacity=1.0):
    color = QColor(hex_value)
    color.setAlphaF(max(0.0, min(1.0, opacity)))
    return color


class LoginAnimation(QWidget):
    finished = Signal()
    DURATION_MS = 8800
    FAN_ANGLES = (-18, -12, -6, 6, 12, 18)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("loginAnimation")
        self.setAccessibleName("Анимация успешного входа")
        self._username = ""
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self._time = 0.0
        self._source_size = None
        self._username_rect = None
        self._boxes_rects = None

    def start(self, username, username_rect=None, boxes_rects=None):
        # Вызывать только после успешного ответа Supabase, без передачи пароля.
        self.stop()
        self._username = username
        self._source_size = self.size()
        self._username_rect = QRectF(username_rect) if username_rect is not None else None
        self._boxes_rects = (
            [QRectF(rect) for rect in boxes_rects]
            if boxes_rects is not None and len(boxes_rects) == 6 else None
        )
        self._time = 0.0
        self._elapsed.start()
        self._timer.start()
        self.update()

    def stop(self):
        self._timer.stop()

    def _advance(self):
        if not self._timer.isActive():
            return
        self._time = min(self._elapsed.elapsed() / 1000.0, self.DURATION_MS / 1000.0)
        self.update()
        if self._time >= self.DURATION_MS / 1000.0:
            self.stop()
            self.finished.emit()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def _scaled_rect(self, rect):
        # Исходные позиции остаются согласованными после изменения размера окна.
        scale_x = self.width() / max(1, self._source_size.width())
        scale_y = self.height() / max(1, self._source_size.height())
        return QRectF(rect.x() * scale_x, rect.y() * scale_y,
                      rect.width() * scale_x, rect.height() * scale_y)

    @staticmethod
    def _text(painter, rect, text, size, color, bold=False):
        font = QFont("Segoe UI")
        font.setPointSizeF(size)
        font.setWeight(QFont.Weight.DemiBold if bold else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _check(painter, center, size, opacity=1.0, width=3.0):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color("#26e7a4", opacity), width,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath()
        path.moveTo(center.x() - size * 0.42, center.y())
        path.lineTo(center.x() - size * 0.10, center.y() + size * 0.30)
        path.lineTo(center.x() + size * 0.45, center.y() - size * 0.34)
        painter.drawPath(path)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#090b10"))
        width, height = self.width(), self.height()
        time = self._time
        center_x = width / 2

        # ==========================================
        # ШКАЛА ВРЕМЕНИ (ВСЕГО 8,8 СЕКУНД)
        # 0–0,95: логин поднимается; 0,45–1,55: ячейки растут.
        # 1,55–2,40: карточки расходятся веером.
        # 2,40–4,90: синее свечение, «Проверяем данные...» (2,5 с).
        # 4,90–6,55: галочки слева направо.
        # 6,55–7,10: большой знак успеха; 7,10–8,80: удержание (1,7 с).
        # ==========================================
        rise = _progress(time, 0.0, 0.95)
        morph = _progress(time, 0.45, 1.55)
        fan = _progress(time, 1.55, 2.40)
        success = _progress(time, 6.55, 7.10)

        # Спокойное фоновое свечение появляется вместе с карточками.
        glow_center = QPointF(center_x, height * 0.45)
        gradient = QRadialGradient(glow_center, min(width, height) * 0.53)
        gradient.setColorAt(0.0, _color("#254fac", 0.13 * morph * (1 - success)))
        gradient.setColorAt(1.0, _color("#090b10", 0.0))
        painter.fillRect(self.rect(), gradient)

        # Логин движется из настоящего поля формы в верхнюю часть окна.
        source_user = (self._scaled_rect(self._username_rect) if self._username_rect is not None
                       else QRectF(center_x - 181, height * 0.39 - 24, 362, 48))
        name_size = _mix(11, 23, rise)
        name_font = QFont("Segoe UI")
        name_font.setPointSizeF(name_size)
        name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        name_width = painter.fontMetrics().horizontalAdvance(self._username)
        name_center_x = _mix(source_user.left() + 14 + name_width / 2, center_x, rise)
        name_center_y = _mix(source_user.center().y(), height * 0.20, rise)
        if rise < 1:
            painter.setPen(QPen(_color("#252c3a", 1 - rise), 1))
            painter.setBrush(_color("#151923", 1 - rise))
            painter.drawRoundedRect(source_user, 10, 10)
        self._text(painter, QRectF(name_center_x - 300, name_center_y - 30, 600, 60),
                   self._username, name_size, _color("#eef2fc", 1 - success), True)
        self._text(painter, QRectF(center_x - 200, height * 0.20 + 34, 400, 24),
                   "БЕЗОПАСНЫЙ ВХОД", 9, _color("#65728c", rise * (1 - success)))

        # На карточках только точки и галочки: содержимое пароля не используется.
        for index, angle in enumerate(self.FAN_ANGLES):
            if self._boxes_rects is not None:
                source = self._scaled_rect(self._boxes_rects[index])
            else:
                source = QRectF(center_x - 181 + index * 62, height * 0.51 - 29, 52, 58)
            offset = index - 2.5
            straight_x = center_x + offset * 62
            card_x = _mix(source.center().x(), straight_x, morph)
            card_x = _mix(card_x, center_x + offset * 86, fan)
            card_y = _mix(source.center().y(), height * 0.46, morph)
            card_y += (offset * offset - 0.25) * 4.2 * fan
            card_width = _mix(source.width(), 74, morph)
            card_height = _mix(source.height(), 106, morph)
            green = _progress(time, 4.90 + index * 0.275, 5.175 + index * 0.275)
            blue = _progress(time, 2.40, 2.70)
            # Рамка меняет цвет плавно, а каждая следующая карточка ждёт своей очереди.
            base, blue_color, green_color = QColor("#252c3a"), QColor("#4f7cff"), QColor("#26e7a4")
            border = QColor(*[
                round(_mix(_mix(getattr(base, channel)(), getattr(blue_color, channel)(), blue),
                           getattr(green_color, channel)(), green))
                for channel in ("red", "green", "blue")
            ])

            painter.save()
            painter.setOpacity(1 - success)
            painter.translate(card_x, card_y)
            painter.rotate(angle * fan)
            rect = QRectF(-card_width / 2, -card_height / 2, card_width, card_height)

            # Несколько прозрачных контуров дают мягкую тень без тяжёлых эффектов.
            pulse = 0.8 + 0.2 * math.sin(time * 3.2 + index * 0.3)
            glow_strength = max(blue * pulse, green)
            for spread in range(15, 0, -3):
                glow_color = QColor(border)
                glow_color.setAlphaF(0.026 * glow_strength)
                painter.setPen(QPen(glow_color, 5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(rect.adjusted(-spread, -spread, spread, spread), 12 + spread, 12 + spread)
            painter.setPen(QPen(border, _mix(1.0, 1.6, blue)))
            painter.setBrush(QColor("#121e23") if green > 0 else QColor("#151923"))
            painter.drawRoundedRect(rect, _mix(10, 13, morph), _mix(10, 13, morph))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color("#b6c5e6", 1 - green))
            painter.drawEllipse(QPointF(0, 0), 3.5, 3.5)
            if green:
                self._check(painter, QPointF(0, 0), 25 * _mix(0.6, 1, green), green)
            painter.restore()

        checking = _progress(time, 2.40, 2.75) * (1 - success)
        self._text(painter, QRectF(center_x - 250, height * 0.68, 500, 35),
                   "Проверяем данные...", 15, _color("#b8c8ea", checking), True)
        self._text(painter, QRectF(center_x - 260, height * 0.68 + 38, 520, 28),
                   "Подготавливаем ваше рабочее пространство", 10, _color("#65728c", checking))

        if success:
            # Большая галочка и приветствие остаются видимыми ещё 1,7 секунды.
            success_center = QPointF(center_x, height * 0.39)
            painter.save()
            painter.setOpacity(success)
            green_glow = QRadialGradient(success_center, 130)
            green_glow.setColorAt(0, _color("#26e7a4", 0.13))
            green_glow.setColorAt(1, _color("#26e7a4", 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(green_glow)
            painter.drawEllipse(success_center, 130, 130)
            painter.setPen(QPen(_color("#26e7a4", 0.32), 1.5))
            painter.setBrush(QColor("#0e201d"))
            painter.drawEllipse(success_center, 49, 49)
            self._check(painter, success_center, 45, width=4.5)
            self._text(painter, QRectF(center_x - 320, height * 0.39 + 75, 640, 50),
                       "Вход выполнен", 27, QColor("#eef2fc"), True)
            self._text(painter, QRectF(center_x - 340, height * 0.39 + 133, 680, 35),
                       f"Добро пожаловать, {self._username}", 14, QColor("#8d96aa"))
            painter.restore()

        # Тонкая полоса показывает ход перехода и не выглядит как зависшее окно.
        track = QRectF(center_x - 90, height - 56, 180, 3)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1d2534"))
        painter.drawRoundedRect(track, 1.5, 1.5)
        painter.setBrush(QColor("#26e7a4") if success else QColor("#4f7cff"))
        painter.drawRoundedRect(QRectF(track.x(), track.y(), track.width() * min(time / 8.8, 1), 3), 1.5, 1.5)
        painter.end()
