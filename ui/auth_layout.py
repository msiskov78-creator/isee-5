"""Общий макет входа и регистрации; логика запросов находится в самих окнах."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from ui.widgets import GestureIllustration, label


def build_auth_layout(title, subtitle):
    page = QWidget()
    row = QHBoxLayout(page)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    brand = QFrame()
    brand.setObjectName("brandPanel")
    brand.setFixedWidth(362)
    left = QVBoxLayout(brand)
    left.setContentsMargins(34, 32, 34, 28)
    logo = label("◈  Gesture Control")
    logo.setObjectName("logo")
    left.addWidget(logo)
    left.addStretch()
    left.addWidget(label("ВАШИ ЖЕСТЫ. ВАШИ ПРАВИЛА.", "badge"))
    headline = label("Управление\nодним движением.")
    headline.setObjectName("brandTitle")
    left.addWidget(headline)
    left.addSpacing(10)
    left.addWidget(label("Личное пространство для жестов,\nдействий и профилей управления.", "muted"))
    left.addWidget(GestureIllustration())
    left.addStretch()
    left.addWidget(label("GESTURE CONTROL   /   ВЕРСИЯ 2.0.1", "badge"))
    left.addSpacing(8)
    left.addWidget(label("Всё начинается с вашего жеста.", "muted"))
    row.addWidget(brand)

    right = QWidget()
    column = QVBoxLayout(right)
    column.setContentsMargins(34, 26, 34, 26)
    column.addStretch()
    form = QWidget()
    form.setFixedWidth(380)
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    layout.addWidget(label("ЛИЧНОЕ ПРОСТРАНСТВО", "badge"))
    layout.addSpacing(2)
    layout.addWidget(label(title, "title"))
    layout.addWidget(label(subtitle, "muted"))
    layout.addSpacing(16)
    column.addWidget(form, 0, Qt.AlignmentFlag.AlignHCenter)
    column.addStretch()
    row.addWidget(right, 1)
    return page, layout
