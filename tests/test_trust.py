"""Regression tests for experimental resource-aware trust decisions."""
import math
import random
import unittest
from dataclasses import replace
from gnss_interference.trust import D, F, XC, XJ, XS, TrustMonitor, TrustParams, costs, margin, rule, thresholds, wquantile

def sky(n=10, seed=1):
    rnd = random.Random(seed)
    return [math.radians(rnd.uniform(10, 85)) for _ in range(n)]

def clean_cn0(elev, rnd, p):
    return [p.b0 + p.b1 * math.sin(th) + rnd.gauss(0, p.sigma_nu) for th in elev]

class TestRule(unittest.TestCase):
    def test_bayes_rule_matches_expected_loss(self):
        rnd = random.Random(3)
        for _ in range(2000):
            p = TrustParams(C_nav=rnd.uniform(10, 1000), phi_inf=rnd.random(),
                tau_m=rnd.uniform(1, 300), C_A=rnd.uniform(1, 500),
                lam0=rnd.uniform(0.01, 5), c_H=rnd.uniform(0.01, 50), T_H=rnd.uniform(0.05, 20))
            m, e = rnd.uniform(0, 300), rnd.uniform(0.02, 1)
            cm, cd, lc = costs(m, e, p)
            alpha, beta, gamma = thresholds(m, e, p)
            for i in range(201):
                prob = i / 200
                if min(abs(prob-x) for x in (alpha, beta, gamma) if math.isfinite(x)) < 1e-6:
                    continue
                self.assertEqual(rule(prob, m, e, p),
                    min({F: prob*cm, D: lc+prob*cd, XJ: (1-prob)*p.C_A},
                        key={F: prob*cm, D: lc+prob*cd, XJ: (1-prob)*p.C_A}.get))

    def test_no_deep_if_insufficient_time(self):
        p = TrustParams()
        for m in (0.0, 0.5, p.T_H):
            for i in range(101):
                self.assertNotEqual(rule(i/100, m, 1.0, p), D)

    def test_margin(self):
        p = TrustParams()
        m = margin(8.0, p)
        self.assertAlmostEqual(8+p.v_b*m+.5*p.a_b*m*m, p.AL)
        self.assertEqual(margin(p.AL, p), 0)

    def test_weighted_quantile_majority(self):
        rnd = random.Random(5)
        for _ in range(500):
            d = [rnd.gauss(0,1.5)+(rnd.uniform(5,25) if rnd.random()<.7 else 0) for _ in range(10)]
            w = [rnd.uniform(.2,1) for _ in d]
            med = wquantile(d, w, .5)
            self.assertLessEqual(sum(wi for di,wi in zip(d,w) if di>med), .5*sum(w))

    def test_bad_weight_is_rejected(self):
        with self.assertRaises(ValueError):
            wquantile([1,2], [0,0], .5)

class TestMonitor(unittest.TestCase):
    def run_monitor(self, seconds, c=0, a=0, blocked=0, params=None, flat=False):
        p = params or TrustParams()
        rnd = random.Random(7)
        elev = sorted(sky())
        mon = TrustMonitor(p)
        seen = []
        for t in range(seconds):
            cn0 = [v-c for v in clean_cn0(elev, rnd, p)]
            for i in range(blocked):
                cn0[i] -= 12
            if flat:
                cn0 = [45.0+rnd.gauss(0,.3) for _ in elev]
            ep = mon.step(float(t), cn0, elev, a+rnd.gauss(0,.5), 8., 1.)
            if ep.launch_deep:
                mon.deep_result(float(t), .01, ep.margin_s)
            seen.append(ep.decision)
        return seen

    def test_clean_fast(self):
        self.assertEqual(set(self.run_monitor(300)), {F})

    def test_joint_jamming(self):
        self.assertEqual(self.run_monitor(30, c=8, a=8)[-1], XJ)

    def test_blockage_not_jamming(self):
        self.assertNotIn(XJ, self.run_monitor(120, blocked=8))

    def test_checks_important(self):
        p = replace(TrustParams(), use_coverage=False, use_cap=False)
        self.assertIn(XJ, self.run_monitor(120, blocked=8, params=p))

    def test_inconsistent(self):
        self.assertEqual(self.run_monitor(20, a=4, flat=True)[-1], XS)

    def test_coverage_insufficient(self):
        ep = TrustMonitor().step(0., [40.,41.,42.], [.5,.8,1.], 0., 8., 1.)
        self.assertEqual(ep.decision, XC)

    def test_mismatched_vectors(self):
        with self.assertRaises(ValueError):
            TrustMonitor().step(0., [40.], [.5,.8], 0., 8., 1.)

if __name__ == "__main__":
    unittest.main()
