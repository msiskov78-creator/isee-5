"""Границы шкалы БД, округление float4 и диагностика без угадывания единиц."""

import logging
import unittest
from diagnostics import ComponentFormatter
from sensitivity import validate_sensitivity, sensitivity_to_percent, sensitivity_from_percent


class SensitivityTests(unittest.TestCase):
    def test_database_values_and_float4_rounding(self):
        for db, ui in ((0., 0), (.5, 50), (.7, 70), (.699999988, 70), (.85, 85), (1., 100)):
            with self.subTest(db=db):
                self.assertEqual(sensitivity_to_percent(db), ui)
                self.assertAlmostEqual(sensitivity_from_percent(ui), db, places=6)

    def test_db_percent_values_and_nonfinite_values_are_rejected(self):
        for value in (-.1, 1.01, 70, True, "0.7", None, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertLogs("Settings", level="ERROR"), self.assertRaises(ValueError):
                validate_sensitivity(value)
        self.assertIsNone(validate_sensitivity(None, nullable=True))

    def test_requested_error_prefixes(self):
        for name, prefix in (("Settings", "[SETTINGS ERROR]"), ("Database", "[DB ERROR]")):
            record = logging.LogRecord(name, logging.ERROR, "", 0, "точный текст", (), None)
            self.assertEqual(ComponentFormatter().format(record), prefix + " точный текст")


if __name__ == "__main__":
    unittest.main()
