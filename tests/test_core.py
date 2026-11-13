import csv
import tempfile
import unittest
from pathlib import Path

from gnss_interference.core import Observation, analyse, evaluate, read_csv


class TestGNSS(unittest.TestCase):
    def test_event_confirmation_and_recovery(self):
        rows = [Observation(float(i), {"cn0": 42.0, "satellites": 10.0}) for i in range(40)]
        rows += [Observation(float(i), {"cn0": 30.0, "satellites": 6.0}) for i in range(40, 45)]
        rows += [Observation(float(i), {"cn0": 42.0, "satellites": 10.0}) for i in range(45, 49)]
        scores, alarms, info = analyse(rows, calibration_s=20, confirm_samples=3, recovery_samples=2)
        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0].start_s, 40)
        self.assertEqual(alarms[0].confirmed_s, 42)
        self.assertEqual(alarms[0].end_s, 46)
        self.assertEqual(evaluate(alarms, 40)["first_confirmation_delay_s"], 2)
        self.assertFalse(scores[0]["anomaly"])

    def test_no_alarm_on_constant_data(self):
        rows = [Observation(float(i), {"cn0": 40.0}) for i in range(60)]
        self.assertEqual(analyse(rows)[1], [])

    def test_calibration_insufficient(self):
        rows = [Observation(float(i), {"cn0": 40.0}) for i in range(3)]
        with self.assertRaises(ValueError):
            analyse(rows)

    def test_duplicate_timestamps_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.csv"
            path.write_text("clock,signal\n1,40\n1,35\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "strictly"):
                read_csv(path, "clock", {"cn0": "signal"})

    def test_missing_measurements_are_not_imputed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.csv"
            path.write_text("time_s,cn0\n0,40\n1,\n2,38\n", encoding="utf-8")
            rows = read_csv(path)
            self.assertNotIn("cn0", rows[1].metrics)

    def test_no_physical_onset_claim(self):
        self.assertEqual(evaluate([], 10)["first_confirmation_delay_s"], None)


if __name__ == "__main__":
    unittest.main()
