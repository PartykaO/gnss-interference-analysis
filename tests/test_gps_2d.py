import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from gnss_interference.gps_2d import HEADERS, stream_epochs, process


def make_xlsx(path, rows):
    ss='<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join(f'<si><t>{escape(v)}</t></si>' for v in HEADERS)+'</sst>'
    data=['<row r="1">'+''.join(f'<c r="{chr(65+i)}1" t="s"><v>{i}</v></c>' for i in range(14))+'</row>']
    for row_num, (prn, t, cn0, output) in enumerate(rows,2):
        vals=[0.0]*14
        vals[0]=prn
        vals[3]=t
        vals[12]=cn0
        vals[13]=output
        data.append('<row r="'+str(row_num)+'">'+''.join(f'<c r="{chr(65+i)}{row_num}"><v>{v}</v></c>' for i,v in enumerate(vals))+'</row>')
    xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(data)+'</sheetData></worksheet>'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/sharedStrings.xml',ss)
        z.writestr('xl/worksheets/sheet1.xml',xml)


class TestGPS2D(unittest.TestCase):
    def test_aggregate_and_keep_opaque_codes(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'long.xlsx'
            make_xlsx(f,[(6,100,45,1),(7,100,43,2),(6,100.2,44,1),(7,101.1,46,3),(6,50,48,0)])
            rows=list(stream_epochs(f))
            self.assertEqual(len(rows),4)
            self.assertEqual(rows[0][2],44)
            self.assertEqual(rows[0][3],2)
            self.assertEqual(rows[0][4]['1'],1)
            report=process(f,out=Path(td)/'out')
            self.assertEqual(report['n_sessions_time_heuristic'],2)
            self.assertEqual(report['opaque_output_codes'],{'1':2,'2':1,'3':1,'0':1})
            self.assertIn('44.00000',(Path(td)/'out'/'session_0001.csv').read_text())
            self.assertIn('unverified',report['label_status'])

    def test_negative_bucket(self):
        with self.assertRaises(ValueError):
            process('unknown.xlsx',bucket_s=0)


if __name__=='__main__':
    unittest.main()
