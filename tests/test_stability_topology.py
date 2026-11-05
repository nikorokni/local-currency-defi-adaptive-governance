from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from risk_engine import (  # noqa: E402
    RiskEngineConfig,
    compute_risk_score,
    compute_targets,
    update_ewma_variance,
)
from stability_topology import (  # noqa: E402
    PARAMETER_SPECS,
    STRESS_REGIMES,
    baseline_parameters,
    evaluate_configuration,
    latin_hypercube,
    simulate_reduced_closed_loop,
    vietoris_rips_betti_01,
)


class StabilityTopologyTests(unittest.TestCase):
    def test_parameterised_defaults_reproduce_paper_equations(self) -> None:
        cfg = RiskEngineConfig()
        variance = update_ewma_variance(0.01**2, 0.03, cfg.ewma_memory)
        self.assertAlmostEqual(float(variance), 0.92 * 0.01**2 + 0.08 * 0.03**2)
        risk = compute_risk_score(0.02, 0.03, 0.04, 0.80, cfg)
        expected = np.clip(4 * 0.02 + 3.2 * 0.03 + 1.8 * 0.04 + 0.9 * 0.08, 0, 1)
        self.assertAlmostEqual(float(risk), float(expected))
        targets = compute_targets(risk, 0.80, cfg)
        self.assertAlmostEqual(float(targets[0]), 0.08 + 0.90 * risk + 0.35 * 0.05)

    def test_latin_hypercube_is_deterministic_and_bounded(self) -> None:
        first = latin_hypercube(24, seed=17)
        second = latin_hypercube(24, seed=17)
        np.testing.assert_array_equal(first.to_numpy(), second.to_numpy())
        for spec in PARAMETER_SPECS:
            self.assertTrue(first[spec.name].between(spec.lower, spec.upper).all())

    def test_reduced_probe_is_finite_and_bounded(self) -> None:
        result = simulate_reduced_closed_loop(
            RiskEngineConfig(), STRESS_REGIMES[0], delay_steps=8, n_steps=180, tail_steps=40
        )
        self.assertTrue(result["bounded"])
        for key in (
            "tail_step_norm",
            "tail_range",
            "final_spread",
            "contraction_ratio",
        ):
            self.assertTrue(np.isfinite(result[key]))
        aggregate = evaluate_configuration(baseline_parameters())
        self.assertTrue(0.0 <= aggregate["converged_case_share"] <= 1.0)
        self.assertTrue(0.0 <= aggregate["bounded_case_share"] <= 1.0)

    def test_vietoris_rips_detects_two_components(self) -> None:
        points = np.array([[0.0], [0.1], [0.2], [2.0], [2.1], [2.2]])
        distance = np.abs(points - points.T)
        beta0, beta1, _, _ = vietoris_rips_betti_01(distance, epsilon=0.15)
        self.assertEqual(beta0, 2)
        self.assertEqual(beta1, 0)


if __name__ == "__main__":
    unittest.main()
