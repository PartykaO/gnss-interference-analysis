"""Stream the simplified 2D (long-format) 14-column GPS Excel export.

Output codes are preserved as opaque counts only; no code has an assumed
attack class. Receiver-local timestamps are not asserted to be UTC.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from statistics import median

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADERS = ("PRN", "DO", "PD", "RX", "TOW", "CP", "EC", "LC", "PC", "PIP", "PQP", "TCD", "CN0", "Output")


def stream_rows(path: str | Path):
    with zipfile.ZipFile(path) as book:
        strings = []
        if "xl/sharedStrings.xml" in book.namelist():
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            strings = ["".join(x.itertext()) for x in root.findall(f"{NS}si")]
        with book.open("xl/worksheets/sheet1.xml") as file:
            for _, node in ET.iterparse(file, events=("end",)):
                if node.tag != f"{NS}row":
                    continue
                raw = [None] * 14
                for cell in node.findall(f"{NS}c"):
                    address = cell.attrib["r"].rstrip("0123456789")
                    col = 0
                    for letter in address:
                        col = col * 26 + ord(letter) - 64
                    col -= 1
                    if not 0 <= col < 14:
                        continue
                    v = cell.find(f"{NS}v")
                    if v is not None and v.text is not None:
                        raw[col] = strings[int(v.text)] if cell.get("t") == "s" else v.text
                row_no = int(node.attrib["r"])
                node.clear()
                if row_no == 1:
                    if tuple(raw) != HEADERS:
                        raise ValueError("Not the expected 2D GPS export with 14 named columns")
                    continue
                yield row_no, raw


def stream_epochs(path: str | Path):
    """Group contiguous per-channel rows with the same RX timestamp."""
    current_time = None
    cn0_values = []
    active_count = 0
    code_counts = Counter()
    last_row = None
    for row_no, values in stream_rows(path):
        try:
            prn, rx = float(values[0]), float(values[3])
            cn0 = float(values[12])
        except (TypeError, ValueError):
            continue
        if not all(map(math.isfinite, (prn, rx, cn0))) or rx <= 0 or prn <= 0:
            continue
        if current_time is not None and not math.isclose(rx, current_time, rel_tol=0, abs_tol=1e-5):
            yield last_row, current_time, median(cn0_values) if cn0_values else None, active_count, code_counts
            cn0_values, active_count, code_counts = [], 0, Counter()
        current_time = rx
        last_row = row_no
        active_count += 1
        if cn0 > 0:
            cn0_values.append(cn0)
        code = values[13]
        if code is not None:
            code_counts[str(code)] += 1
    if current_time is not None:
        yield last_row, current_time, median(cn0_values) if cn0_values else None, active_count, code_counts


def process(path: str | Path, out: str | Path | None = None,
            bucket_s: float = 1.0, max_gap_s: float = 5.0) -> dict:
    if bucket_s <= 0 or max_gap_s <= 0:
        raise ValueError("bucket_s and max_gap_s must be positive")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    directory = Path(out) if out else None
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
    sessions = []
    current = None
    start = 0.0
    previous = None
    bucket = None
    nums, cnos = [], []
    handle = writer = None
    totals = Counter()

    def finish_bucket():
        nonlocal bucket, nums, cnos
        if bucket is None or current is None:
            return
        current["output_rows"] += 1
        if cnos:
            current["output_rows_with_cn0"] += 1
        if writer:
            writer.writerow([f"{bucket*bucket_s:.6f}", f"{median(cnos):.5f}" if cnos else "", f"{median(nums):.1f}"])
        bucket = None
        nums, cnos = [], []

    def finish_session():
        nonlocal current, handle, writer
        finish_bucket()
        if handle:
            handle.close()
        handle = writer = None
        if current is not None:
            sessions.append(current)
            current = None

    for row_no, rx, cn, count, codes in stream_epochs(path):
        if previous is not None and (rx <= previous or rx - previous > max_gap_s):
            finish_session()
        if current is None:
            start = rx
            current = {"session": len(sessions)+1, "last_source_row": row_no,
                       "first_rx_time_s": rx, "last_rx_time_s": rx,
                       "raw_epochs": 0, "raw_channel_rows": 0, "output_rows": 0,
                       "output_rows_with_cn0": 0, "opaque_output_code_counts": {}}
            if directory:
                name = f"session_{len(sessions)+1:04d}.csv"
                current["csv"] = name
                handle = (directory/name).open("w", newline="", encoding="utf-8")
                writer = csv.writer(handle)
                writer.writerow(["time_s", "cn0", "satellites"])
        current["last_source_row"] = row_no
        current["last_rx_time_s"] = rx
        current["raw_epochs"] += 1
        current["raw_channel_rows"] += count
        for code, value in codes.items():
            totals[code] += value
            current["opaque_output_code_counts"][code] = current["opaque_output_code_counts"].get(code, 0) + value
        b = int(math.floor((rx-start)/bucket_s+1e-9))
        if bucket is not None and bucket != b:
            finish_bucket()
        bucket = b
        nums.append(count)
        if cn is not None:
            cnos.append(cn)
        previous = rx
    finish_session()
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda:file.read(1024*1024), b""):
            digest.update(chunk)
    result = {"source_filename": path.name, "sha256": digest.hexdigest(),
              "n_sessions_time_heuristic": len(sessions), "bucket_s": bucket_s,
              "max_gap_s": max_gap_s, "opaque_output_codes": dict(totals),
              "label_status": "Output code semantics unverified; not attack ground truth",
              "not_available": ["AGC", "satellite_elevation", "protection_level"],
              "sessions": sessions}
    if directory:
        (directory/"manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["inspect", "extract"])
    p.add_argument("workbook", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/private/gps_2d"))
    p.add_argument("--bucket-s", type=float, default=1.0)
    p.add_argument("--max-gap-s", type=float, default=5.0)
    a = p.parse_args(argv)
    result = process(a.workbook, out=a.out if a.command == "extract" else None,
                     bucket_s=a.bucket_s, max_gap_s=a.max_gap_s)
    print(json.dumps({k:v for k,v in result.items() if k != "sessions"}, indent=2))
    print("Session preview:")
    for s in result["sessions"][:20]:
        print(json.dumps(s))
    if len(result["sessions"])>20:
        print("Additional sessions:",len(result["sessions"])-20)


if __name__ == "__main__":
    main()
