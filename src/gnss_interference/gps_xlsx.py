"""Stream an 8-channel GNSS tracking workbook to per-session receiver CSV.

Source layout: 13 eight-channel blocks, two header rows, 1-based Excel rows.
Zero PRNs/CN0 indicate inactive channels (not measured zero dB-Hz).
No attack labels, AGC, satellite elevation, or protection levels are inferred.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from statistics import median

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
FIELDS = (
    "PRN", "Carrier_Doppler_hz", "Pseudorange_m", "RX_time",
    "TOW_at_current_symbol_s", "Carrier_phase_cycles", "EC", "LC",
    "PC", "PIP", "PQP", "TCD", "CN0",
)
N_CHANNELS = 8
N_COLS = len(FIELDS) * N_CHANNELS


def _column_index(address: str) -> int:
    chars = address.rstrip("0123456789")
    col = 0
    for ch in chars:
        col = col * 26 + ord(ch) - ord("A") + 1
    return col - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.itertext()) for node in root.findall(f"{NS}si")]


def _rows(path: Path):
    """Yield (Excel row number, sparse 104-column values), with bounded memory."""
    with zipfile.ZipFile(path) as book:
        strings = _shared_strings(book)
        name = "xl/worksheets/sheet1.xml"
        if name not in book.namelist():
            raise ValueError("Expected the GPS export in the first worksheet")
        with book.open(name) as stream:
            for _, node in ET.iterparse(stream, events=("end",)):
                if node.tag != f"{NS}row":
                    continue
                row = [None] * N_COLS
                for cell in node.findall(f"{NS}c"):
                    col = _column_index(cell.attrib["r"])
                    if col >= N_COLS:
                        continue
                    val = cell.find(f"{NS}v")
                    if val is not None and val.text is not None:
                        row[col] = (strings[int(val.text)]
                                    if cell.get("t") == "s" else val.text)
                yield int(node.attrib["r"]), row
                node.clear()


def _check_headers(rows):
    first_id, h1 = next(rows)
    second_id, h2 = next(rows)
    if (first_id, second_id) != (1, 2):
        raise ValueError("Expected the two header rows at Excel rows 1 and 2")
    for block, field_name in enumerate(FIELDS):
        if h1[block * N_CHANNELS] != field_name:
            raise ValueError(f"Expected {field_name} header in block {block}")
        for ch in range(N_CHANNELS):
            if h2[block * N_CHANNELS + ch] != f"ch{ch}":
                raise ValueError(f"Missing channel ch{ch} in {field_name}")


def _float(raw):
    if raw is None or raw == "":
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def iter_epochs(path: str | Path):
    """Yield (Excel row, RX time in seconds, median C/N0, active count).

    RX_time is receiver-local: do not assume UTC. PRN=0 is an inactive
    channel. A positive PRN with CN0=0 does not supply a CN0 measurement.
    """
    rows = iter(_rows(Path(path)))
    _check_headers(rows)
    for row_id, cells in rows:
        rx = [_float(x) for x in cells[3*N_CHANNELS:4*N_CHANNELS]]
        rx = [v for v in rx if v is not None and v > 0]
        if not rx:
            continue
        prns = [_float(x) for x in cells[:N_CHANNELS]]
        cn0 = [_float(x) for x in cells[12*N_CHANNELS:13*N_CHANNELS]]
        active = sum(prn is not None and prn > 0 for prn in prns)
        valid_cn0 = [v for prn, v in zip(prns, cn0)
                     if prn is not None and prn > 0 and v is not None and v > 0]
        yield row_id, median(rx), median(valid_cn0) if valid_cn0 else None, active


def process(path: str | Path, out: str | Path | None = None,
            max_gap_s: float = 5.0, bucket_s: float = 1.0) -> dict:
    """Separate noncontiguous sessions and downsample into measured bins.

    Output is receiver metrics; never assign attack labels or assume a clean
    baseline. Session boundaries are timing heuristics, not verified trials.
    """
    if max_gap_s <= 0 or bucket_s <= 0:
        raise ValueError("max_gap_s and bucket_s must be positive")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    directory = Path(out) if out else None
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
    sessions = []
    current = None
    previous_t = None
    start_t = 0.0
    active_bucket = None
    cn0_bucket = []
    count_bucket = []
    handle = writer = None

    def finish_bucket():
        nonlocal cn0_bucket, count_bucket, active_bucket
        if active_bucket is None or current is None:
            return
        ts = active_bucket * bucket_s
        cn = median(cn0_bucket) if cn0_bucket else None
        sats = median(count_bucket) if count_bucket else 0.0
        current["output_rows"] += 1
        current["max_satellites"] = max(current["max_satellites"], sats)
        if cn is not None:
            current["output_rows_with_cn0"] += 1
        if writer:
            writer.writerow([f"{ts:.6f}", f"{cn:.5f}" if cn is not None else "", f"{sats:.1f}"])
        active_bucket = None
        cn0_bucket, count_bucket = [], []

    def finish_session():
        nonlocal handle, writer, current
        finish_bucket()
        if handle:
            handle.close()
        handle = writer = None
        if current is not None:
            sessions.append(current)
            current = None

    for row_id, t, cn, sats in iter_epochs(path):
        if previous_t is not None and (t <= previous_t or t - previous_t > max_gap_s):
            finish_session()
        if current is None:
            start_t = t
            current = {
                "session": len(sessions) + 1,
                "first_excel_row": row_id,
                "last_excel_row": row_id,
                "first_rx_time_s": t,
                "last_rx_time_s": t,
                "raw_epochs": 0,
                "output_rows": 0,
                "output_rows_with_cn0": 0,
                "max_satellites": 0.0,
            }
            if directory:
                file_name = f"session_{len(sessions)+1:04d}.csv"
                current["csv"] = file_name
                handle = (directory / file_name).open("w", encoding="utf-8", newline="")
                writer = csv.writer(handle)
                writer.writerow(["time_s", "cn0", "satellites"])
        current["last_excel_row"] = row_id
        current["last_rx_time_s"] = t
        current["raw_epochs"] += 1
        bucket = int(math.floor((t - start_t) / bucket_s + 1e-9))
        if active_bucket is not None and bucket != active_bucket:
            finish_bucket()
        active_bucket = bucket
        count_bucket.append(sats)
        if cn is not None:
            cn0_bucket.append(cn)
        previous_t = t
    finish_session()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    manifest = {
        "source_filename": path.name,
        "sha256": digest.hexdigest(),
        "source_kind": "8-channel Excel receiver export",
        "n_sessions_time_heuristic": len(sessions),
        "bucket_s": bucket_s,
        "max_gap_s": max_gap_s,
        "label_status": "no ground-truth attack annotations supplied",
        "calibration_status": "clean baseline not established",
        "not_available": ["AGC", "satellite_elevation", "protection_level"],
        "sessions": sessions,
    }
    if directory:
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "extract"])
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/private/gps_xlsx"))
    parser.add_argument("--max-gap-s", type=float, default=5.0)
    parser.add_argument("--bucket-s", type=float, default=1.0)
    args = parser.parse_args(argv)
    result = process(args.workbook,
                     out=args.out if args.command == "extract" else None,
                     max_gap_s=args.max_gap_s, bucket_s=args.bucket_s)
    print(json.dumps({k:v for k,v in result.items() if k != "sessions"}, indent=2))
    print("Session preview:")
    for item in result["sessions"][:20]:
        print(json.dumps(item))
    if len(result["sessions"]) > 20:
        print(f"... {len(result['sessions'])-20} additional sessions")


if __name__ == "__main__":
    main()
