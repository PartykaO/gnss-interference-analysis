import csv
import tempfile
import unittest
from pathlib import Path

from gnss_interference.cardrf import extract, features


class TestCardRF(unittest.TestCase):
    def test_features_for_flat_signal(self):
        a=features([2.0]*1024)
        self.assertEqual(a[0],2.0)
        self.assertEqual(a[1],2.0)
        self.assertEqual(a[2],0.0)
        self.assertEqual(a[4],1.0)
        self.assertEqual(a[5],0.0)
        self.assertEqual(a[6],0.0)

    def test_cardrf_label_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"input.csv"
            with src.open("w",newline="") as f:
                w=csv.writer(f)
                w.writerow(["1"]*1024+["Non_Control","DJI_M600","DJI_M600_FLYING"])
            output=Path(tmp)/"derived.csv"
            report=extract(src,output)
            self.assertEqual(report["rows_processed"],1)
            self.assertEqual(report["labels"][0]["capture"],"DJI_M600_FLYING")
            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".manifest.json").exists())
            self.assertTrue(report["not_a_gnss_jamming_or_flight_telemetry_dataset"])

    def test_malformed_row_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"broken.csv"
            src.write_text("1,2,3\n")
            with self.assertRaisesRegex(ValueError,"expected 1027"):
                extract(src,Path(tmp)/"out.csv")

if __name__=="__main__":
    unittest.main()
