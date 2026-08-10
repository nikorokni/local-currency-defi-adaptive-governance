from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from model import (  # noqa: E402
    MAIN_ARCHITECTURES,
    SimulationConfig,
    build_market_paths,
    historical_joint_windows,
    moving_block_bootstrap_joint,
    simulate_protocol,
)


class ModelTests(unittest.TestCase):
    def test_joint_bootstrap_is_deterministic(self) -> None:
        values = np.column_stack(
            [np.linspace(0.01, 0.08, 12), np.linspace(-0.20, 0.25, 12)]
        )
        first = moving_block_bootstrap_joint(values, 25, 4, 2, 7)
        second = moving_block_bootstrap_joint(values, 25, 4, 2, 7)
        self.assertEqual(first.shape, (25, 4, 2))
        np.testing.assert_array_equal(first, second)

    def test_historical_window_count(self) -> None:
        values = np.column_stack([np.arange(42), np.arange(42) / 10])
        windows = historical_joint_windows(values, horizon=4)
        self.assertEqual(windows.shape, (39, 4, 2))
        np.testing.assert_array_equal(windows[0], values[:4])
        np.testing.assert_array_equal(windows[-1], values[-4:])

    def test_disaggregation_preserves_monthly_returns(self) -> None:
        macro = np.array(
            [
                [[0.03, -0.10], [0.05, 0.08], [0.01, -0.04], [0.07, 0.15]],
                [[0.02, 0.05], [0.00, -0.20], [0.08, 0.12], [0.04, -0.03]],
            ]
        )
        cfg = SimulationConfig()
        market = build_market_paths(macro, seed=11, config=cfg, attack_probability=0)
        for month in range(cfg.horizon_months):
            start = month * cfg.steps_per_month
            stop = start + cfg.steps_per_month
            fx_product = np.exp(market.fx_step_log_return[:, start:stop].sum(axis=1))
            eth_product = np.exp(market.eth_step_log_return[:, start:stop].sum(axis=1))
            np.testing.assert_allclose(fx_product, 1 / (1 + macro[:, month, 0]), rtol=1e-12)
            np.testing.assert_allclose(eth_product, 1 + macro[:, month, 1], rtol=1e-12)

    def test_multi_oracle_limits_single_source_attack(self) -> None:
        macro = np.zeros((120, 4, 2))
        market = build_market_paths(macro, seed=19, attack_probability=1.0)
        static, _ = simulate_protocol(
            market, MAIN_ARCHITECTURES[0], "ARS", keep_paths=0, attack_scale=2.0
        )
        robust, _ = simulate_protocol(
            market, MAIN_ARCHITECTURES[-1], "ARS", keep_paths=0, attack_scale=2.0
        )
        self.assertLess(
            robust["maximum_abs_oracle_error"].quantile(0.95),
            static["maximum_abs_oracle_error"].quantile(0.95),
        )
        self.assertLess(robust["bad_debt_event"].mean(), static["bad_debt_event"].mean())

    def test_breaker_weakly_reduces_severe_depeg(self) -> None:
        macro = np.tile(np.array([[[0.08, -0.25], [0.10, -0.15], [0.06, 0.05], [0.12, -0.20]]]), (180, 1, 1))
        market = build_market_paths(macro, seed=23, attack_probability=0.25)
        adaptive, _ = simulate_protocol(
            market, MAIN_ARCHITECTURES[2], "TRY", keep_paths=0
        )
        breaker, _ = simulate_protocol(
            market, MAIN_ARCHITECTURES[3], "TRY", keep_paths=0
        )
        self.assertLessEqual(
            breaker["deep_depeg_event"].mean(),
            adaptive["deep_depeg_event"].mean(),
        )
        self.assertLess(breaker["credit_issued"].mean(), adaptive["credit_issued"].mean())
        self.assertGreater(breaker["pause_share"].mean(), 0)

    def test_outputs_are_finite_and_bounded(self) -> None:
        macro = np.tile(np.array([[[0.03, -0.10], [0.02, 0.08], [0.05, -0.12], [0.01, 0.04]]]), (24, 1, 1))
        market = build_market_paths(macro, seed=29, attack_probability=0.2)
        results, monthly = simulate_protocol(
            market, MAIN_ARCHITECTURES[-1], "ARS", keep_paths=2
        )
        self.assertTrue(np.isfinite(results.select_dtypes(include=[np.number])).all().all())
        self.assertTrue(np.isfinite(monthly.select_dtypes(include=[np.number])).all().all())
        self.assertTrue(results["mean_debt_ceiling"].between(0.20, 1.0).all())
        self.assertTrue(results["mean_liquidation_ratio"].between(1.50, 2.20).all())
        self.assertTrue(results["pause_share"].between(0.0, 1.0).all())
        self.assertTrue((results["bad_debt"] >= 0).all())


if __name__ == "__main__":
    unittest.main()

