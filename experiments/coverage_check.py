"""Check of the coverage (median-reliability) criterion.

Old indicator: weight{ i : d_i - wmed > z*sigma } < 1/2  -> always true by the
definition of the weighted median (tautology). Confirmed numerically below.

New criterion (independent of median residuals):
  c_q   = weighted lower q-quantile of d_i  (blockage only increases d_i, so the
          least-degraded satellites stay near the common component up to a
          blocked weight share of 1-q)
  G     = c_med - c_q                         (gap between two order statistics)
  1_cov = [ G <= g_max ] and [ N >= N_min ], g_max = 99th pct of G on clean data
Plus a physical cap in the detector: c_eff = min(c_hat, a+/k_A + Delta_max),
from bound (6): interference cannot lower C/N0 more than the AGC change allows.
"""
import numpy as np

rng = np.random.default_rng(11)
SIG = 1.5      # dB-Hz, C/N0 residual noise
Q = 0.25
N_MIN = 6


def wquant(x, w, q):
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = np.cumsum(w)
    return x[np.searchsorted(cw, q * cw[-1])]


def epoch(rho_target=None, jam=0.0):
    N = int(rng.integers(6, 16))
    th = np.deg2rad(rng.uniform(5, 85, N))
    w = np.sin(th)
    d = rng.normal(0, SIG, N) + jam
    order = np.argsort(th + rng.normal(0, 0.3, N))      # low elevation first
    k = int(rng.integers(0, N + 1)) if rho_target is None else 0
    blk = order[:k]
    d[blk] += rng.uniform(5, 25, k)
    rho = w[blk].sum() / w.sum()
    cm = wquant(d, w, 0.5)
    cq = wquant(d, w, Q)
    old_flag_blocked = (w[(d - cm) > 2 * SIG].sum() >= 0.5 * w.sum())   # old: unreliable
    return dict(N=N, rho=rho, cm=cm, cq=cq, G=cm - cq, old=old_flag_blocked, jam=jam)


# calibration of g_max on clean epochs (no blockage, no jamming)
clean = []
for _ in range(20000):
    N = int(rng.integers(6, 16))
    th = np.deg2rad(rng.uniform(5, 85, N)); w = np.sin(th)
    d = rng.normal(0, SIG, N)
    clean.append(wquant(d, w, 0.5) - wquant(d, w, Q))
clean = np.array(clean)
g_max = np.percentile(clean, 99)
print(f"G on clean data: mean={clean.mean():.2f} dB, p99 (g_max)={g_max:.2f} dB, "
      f"theory 0.674*sigma={0.674*SIG:.2f}")

# blockage only
R = [epoch() for _ in range(60000)]
rho = np.array([r["rho"] for r in R]); G = np.array([r["G"] for r in R])
cm = np.array([r["cm"] for r in R]); cq = np.array([r["cq"] for r in R])
old = np.array([r["old"] for r in R])
flag = G > g_max
print(f"\nOld indicator ever flagged unreliable: {old.sum()} of {len(old)} epochs")
print("\nBlockage only (no interference)")
print("rho_bin     n    flag_new  bias_med  bias_q   p95_med")
for lo, hi in [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .75), (.75, .9), (.9, 1.01)]:
    s = (rho >= lo) & (rho < hi)
    print(f"[{lo:.2f},{hi:.2f}) {s.sum():6d}  {flag[s].mean():7.3f}  {cm[s].mean():7.2f}  "
          f"{cq[s].mean():7.2f}  {np.percentile(cm[s],95):7.2f}")

# jamming + partial blockage: flag must not suppress jamming evidence
print("\nJamming c = 6 dB on all satellites + blockage")
RJ = [epoch(jam=6.0) for _ in range(30000)]
rhoj = np.array([r["rho"] for r in RJ]); Gj = np.array([r["G"] for r in RJ])
for lo, hi in [(0, .1), (.1, .3), (.3, .5), (.5, .75)]:
    s = (rhoj >= lo) & (rhoj < hi)
    print(f"[{lo:.2f},{hi:.2f}) flag rate {(Gj[s] > g_max).mean():.3f}")

# false-evidence check of the fast detector under blockage only (a ~ N(0, sigma_a))
sig_a, mu_a, mu_c, k_A, dmax = 0.3, 3.0, 3.0, 1.0, 3.0
print("\nPer-epoch evidence l(t) under blockage only, share of epochs with l > 0")
print("rho_bin     old(no cov, no cap)  new cov only  new cov + cap")
for lo, hi in [(0, .5), (.5, .75), (.75, 1.01)]:
    s = np.where((rho >= lo) & (rho < hi))[0]
    pos_old = pos_cov = pos_cap = 0
    for i in s:
        a = rng.normal(0, sig_a)
        n = R[i]["N"]; sc = 1.25 * SIG / np.sqrt(n)
        la = mu_a / sig_a**2 * (a - mu_a / 2)
        c = R[i]["cm"]
        lc = mu_c / sc**2 * (c - mu_c / 2)
        cov = G[i] <= g_max
        ceff = min(c, max(a, 0) / k_A + dmax)
        lcap = mu_c / sc**2 * (ceff - mu_c / 2)
        pos_old += (la + lc) > 0
        pos_cov += (la + (lc if cov else 0)) > 0
        pos_cap += (la + (lcap if cov else 0)) > 0
    print(f"[{lo:.2f},{hi:.2f})      {pos_old/len(s):.3f}              {pos_cov/len(s):.3f}         {pos_cap/len(s):.3f}")