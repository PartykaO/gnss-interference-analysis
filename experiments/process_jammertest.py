"""Run the three-way trust rule on the Jammertest 2024 u-blox dataset (Zenodo 15911589).

Reads GNSS_DATASET_JAMMING_SPOOFING.tar.gz directly (no unpacking, .ubx files are skipped).
Written WITHOUT access to the real files: column names are detected heuristically.
Always run step 1 first and look at schema_report.json.

  1) python process_jammertest.py inspect ARCHIVE --out OUT
  2) python process_jammertest.py run     ARCHIVE --out OUT [--calib 60] [--platform ground]

Outputs of `run`: OUT/summary.csv (one row per scenario and method) and
OUT/series/<scenario>.csv (per-epoch c_hat, a, p, margin, decisions).

What the data cannot give, and what the script does instead:
  * no satellite elevation in the observation table -> per-satellite C/N0 baseline from the
    first --calib seconds of each recording, equal weights (the recording must start clean);
  * AGC is the raw u-blox agcCnt -> a = 20*lg(ref/agcCnt), slope k_A is NOT calibrated;
  * protection level -> K * hAcc from NAV-PVT;
  * no deep model -> deep-analysis requests are counted; their verdict is taken from the
    attack label when scenario.json gives attack times, otherwise they resolve as "no interference".
Needs pandas and numpy.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import tarfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gnss_interference.trust import D, F, TrustMonitor, TrustParams, margin  # noqa: E402

WANTED = ("scenario.json", "info.txt", "mon_rf.csv", "nav_pvt.csv", "rinex.csv")
PLATFORMS = {"ground": dict(AL=30.0, v_b=0.2, a_b=0.02), "multirotor": dict(AL=15.0, v_b=0.5, a_b=0.3),
             "fixed_wing": dict(AL=10.0, v_b=1.0, a_b=1.0)}
K_PL = 6.0


def scenarios(archive: str):
    """Yield (scenario_dir, {filename: bytes}) streaming through the tar once."""
    cur, files = None, {}
    with tarfile.open(archive, "r:*") as tar:
        for m in tar:
            if not m.isfile():
                continue
            p = Path(m.name)
            if p.name not in WANTED:
                continue
            key = str(p.parent)
            if cur is not None and key != cur:
                yield cur, files
                files = {}
            cur = key
            files[p.name] = tar.extractfile(m).read()
    if cur is not None:
        yield cur, files


def read_csv(raw: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(raw), sep=None, engine="python")


def find(cols, *patterns):
    for pat in patterns:
        for c in cols:
            if re.search(pat, str(c), re.I):
                return c
    return None


def seconds(df: pd.DataFrame) -> tuple[np.ndarray, str]:
    """Absolute time in seconds and the kind of clock it came from."""
    c = find(df.columns, r"^itow$", r"itow")
    if c is not None:
        return df[c].to_numpy(float) / 1000.0, "itow"
    c = find(df.columns, r"^(utc|time|timestamp|datetime|epoch|date)", r"time")
    if c is not None:
        if pd.api.types.is_numeric_dtype(df[c]):
            v = df[c].to_numpy(float)
            return (v / 1000.0 if np.nanmedian(v) > 1e11 else v), "numeric"
        t = pd.to_datetime(df[c], errors="coerce", utc=True)
        return t.astype("int64").to_numpy() / 1e9, "utc"
    return np.arange(len(df), dtype=float), "index"


def cn0_long(df: pd.DataFrame) -> pd.DataFrame:
    """Return long table: t, sat, cn0 (L1-band signal preferred)."""
    t, kind = seconds(df)
    sat = find(df.columns, r"^(sv|sat|prn|svid|satellite|sv_id)$", r"^(sv|sat|prn)")
    cn_cols = [c for c in df.columns if re.fullmatch(r"S1\w?", str(c))] \
        or [c for c in df.columns if re.search(r"cn0|cno|snr", str(c), re.I)] \
        or [c for c in df.columns if re.fullmatch(r"S\d\w?", str(c))]
    if sat is not None and cn_cols:
        gnss = find(df.columns, r"^(gnss|gnssid|constellation|sys|system)$")
        name = df[sat].astype(str) if gnss is None else df[gnss].astype(str) + "-" + df[sat].astype(str)
        cn = df[cn_cols].apply(pd.to_numeric, errors="coerce").bfill(axis=1).iloc[:, 0]
        out = pd.DataFrame({"t": t, "sat": name, "cn0": cn})
    else:  # wide layout: one column per satellite and signal, e.g. G01_S1C
        wide = [c for c in df.columns if re.fullmatch(r"[GRECJS]\d\d[_ .-]?S1\w?", str(c))]
        if not wide:
            raise ValueError(f"no C/N0 columns recognised in rinex.csv: {list(df.columns)[:40]}")
        out = df[wide].apply(pd.to_numeric, errors="coerce").assign(t=t).melt("t", var_name="sat", value_name="cn0")
        out["sat"] = out["sat"].str[:3]
    out = out.dropna()
    out = out[(out.cn0 > 5) & (out.cn0 < 65)]
    out.attrs["clock"] = kind
    return out


def agc_series(df: pd.DataFrame) -> pd.DataFrame:
    t, kind = seconds(df)
    agc = find(df.columns, r"agccnt", r"agc")
    if agc is None:
        raise ValueError(f"no AGC column in mon_rf.csv: {list(df.columns)}")
    out = pd.DataFrame({"t": t, "agc": pd.to_numeric(df[agc], errors="coerce")})
    for name, pat in (("jam_ind", r"jamind"), ("jam_state", r"jammingstate|jamstate|flags")):
        c = find(df.columns, pat)
        if c is not None:
            out[name] = pd.to_numeric(df[c], errors="coerce")
    blk = find(df.columns, r"blockid|block|band|rfblock")
    if blk is not None:  # one RF block per band: keep the first (L1)
        out = out[df[blk].to_numpy() == sorted(df[blk].dropna().unique())[0]]
    out.attrs["clock"] = kind
    return out.dropna(subset=["agc"])


def pvt_series(df: pd.DataFrame) -> pd.DataFrame:
    t, kind = seconds(df)
    out = pd.DataFrame({"t": t})
    for name, pat, scale in (("hacc", r"^hacc$|hacc", None), ("numsv", r"numsv", 1.0), ("fix", r"fixtype", 1.0)):
        c = find(df.columns, pat)
        if c is not None:
            v = pd.to_numeric(df[c], errors="coerce")
            if name == "hacc":  # UBX stores mm; a parsed table may already be in metres
                v = v / 1000.0 if v.median() > 200 else v
            out[name] = v
    out.attrs["clock"] = kind
    return out


def attack_windows(meta, t0: float, t_end: float):
    """Find (start, end) pairs in scenario.json, as seconds relative to recording start if possible."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            keys = {k.lower(): k for k in o}
            s = next((keys[k] for k in keys if re.search(r"start", k)), None)
            e = next((keys[k] for k in keys if re.search(r"end|stop", k)), None)
            if s and e and not isinstance(o[s], (dict, list)) and not isinstance(o[e], (dict, list)):
                found.append((o[s], o[e]))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(meta)
    out = []
    for s, e in found:
        try:
            if isinstance(s, (int, float)):
                a, b = float(s), float(e)
            else:
                a = pd.Timestamp(s, tz="UTC").timestamp() if pd.Timestamp(s).tzinfo is None else pd.Timestamp(s).timestamp()
                b = pd.Timestamp(e, tz="UTC").timestamp() if pd.Timestamp(e).tzinfo is None else pd.Timestamp(e).timestamp()
        except Exception:
            continue
        if b > a and t0 - 1 <= a <= t_end + 1:
            out.append((a, b))
    return out


