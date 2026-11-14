import csv
import tempfile
import unittest
from pathlib import Path
from gnss_interference.augmentation import Config, augment_rows, build_collection, process_file

class TestAugmentation(unittest.TestCase):
    def setUp(self):
        self.src = [{"time_s":float(i),"cn0":44.0,"satellites":8.0} for i in range(100)]
        self.cfg = Config(35,20,8,.8,5,5)

    def test_unchanged_outside_injected_interval(self):
        for name in ("attenuation","satellite_loss","intermittent","combined"):
            rows=augment_rows(self.src,name,self.cfg)
            for i in list(range(36))+list(range(55,100)):
                self.assertEqual(rows[i]["cn0"],44)
                self.assertEqual(rows[i]["satellites"],8)
                self.assertEqual(rows[i]["injection_active"],0)

    def test_attenuation_exact(self):
        rows=augment_rows(self.src,"attenuation",self.cfg)
        self.assertEqual(rows[41]["cn0"],36)
        self.assertEqual(rows[41]["injected_cn0_drop_db"],8)
        self.assertEqual(rows[41]["satellites"],8)

    def test_loss_is_deterministic(self):
        a=augment_rows(self.src,"satellite_loss",self.cfg)
        self.assertEqual(a,augment_rows(self.src,"satellite_loss",self.cfg))
        self.assertLess(a[45]["satellites"],8)

    def test_no_false_zero_dbhz(self):
        src=[{"time_s":40.0,"cn0":44.0,"satellites":1.0}]
        y=augment_rows(src,"satellite_loss",Config(35,20,0,1,0,7))
        self.assertIsNone(y[0]["cn0"])

    def test_intermit_recovers(self):
        x=augment_rows(self.src,"intermittent",self.cfg)
        self.assertEqual(x[38]["injection_active"],0)
        self.assertEqual(x[41]["injection_active"],1)

    def test_reject_bad_options(self):
        with self.assertRaises(ValueError):
            Config(1,2,1,1.1,2).validate()
        with self.assertRaises(ValueError):
            augment_rows(self.src,"spoofing",self.cfg)

    def test_build_collection_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"session_0001.csv"
            with path.open("w",newline="") as file:
                w=csv.writer(file); w.writerow(["time_s","cn0","satellites"])
                for r in self.src: w.writerow(r.values())
            target=Path(td)/"target.csv"
            manifest=process_file(path,target,"attenuation",self.cfg)
            self.assertTrue(target.exists())
            self.assertTrue(target.with_suffix(".json").exists())
            self.assertFalse(manifest["physical_attack"])
            self.assertEqual(len(build_collection(td,Path(td)/"augmented")),4)

if __name__=="__main__":
    unittest.main()
