"""Анимация завершает вход только после показа всех этапов."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from ui.login_animation import LoginAnimation


class FakeClock:
    """Проверяем границы таймера без ожидания девяти секунд в каждом тесте."""

    def __init__(self, milliseconds):
        self.milliseconds = milliseconds

    def elapsed(self):
        return self.milliseconds


class LoginAnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = LoginAnimation()
        self.widget.resize(1000, 680)
        self.widget.show()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.app.processEvents()

    def test_inactive_until_started_and_finishes_once(self):
        spy = QSignalSpy(self.widget.finished)
        self.assertFalse(self.widget._timer.isActive())
        self.widget.start("student")
        self.assertTrue(self.widget._timer.isActive())
        self.widget._elapsed = FakeClock(8799)
        self.widget._advance()
        self.assertEqual(spy.count(), 0)
        self.widget._elapsed.milliseconds = 8800
        self.widget._advance()
        self.assertEqual(spy.count(), 1)
        self.assertFalse(self.widget._timer.isActive())
        self.widget._advance()
        self.assertEqual(spy.count(), 1)

    def test_all_stages_render_and_resize(self):
        cells = [QRectF(319 + index * 62, 318, 52, 58) for index in range(6)]
        self.widget.start("student", QRectF(319, 250, 362, 48), cells)
        self.widget.stop()
        for seconds in (0, 0.7, 1.8, 3.5, 5.6, 6.54, 7.5, 8.8):
            self.widget._time = seconds
            self.assertFalse(self.widget.grab().isNull())
        self.widget.resize(1200, 800)
        self.assertFalse(self.widget.grab().isNull())
        scaled = self.widget._scaled_rect(cells[0])
        self.assertAlmostEqual(scaled.x(), cells[0].x() * 1.2)
        self.assertEqual(self.widget.FAN_ANGLES, (-18, -12, -6, 6, 12, 18))

    def test_close_stops_timer(self):
        self.widget.start("student")
        self.widget.close()
        self.assertFalse(self.widget._timer.isActive())


if __name__ == "__main__":
    unittest.main()