def inspect(archive: str, out: Path):
    report = {}
    for name, files in scenarios(archive):
        entry = {}
        for fn, raw in files.items():
            if fn.endswith(".csv"):
                try:
                    df = read_csv(raw)
                    entry[fn] = {"rows": len(df), "columns": [str(c) for c in df.columns],
                                 "head": df.head(3).astype(str).values.tolist()}
                except Exception as exc:
                    entry[fn] = {"error": repr(exc)}
            elif fn == "scenario.json":
                try:
                    entry[fn] = json.loads(raw)
                except Exception as exc:
                    entry[fn] = {"error": repr(exc)}
            else:
                entry[fn] = raw.decode("utf-8", "replace")[:1500]
        report[name] = entry
        print(name, {k: (v.get("rows") if isinstance(v, dict) else "") for k, v in entry.items() if k.endswith(".csv")})
    out.mkdir(parents=True, exist_ok=True)
    (out / "schema_report.json").write_text(json.dumps(report, indent=1, default=str)[:4_000_000])
    print(f"{len(report)} scenarios -> {out / 'schema_report.json'}")


def run_one(name: str, files: dict, calib: float, platform: str, out: Path):
    obs = cn0_long(read_csv(files["rinex.csv"]))
    rf = agc_series(read_csv(files["mon_rf.csv"]))
    pvt = pvt_series(read_csv(files["nav_pvt.csv"])) if "nav_pvt.csv" in files else None
    clocks = {obs.attrs["clock"], rf.attrs["clock"]} | ({pvt.attrs["clock"]} if pvt is not None else set())
    aligned = len(clocks) == 1 and "index" not in clocks
    tabs = [obs, rf] + ([pvt] if pvt is not None else [])
    origin = min(x.t.min() for x in tabs) if aligned else None
    for x in tabs:  # 1 s grid; if clocks differ, each file is counted from its own start
        x["k"] = np.round(x.t - (origin if aligned else x.t.min())).astype(int)
    t_abs0 = obs.t.min()
    n_ep = int(min(x.k.max() for x in tabs)) + 1
    base = obs[obs.k < calib].groupby("sat").cn0.median()
    base = base[obs[obs.k < calib].groupby("sat").cn0.count() >= calib / 4]
    if len(base) < 4:
        raise ValueError("fewer than 4 satellites in the calibration window")
    agc = rf.groupby("k").agc.median()
    agc_ref = agc[agc.index < calib].median()
    a = (20 * np.log10(agc_ref / agc.clip(lower=1))).reindex(range(n_ep)).ffill().bfill()
    sigma_a = max(0.3, 1.4826 * float((a[a.index < calib] - a[a.index < calib].median()).abs().median()))
    cal = obs[(obs.k < calib) & obs.sat.isin(base.index)]
    resid = cal.cn0 - cal.sat.map(base)
    sigma_nu = max(0.5, 1.4826 * float(resid.abs().median()))
    hacc = pvt.groupby("k").hacc.median().reindex(range(n_ep)).ffill() if pvt is not None and "hacc" in pvt else None
    jam_state = rf.groupby("k").jam_state.max().reindex(range(n_ep)) if "jam_state" in rf else None

    meta = json.loads(files["scenario.json"]) if "scenario.json" in files else {}
    wins = attack_windows(meta, t_abs0, t_abs0 + n_ep) if aligned else []
    label = np.zeros(n_ep, bool)
    for s, e in wins:
        label[max(0, int(s - t_abs0)):max(0, int(e - t_abs0)) + 1] = True
    has_label = bool(wins)

    # flat profile: baseline is per satellite, so b0 = b1 = 0 and d_i = base_i - cn0_i
    # spread_min = 0: the equal-C/N0 spoofing test needs raw values against elevation, not available here
    prm = replace(TrustParams(), b0=0.0, b1=0.0, spread_min=0.0, sigma_nu=sigma_nu, sigma_a=sigma_a,
                  **PLATFORMS[platform])
    variants = {"proposed": prm, "fast_only": replace(prm, T_H=1e9)}
    by_k = {k: g for k, g in obs[obs.sat.isin(base.index)].groupby("k")}
    equal_elev = math.pi / 2          # sin = 1 -> equal weights
    series = pd.DataFrame({"k": range(n_ep), "a": a.to_numpy(), "label": label})
    rows = []
    for vname, p in variants.items():
        mon = TrustMonitor(p)
        dec, prob, marg, chat, launches, late, pending = [], [], [], [], 0, 0, None
        for k in range(n_ep):
            if pending is not None and k >= pending:
                if mon.state == D:
                    mon.deep_result(float(k), 0.99 if (has_label and label[k]) else 0.01, marg[-1] if marg else 0.0)
                pending = None
            g = by_k.get(k)
            cn = [] if g is None else (g.cn0 - g.sat.map(base)).tolist()   # C/N0 relative to baseline
            pl = K_PL * float(hacc.iloc[k]) if hacc is not None and not math.isnan(hacc.iloc[k]) else 6.0
            ep = mon.step(float(k), cn, [equal_elev] * len(cn), float(a.iloc[k]), pl, 1.0)
            if ep.launch_deep:
                launches += 1
                late += ep.margin_s <= p.T_H
                pending = k + int(round(p.T_H))
            dec.append(ep.decision); prob.append(ep.prob); marg.append(ep.margin_s)
            chat.append(np.nan if ep.c_hat is None else ep.c_hat)
        series[f"decision_{vname}"] = dec
        if vname == "proposed":
            series["c_hat"], series["p"], series["margin_s"] = chat, prob, marg
        d = np.array(dec)
        distrust = np.isin(d, ["XJ", "XS", "XC"])
        clean = ~label if has_label else (np.arange(n_ep) < calib)
        row = dict(scenario=name, method=vname, epochs=n_ep, satellites=len(base), clocks_aligned=aligned,
                   labelled=has_label, sigma_nu=round(sigma_nu, 2), sigma_a=round(sigma_a, 2),
                   share_distrust=float(distrust.mean()), share_XJ=float((d == "XJ").mean()),
                   share_XS=float((d == "XS").mean()), share_XC=float((d == "XC").mean()),
                   deep_launches=launches, late_launches=int(late),
                   distrust_in_clean=float(distrust[clean].mean()) if clean.any() else None)
        if has_label:
            first = np.flatnonzero(label)[0]
            hit = np.flatnonzero(distrust[first:] & label[first:])
            row.update(attack_share=float(label.mean()), distrust_in_attack=float(distrust[label].mean()),
                       delay_s=int(hit[0]) if len(hit) else None)
        if jam_state is not None:
            row["ublox_jam_flag_share"] = float((jam_state.fillna(0) > 0).mean())
        rows.append(row)
    sdir = out / "series"; sdir.mkdir(parents=True, exist_ok=True)
    series.to_csv(sdir / (re.sub(r"[^\w.-]+", "_", name)[-150:] + ".csv"), index=False)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("inspect", "run"))
    ap.add_argument("archive")
    ap.add_argument("--out", default="outputs/jammertest2024")
    ap.add_argument("--calib", type=float, default=60.0, help="clean seconds at the start of each recording")
    ap.add_argument("--platform", choices=tuple(PLATFORMS), default="ground")
    a = ap.parse_args()
    out = Path(a.out)
    if a.mode == "inspect":
        return inspect(a.archive, out)
    rows, failed = [], []
    for name, files in scenarios(a.archive):
        if "rinex.csv" not in files or "mon_rf.csv" not in files:
            failed.append((name, "rinex.csv or mon_rf.csv missing")); continue
        try:
            rows += run_one(name, files, a.calib, a.platform, out)
            print("ok  ", name)
        except Exception as exc:
            failed.append((name, repr(exc))); print("FAIL", name, exc)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "summary.csv", index=False)
    (out / "failed.json").write_text(json.dumps(failed, indent=1))
    print(f"{len(rows) // 2} scenarios processed, {len(failed)} failed -> {out / 'summary.csv'}")


if __name__ == "__main__":
    main()