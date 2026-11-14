import csv
import io
import unittest
from experiments.compare_gnss_64 import events, reference, METHODS


class TestControlledGNSSComparison(unittest.TestCase):
    @staticmethod
    def records(attack=False):
        return [{"time_s": float(i), "cn0": 40. if i < 40 or not attack else 32.,
                 "satellites": 8., "injection_active": int(attack and i >= 40)}
                for i in range(70)]

    def test_clean_data_does_not_alert(self):
        records = self.records()
        for method in METHODS:
            self.assertEqual(events(records, method, reference(records)), [])

    def test_injection_labels_do_not_enter_detector(self):
        records = self.records(True)
        refs = reference(records)
        for method in METHODS:
            result = events(records, method, refs)
            hidden = [dict(r, injection_active=0) for r in records]
            self.assertEqual(result, events(hidden, method, refs))

    def test_confirmed_after_three_samples(self):
        rows = self.records(True)
        self.assertEqual(events(rows, "cn0_4db", reference(rows)), [42.0])

    def test_missing_cn0_not_interpreted_as_zero(self):
        rows = self.records()
        for r in rows[40:]:
            r["cn0"] = None
        self.assertEqual(events(rows, "cn0_4db", reference(rows)), [])


if __name__ == "__main__":
    unittest.main()
