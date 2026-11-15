"""Тесты UI не отправляют клавиши в рабочий стол и не меняют реальную громкость."""
from unittest.mock import Mock, patch


def isolate_windows_actions(test_class):
    backend = Mock()
    backend.get_volume.return_value = .5
    replacement = patch("actions.action_executor.WindowsActions", return_value=backend)
    replacement.start()
    test_class.addClassCleanup(replacement.stop)
