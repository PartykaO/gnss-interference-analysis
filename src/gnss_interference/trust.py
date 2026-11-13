"""Exploratory resource-aware GNSS trust monitor, not a validated jammer classifier.

Input AGC must be a calibrated positive input-power-change proxy in dB.
Deep verification is EXTERNAL; no trained model is included. Parameters and
posterior are illustrative, not calibrated confidence estimates.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from statistics import median

F, D, XJ, XS, XC = "F", "D", "XJ", "XS", "XC"


@dataclass(frozen=True)
class TrustParams:
    b0: float = 37.0
    b1: float = 11.0
    sigma_nu: float = 1.5
    sigma_a: float = 1.0
    k_A: float = 1.0
    delta_max: float = 3.0
    z: float = 3.0
    q: float = 0.25
    g_max: float = 2.75
    n_min: int = 6
    spread_min: float = 0.5
    k_S: int = 3
    W_S: int = 5
    mu_a: float = 2.0
    mu_c: float = 2.0
    prior: float = 0.05
    sigma_b: float = 1.0
    eta: float = 0.3
    s_max: float = 8.0
    C_nav: float = 100.0
    phi_inf: float = 0.2
    tau_m: float = 30.0
    C_A: float = 20.0
    lam0: float = 1.0
    c_H: float = 5.0
    T_H: float = 2.0
    h: float = 0.02
    T_dw: float = 5.0
    AL: float = 30.0
    v_b: float = 0.2
    a_b: float = 0.02
    use_coverage: bool = True
    use_cap: bool = True
    fixed_thresholds: tuple[float, float, float] | None = None


def wquantile(values: list[float], weights: list[float], q: float) -> float:
    if len(values) != len(weights) or not values or not 0 <= q <= 1:
        raise ValueError("Invalid weighted quantile input")
    if any(not math.isfinite(v) for v in values) or any(not math.isfinite(w) or w < 0 for w in weights):
        raise ValueError("Nonfinite values or invalid weights")
    pairs = sorted(zip(values, weights))
    total = sum(weights)
    if total <= 0:
        raise ValueError("Weights must sum to a positive number")
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= q * total:
            return value
    return pairs[-1][0]


def margin(pl: float, p: TrustParams) -> float:
    if not math.isfinite(pl) or p.a_b < 0 or p.v_b < 0:
        raise ValueError("Invalid protection level or margin bounds")
    if pl >= p.AL:
        return 0.0
    if p.a_b == 0:
        return (p.AL - pl) / p.v_b if p.v_b > 0 else math.inf
    return (math.sqrt(p.v_b ** 2 + 2 * p.a_b * (p.AL - pl)) - p.v_b) / p.a_b


def costs(m: float, e: float, p: TrustParams) -> tuple[float, float, float]:
    c_m = p.C_nav * (p.phi_inf + (1 - p.phi_inf) * math.exp(-m / p.tau_m))
    psi = 1.0 if m <= p.T_H else p.T_H / m
    return c_m, c_m * psi, p.lam0 / max(e, 1e-6) * p.c_H


def thresholds(m: float, e: float, p: TrustParams) -> tuple[float, float, float]:
    if p.fixed_thresholds is not None:
        return p.fixed_thresholds
    c_m, c_d, lc = costs(m, e, p)
    alpha = lc / (c_m - c_d) if c_m > c_d else math.inf
    beta = (p.C_A - lc) / (p.C_A + c_d)
    gamma = p.C_A / (p.C_A + c_m)
    return alpha, beta, gamma


def rule(prob: float, m: float, e: float, p: TrustParams) -> str:
    alpha, beta, gamma = thresholds(m, e, p)
    if alpha < beta:
        return F if prob < alpha else (D if prob < beta else XJ)
    return F if prob < gamma else XJ


@dataclass
class Epoch:
    decision: str
    prob: float
    margin_s: float
    c_hat: float | None = None
    gap: float | None = None
    coverage_ok: bool | None = None
    credible: bool | None = None
    launch_deep: bool = False


@dataclass
class TrustMonitor:
    params: TrustParams = field(default_factory=TrustParams)
    state: str = F
    S: float = 0.0
    _since: float = -1e9
    _omega: deque = field(default_factory=deque)
    _deep_running: bool = False

    def _enter(self, state: str, t: float) -> None:
        if state != self.state:
            self.state = state
            self._since = t
            if state != D:
                self._deep_running = False

    def deep_result(self, t: float, p_h: float, m: float) -> str:
        """Supply a real independent deep model's calibrated score, never a ground-truth label."""
        if not 0 <= p_h <= 1:
            raise ValueError("Deep score must be in [0,1]")
        gamma = thresholds(m, 1.0, self.params)[2]
        self._deep_running = False
        if p_h >= gamma:
            self.S = self.params.s_max
            self._enter(XJ, t)
        else:
            self.S = 0.0
            self._enter(F, t)
        return self.state

    def step(self, t: float, cn0: list[float], elev_rad: list[float], a: float,
             pl: float, energy: float) -> Epoch:
        p = self.params
        n = len(cn0)
        if n != len(elev_rad) or not all(math.isfinite(x) for x in cn0 + elev_rad):
            raise ValueError("C/N0 and elevation must be equal-length finite vectors")
        if not all(math.isfinite(x) for x in (t, a, pl, energy)) or not 0 < energy <= 1:
            raise ValueError("Invalid timestamp, AGC proxy, protection level or energy share")
        if any(not 0 <= x <= math.pi / 2 for x in elev_rad):
            raise ValueError("Elevation must be in radians between 0 and pi/2")
        m = margin(pl, p) if n >= 4 else 0.0
        if n < 4:
            self._enter(XC, t)
            return Epoch(XC, self._prob(), 0.0)
        w = [math.sin(th) for th in elev_rad]
        d = [p.b0 + p.b1 * math.sin(th) - v for th, v in zip(elev_rad, cn0)]
        c_hat = wquantile(d, w, 0.5)
        gap = c_hat - wquantile(d, w, p.q)
        cov = (gap <= p.g_max and n >= p.n_min) if p.use_coverage else True
        sigma_c = 1.2533 * p.sigma_nu / math.sqrt(n)
        med_raw = median(cn0)
        spread = median(abs(v - med_raw) for v in cn0)
        bad = (c_hat < -p.z * sigma_c
               or (a > p.z * p.sigma_a and c_hat > a / p.k_A + p.delta_max + p.z * sigma_c)
               or (n >= p.n_min and spread < p.spread_min))
        self._omega.append(0 if bad else 1)
        while len(self._omega) > p.W_S:
            self._omega.popleft()
        if len(self._omega) - sum(self._omega) >= p.k_S:
            self._enter(XS, t)
            return Epoch(XS, self._prob(), m, c_hat, gap, cov, False)
        if not bad:
            c_eff = min(c_hat, max(a, 0.0) / p.k_A + p.delta_max) if p.use_cap else c_hat
            ell = p.mu_a / p.sigma_a ** 2 * (a - p.mu_a / 2)
            if cov:
                ell += p.mu_c / (sigma_c ** 2 + p.sigma_b ** 2) * (c_eff - p.mu_c / 2)
            self.S = min(max(0.0, self.S + p.eta * ell), p.s_max)
        prob = self._prob()
        alpha, beta, gamma = thresholds(m, energy, p)
        window = alpha < beta
        upper = beta if window else gamma
        dwell_ok = (t - self._since) >= p.T_dw
        launch = False
        if self.state in (XS, XC):
            if self.state == XC or dwell_ok:
                self._enter(F, t)
        if self.state == XJ:
            if prob < upper - p.h and dwell_ok:
                self._enter(F, t)
        if self.state == D:
            if prob >= upper:
                self._enter(XJ, t)
            elif not self._deep_running:
                self._enter(F, t)
        if self.state == F:
            if prob >= upper:
                self._enter(XJ, t)
            elif window and prob >= alpha and dwell_ok:
                self._enter(D, t)
                self._deep_running = True
                launch = True
        return Epoch(self.state, prob, m, c_hat, gap, cov, not bad, launch)

    def _prob(self) -> float:
        pr = self.params.prior
        return 1.0 / (1.0 + (1 - pr) / pr * math.exp(-self.S))
