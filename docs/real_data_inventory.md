# Verified non-synthetic sources from user's Google Drive (2026-11-14)

This inventory deliberately separates **original measured signal** from
simulation, augmentation and unknown origin. It is not a blanket permission
to republish copyrighted raw files. None of the raw Drive datasets belongs
in this public repository.

| Drive source | Evidence | Approved use | Constraint |
|---|---|---|---|
| `GPS_Raw_Data_Authentic_Data_3D_8_Channels.xlsx` | Source name and Aissou dataset documentation identify authentic GPS receiver observations | Receiver C/N0 baseline, feature statistics, anomaly screening | No independent physical attack labels, AGC, elevation or navigation PL |
| `GPS_Dataset_3D_8_Channels_Authentic_and_Simulated.xlsx` | Combines authentic observations with simulated spoofing | Use ONLY separately identifiable authentic-labelled rows, after ensuring correspondence to original and preserving source blocks | Do NOT use simulated rows as real validation or count duplicate receivers as independent captures |
| `GPS_Data_Simplified_2D_Feature_Map.xlsx` | Flattened Aissou source: class 0 authentic, classes 1-3 simulated spoofing according to source documentation | Class-0 rows for measured GPS analysis; preserve original 14 columns for reuse | Never use attack classes 1-3 as physical GNSS attack evidence |
| `V2x/supplementary_files/Processed_CardRF` | CardRF paper: outdoor captured RF transmissions of actual UAVs and UAV controllers, LOS and NLOS; processed CSVs with device class labels | Separate UAV RF recognition/fingerprinting research | Not GNSS, not GPS jamming, no GNSS-to-flight aligned telemetry |
| `V2x/data_signal_pwr=.../*.mat` | One inspected MATLAB file had `signal.data` complex samples and `signal.fs=40000000`; filenames encode signal/interference power and frequency offsets | Unverified external RF evidence; keep in quarantine | Acquisition / simulation provenance not established, excluded from real-only dataset |
| `V2x/v2x 1 стаття/*` | Analysis artifacts and simulations by filename | Code/reference only | No independently verified measured dataset |
| `UAVAttackData.zip` | Mentioned by user but not located in accessible Google Drive folders | Future real UAV flight-log GNSS validation after acquisition | Not available at time of inventory |

## Aissou source provenance
G. Aissou, *A DATASET for GPS Spoofing Detection on Unmanned Aerial System*,
Mendeley Data version 3 (2022), DOI https://doi.org/10.17632/z7dj3yyzt8.3.
The source's GPS receiver baseline was recorded from a road vehicle and
static rooftop positions, **not actual onboard UAV flight telemetry**.
Do not infer a flight from the dataset title. Spoofing types 1, 2, 3
are simulated variants of authentic signals.

## CardRF source provenance
Cardinal Radio Frequency (CardRF) Dataset, Olusiji O Medaiyese et al.
The attached CardRF paper documents capture in August 2020 at the
AERPAW Lake Wheeler outdoor site, with UAVs, controllers, Wi-Fi
and Bluetooth devices at LOS and BVLOS, including actual flying UAVs.
The `Processed_CardRF/Train/UAV/DJI_M600.csv` export was directly
inspected: 15,000 rows, each with 1024 numeric RF samples, followed by
`Non_Control,DJI_M600,DJI_M600_FLYING`. It is an RF waveform snippet
dataset. It does **not** contain GPS pseudoranges, C/N0, receiver AGC,
vehicle position, flight trajectories or attack onset.

## Safe analysis routes

Receiver observations:
```bash
python -m gnss_interference.gps_xlsx extract \
  data/raw/GPS_Raw_Data_Authentic_Data_3D_8_Channels.xlsx \
  --out data/private/gps_authentic
```

Measured RF snippets (separate experiment):
```bash
python -m gnss_interference.cardrf \
  data/raw/CardRF/Train/UAV/DJI_M600.csv \
  --out data/private/cardrf_train_m600_features.csv
```

Retain `Processed_CardRF/Train` versus `Test` directory grouping.
For Aissou, leave related receiver-time regions and augmented variants
in a single partition to avoid train/test leakage. Unit-test fixtures
are synthetic, but no synthetic observations are used as real
measurements.

## Scientific exclusions

- Do not combine CardRF and Aissou row counts into one sample total.
- Do not report sensitivity/specificity for physical jamming using Aissou.
- Do not assign power or AGC from uncalibrated proxies.
- Do not call 27 timing segments 27 independent flights.
- Do not assume `V2x` folders prove a driving V2X measurement.
- Do not report physical attack-detection performance before independent
  labelled UAV flight logs with onset timestamps are available.
