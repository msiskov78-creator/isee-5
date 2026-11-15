"""Журнал сохраняет ошибки и причины блокировки, но не секреты сессии."""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from diagnostics import COMPONENTS, setup_logging


class DiagnosticsTests(unittest.TestCase):
    def test_file_logging_is_redacted_and_not_duplicated(self):
        previous = {name: (list(logging.getLogger(name).handlers), logging.getLogger(name).level,
                           logging.getLogger(name).propagate) for name in COMPONENTS}
        try:
            with TemporaryDirectory() as directory:
                path = setup_logging(directory)
                self.assertEqual(path, Path(directory).resolve() / "gesture_control.log")
                setup_logging(directory)
                logging.getLogger("Actions").info("confidence=0.78; threshold=0.95")
                try:
                    raise ValueError("password=secret access_token=private bearer hidden eyJhbGci.test.signature")
                except ValueError:
                    logging.getLogger("Actions").exception("Проверка ошибки")
                content = path.read_text(encoding="utf-8")
                self.assertEqual(content.count("confidence=0.78"), 1)
                self.assertIn("ValueError", content)
                self.assertIn("[Actions ERROR]", content)
                for secret in ("secret", "private", "hidden", "eyJhbGci.test.signature"):
                    self.assertNotIn(secret, content)
                self._restore(previous)
        finally:
            self._restore(previous)

    def _restore(self, previous):
        for name, (handlers, level, propagate) in previous.items():
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                if handler not in handlers:
                    logger.removeHandler(handler)
                    handler.close()
            logger.setLevel(level)
            logger.propagate = propagate
