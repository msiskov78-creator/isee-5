"""Небольшие переиспользуемые элементы оформления."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


def clear_layout(layout):
    """Обновляем карточки страниц; Qt удалит виджеты после обработки текущих сигналов."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def label(text, role="body"):
    widget = QLabel(text)
    # Пользовательские строки всегда выводим как текст, а не HTML.
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("role", role)
    widget.setWordWrap(True)
    return widget


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)
    return frame


def page_header(layout, title, subtitle):
    header = QWidget()
    column = QVBoxLayout(header)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(6)
    column.addWidget(label(title, "title"))
    column.addWidget(label(subtitle, "subtitle"))
    layout.addWidget(header)


def primary_button(text):
    button = QPushButton(text)
    button.setObjectName("primary")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def message_label():
    widget = label("", "muted")
    widget.setMinimumHeight(22)
    return widget


def set_message(widget, text, role="error"):
    if widget.text() != text:
        widget.setText(text)
    if widget.property("role") != role:
        widget.setProperty("role", role)
        # Перечитываем стиль только при смене роли, а не на каждом видеокадре.
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def switch_window(previous, following):
    # Сначала показываем новое окно: приложение не завершится между переходами.
    QApplication.instance().current_window = following
    following.show()
    previous.close()


class GestureIllustration(QWidget):
    """Декоративная схема ладони. Не использует камеру или распознавание."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setMaximumHeight(270)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        scale = min(self.width() / 290, self.height() / 260)
        painter.scale(scale, scale)
        glow = QRadialGradient(0, 0, 135)
        glow.setColorAt(0, QColor(44, 77, 154, 95))
        glow.setColorAt(1, QColor(13, 16, 22, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-140, -140, 280, 280))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#243453"), 1))
        painter.drawEllipse(QPointF(0, 0), 109, 109)
        painter.drawEllipse(QPointF(0, 0), 83, 83)
        # Координаты нарисованы вручную и служат только иллюстрацией.
        wrist = (0, 88)
        fingers = [
            [wrist, (-42, 42), (-72, 12), (-89, -9)],
            [wrist, (-34, 5), (-43, -37), (-46, -77)],
            [wrist, (-7, -1), (-9, -49), (-10, -95)],
            [wrist, (20, 5), (24, -39), (27, -80)],
            [wrist, (44, 23), (55, -6), (61, -39)],
        ]
        painter.setPen(QPen(QColor("#5c87ef"), 2))
        for finger in fingers:
            for start, end in zip(finger, finger[1:]):
                painter.drawLine(QPointF(*start), QPointF(*end))
        for left, right in zip(fingers, fingers[1:]):
            painter.drawLine(QPointF(*left[1]), QPointF(*right[1]))
        for finger in fingers:
            for point in finger[1:]:
                painter.setPen(QPen(QColor("#8fafff"), 1.5))
                painter.setBrush(QColor("#172849"))
                painter.drawEllipse(QPointF(*point), 4, 4)
        painter.setBrush(QColor("#26e7a4"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(*wrist), 5, 5)
