# Import of an eight-channel GNSS Excel recording

Use the stream-processing adapter for the Excel tracking export containing
13 groups of eight channels, starting with PRN and ending with CN0.
The original file remains on the user's Drive or local disk; do not commit it.

Run after installing the package (`python -m pip install -e .`):

```bash
python -m gnss_interference.gps_xlsx inspect data/raw/receiver.xlsx
python -m gnss_interference.gps_xlsx extract data/raw/receiver.xlsx --out data/private/gps_xlsx --bucket-s 1 --max-gap-s 5
```

The adapter validates the two header rows, ignores zero-padded inactive
channels, computes per-epoch median positive C/N0 (dB-Hz), and counts channels
with a positive PRN. **The latter is an active-channel proxy, not a guaranteed
unique satellite count.** The 1-second CSV is a median of the measurements
within each time bin; original high-frequency measurements are not overwritten.

Timing discontinuities larger than the configured gap, equal or decreasing
receiver times, create separate candidate sessions. Their boundaries are
heuristics and must not be treated as validated experimental scenarios.
The exported `manifest.json` stores timing, counts, and SHA-256 of the source.
`time_s` is relative to the start of each candidate session, not UTC.

Output paths are under `data/private/` and ignored by Git. The CSV fields
`time_s,cn0,satellites` can be opened by the repository's existing
`gnss-analyse` CLI **only after confirming a genuinely clean baseline
interval and independent scenario annotations**. No AGC, satellite elevations,
protection levels, clean labels, or attack labels can be recovered from the
visible columns of this spreadsheet. The separate trust model depends on
validated AGC, elevation, and protection level and must not silently fill
missing features with constants.

Do not compute scientific detection rates, delays, or false alarms per hour
from these unlabeled candidate sessions.

## Simplified 2D GPS feature-map export

The `GPS_Data_Simplified_2D_Feature_Map.xlsx` export is in long format:
one row per channel observation with the 14 columns
`PRN,DO,PD,RX,TOW,CP,EC,LC,PC,PIP,PQP,TCD,CN0,Output`.

```bash
python -m gnss_interference.gps_2d inspect data/raw/GPS_Data_Simplified_2D_Feature_Map.xlsx
python -m gnss_interference.gps_2d extract data/raw/GPS_Data_Simplified_2D_Feature_Map.xlsx --out data/private/gps_2d
```

This exporter groups channel observations by receiver-local RX time,
then splits discontinuous sessions and downsamples positive C/N0 into
one-second medians. It records the counts of each original `Output`
value in `manifest.json`, **without mapping any number to attack types**.
Counts are not validated event labels. A channel count is not necessarily
a distinct-satellite count. The original `Output` column should be
retained in the source workbook for future study after obtaining its
label dictionary and independent provenance.

The wide 3D workbook with an additional `Output` block can be processed
by `gps_xlsx` for observables, but that module intentionally ignores
the code block. Do not regard the modified wide workbook and the
original tracking workbook as independent recordings.

Both importers keep local output under `data/private/` (Git ignored).
Never publish raw files or calculated CSV unless you have reviewed
dataset ownership, permissions, privacy, and research reproducibility.
