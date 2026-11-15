"""Ресурсы не зависят от cwd, изменяемые данные не попадают в каталог exe."""

import os
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app_paths


class AppPathsTests(unittest.TestCase):
    def test_frozen_configuration_is_next_to_executable(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\Program Files\GestureControl\GestureControl.exe"):
            paths = runpy.run_path(app_paths.__file__)
        self.assertEqual(paths["APP_DIRECTORY"], Path(r"C:\Program Files\GestureControl"))
        self.assertEqual(paths["RESOURCE_DIRECTORY"], Path(app_paths.__file__).resolve().parent)

    def test_user_directory_uses_localappdata(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"LOCALAPPDATA": directory}):
            result = app_paths.user_data_directory()
            self.assertEqual(result, Path(directory) / "GestureControl")
            self.assertTrue(result.is_dir())

    def test_source_resources_are_independent_of_working_directory(self):
        previous = Path.cwd()
        try:
            with TemporaryDirectory() as directory:
                os.chdir(directory)
                paths = runpy.run_path(app_paths.__file__)
                self.assertTrue((paths["RESOURCE_DIRECTORY"] / "ui/icons/chevron_down.svg").is_file())
                self.assertTrue((paths["RESOURCE_DIRECTORY"] / "hand_tracking/models/hand_landmarker.task.gz").is_file())
                os.chdir(previous)
        finally:
            os.chdir(previous)
