"""Выход и закрытие окна ждут освобождения камеры, сохраняя отзывчивый интерфейс."""
import os
import time
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from shiboken6 import isValid
from test_control_runtime import FakeCamera
from test_persistence import RepositoryDouble
from ui.main_window import MainWindow


class DelayedCamera(FakeCamera):
    def stop(self):
        if not self.is_busy: self.stopped.emit()
    def finish_stop(self):
        self.is_busy=self.is_running=False
        self.stopped.emit()


class RuntimeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from safe_actions import isolate_windows_actions
        isolate_windows_actions(cls)
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.errors=[]
        self._exception_hook=sys.excepthook
        sys.excepthook=lambda kind,value,tb:self.errors.append(str(value))
        self.logouts=[]
        auth=SimpleNamespace(sign_out=lambda:self.logouts.append(True))
        self.camera=DelayedCamera()
        with patch("ui.main_window.CameraService",return_value=self.camera):
            self.window=MainWindow(SimpleNamespace(id="demo",user_metadata={"username":"student"}),auth)
        self.window.show()
        self.app.current_window=self.window
        self.camera.start(0)

    def wait_for(self,predicate):
        deadline=time.monotonic()+3
        while not predicate() and time.monotonic()<deadline: QTest.qWait(10)
        self.assertTrue(predicate())

    def tearDown(self):
        self.camera.finish_stop()
        for window in self.app.topLevelWidgets():
            if isValid(window): window.close()
        QTest.qWait(30)
        sys.excepthook=self._exception_hook
        self.assertEqual(self.errors,[])

    def test_close_waits_for_release(self):
        self.window.close()
        self.assertTrue(isValid(self.window))
        self.assertTrue(self.camera.is_busy)
        self.camera.finish_stop()
        self.wait_for(lambda:not isValid(self.window))

    def test_logout_waits_for_release_and_only_signs_out_once(self):
        self.window.logout()
        self.window.logout()
        QTest.qWait(30)
        self.assertEqual(self.logouts,[])
        self.camera.finish_stop()
        self.wait_for(lambda:not isValid(self.window))
        self.assertEqual(len(self.logouts),1)

    def test_logout_waits_for_last_save(self):
        repository=RepositoryDouble(self.window.state.snapshot())
        # В этом тесте проверяем закрытие, мастер первого входа не нужен.
        repository.data["settings"]["onboarding_completed"]=True
        self.window.state.attach_repository(repository)
        self.wait_for(lambda:not self.window.state.persistence_busy)
        repository.gate.clear()
        try:
            self.window.state.save_settings(sensitivity=.8)
            self.window.logout()
            self.camera.finish_stop()
            QTest.qWait(30)
            self.assertEqual(self.logouts,[])
        finally:
            repository.gate.set()
        self.wait_for(lambda:not isValid(self.window))
        self.assertEqual(repository.data["settings"]["sensitivity"],.8)
        self.assertEqual(len(self.logouts),1)

    def test_failed_save_allows_explicit_discard_and_releases_camera(self):
        repository=RepositoryDouble(self.window.state.snapshot())
        repository.data["settings"]["onboarding_completed"]=True
        self.window.state.attach_repository(repository)
        self.wait_for(lambda:not self.window.state.persistence_busy)
        repository.failure=True
        self.window.state.save_settings(sensitivity=.8)
        self.wait_for(lambda:not self.window.state.persistence_busy)
        self.window.logout()
        self.camera.finish_stop()
        self.wait_for(lambda:not self.window.state.persistence_busy)
        self.assertEqual(self.logouts,[])
        self.assertTrue(self.window.state.has_unsaved_changes)
        self.assertFalse(self.window.discard_logout_button.isHidden())
        with patch("ui.main_window.QMessageBox.question",return_value=QMessageBox.StandardButton.No):
            self.window.logout_without_saving()
        self.assertEqual(self.logouts,[])
        with patch("ui.main_window.QMessageBox.question",return_value=QMessageBox.StandardButton.Yes):
            self.window.logout_without_saving()
        self.wait_for(lambda:not isValid(self.window))
        self.assertEqual(self.logouts,[True])
        self.assertFalse(self.camera.is_busy)


if __name__ == "__main__": unittest.main()
