import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from gnss_interference.gps_xlsx import FIELDS, N_CHANNELS, iter_epochs, process


def excel_col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65+r) + s
    return s


def make_xlsx(path, observations):
    strings = list(FIELDS) + [f'ch{i}' for i in range(N_CHANNELS)]
    header1 = ''.join(f'<c r="{excel_col(j*8)}1" t="s"><v>{j}</v></c>' for j in range(len(FIELDS)))
    header2 = ''.join(f'<c r="{excel_col(j)}2" t="s"><v>{len(FIELDS)+(j%8)}</v></c>' for j in range(13*8))
    rows = [f'<row r="1">{header1}</row>',f'<row r="2">{header2}</row>']
    for i,(rx,prns,cn0) in enumerate(observations,3):
        cell_values = [0.0]*104
        cell_values[0:8] = prns
        cell_values[24:32] = [rx]*8
        cell_values[96:104] = cn0
        cells = ''.join(f'<c r="{excel_col(j)}{i}"><v>{v}</v></c>' for j,v in enumerate(cell_values))
        rows.append(f'<row r="{i}">{cells}</row>')
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>'
    st = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+''.join(f'<si><t>{escape(x)}</t></si>' for x in strings)+'</sst>'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/sharedStrings.xml', st)
        z.writestr('xl/worksheets/sheet1.xml',xml)


class TestGPSXLSX(unittest.TestCase):
    def test_zero_padding_sessions_and_aggregation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.xlsx'
            make_xlsx(path,[(0,[0]*8,[0]*8),
                (100,[4,7,0,0,0,0,0,0],[45,40,0,0,0,0,0,0]),
                (100.2,[4,7,0,0,0,0,0,0],[44,42,0,0,0,0,0,0]),
                (101.1,[4,0,0,0,0,0,0,0],[41,0,0,0,0,0,0,0]),
                (50,[4,0,0,0,0,0,0,0],[39,0,0,0,0,0,0,0])])
            events=list(iter_epochs(path))
            self.assertEqual(len(events),4)
            self.assertEqual(events[0][2],42.5)
            self.assertEqual(events[0][3],2)
            out=Path(tmp)/'out'
            report=process(path,out=out,bucket_s=1)
            self.assertEqual(report['n_sessions_time_heuristic'],2)
            self.assertEqual(report['sessions'][0]['output_rows'],2)
            self.assertEqual(report['sessions'][1]['output_rows'],1)
            self.assertIn('42.75000',(out/'session_0001.csv').read_text())
            self.assertIn('no ground-truth',report['label_status'])

    def test_reject_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            process('/missing/gnss.xlsx')

    def test_reject_negative_gap(self):
        with self.assertRaises(ValueError):
            process('anything.xlsx',max_gap_s=-1)


if __name__ == '__main__':
    unittest.main()
