from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))

from risk_engine import RiskEngineConfig  # noqa: E402
from shadow_mode import (  # noqa: E402
    CSVObservationSource,
    JSONLDecisionLog,
    MarketObservation,
    ReadOnlyJSONRPCClient,
    ShadowRiskEngine,
    ShadowState,
    replay,
)


def observation(**overrides: float | str) -> MarketObservation:
    values: dict[str, float | str] = {
        "timestamp": "2026-01-01T00:00:00Z",
        "official_lcu_usd": 1.00,
        "official_eth_usd": 100.0,
        "dex_lcu_usd": 0.99,
        "dex_eth_usd": 99.0,
        "reference_lcu_usd": 1.01,
        "reference_eth_usd": 101.0,
        "dex_basis": 0.01,
        "debt_value_usd": 0.62,
        "oracle_age_hours": 6.0,
    }
    values.update(overrides)
    return MarketObservation.from_mapping(values)


class ShadowModeTests(unittest.TestCase):
    def test_median_oracle_and_controller_limits(self) -> None:
        engine = ShadowRiskEngine()
        decision, state = engine.step(
            observation(dex_eth_usd=1_000.0, dex_basis=0.08), ShadowState()
        )
        self.assertEqual(decision.oracle_lcu_usd, 1.0)
        self.assertEqual(decision.oracle_eth_usd, 101.0)
        self.assertLessEqual(decision.recommended_annual_rate - 0.08, 0.05 + 1e-12)
        self.assertGreaterEqual(
            decision.recommended_debt_ceiling - 1.0, -0.05 - 1e-12
        )
        self.assertLessEqual(
            decision.recommended_liquidation_ratio - 1.50, 0.035 + 1e-12
        )
        self.assertTrue(decision.breaker_triggered)
        self.assertTrue(decision.pause_new_draws)
        self.assertEqual(state.breaker_cooldown, 4)

    def test_breaker_cooldown_persists_without_new_trigger(self) -> None:
        engine = ShadowRiskEngine(breaker_cooldown_steps=4)
        _, state = engine.step(observation(dex_basis=0.08), ShadowState())
        calm = observation(timestamp="2026-01-01T06:00:00Z", dex_basis=0.0)
        for expected in (3, 2, 1):
            decision, state = engine.step(calm, state)
            self.assertEqual(state.breaker_cooldown, expected)
            self.assertTrue(decision.pause_new_draws)
        decision, state = engine.step(calm, state)
        self.assertEqual(state.breaker_cooldown, 0)
        self.assertFalse(decision.pause_new_draws)

    def test_read_only_rpc_rejects_transaction_methods_before_network(self) -> None:
        client = ReadOnlyJSONRPCClient("https://rpc.example.invalid")
        for method in (
            "eth_sendTransaction",
            "eth_sendRawTransaction",
            "personal_sign",
            "wallet_addEthereumChain",
        ):
            with self.assertRaises(PermissionError):
                client.call(method, [])

    def test_replay_is_deterministic_and_writes_auditable_log(self) -> None:
        observations = [
            observation(),
            observation(
                timestamp="2026-01-01T06:00:00Z",
                dex_basis=0.03,
                debt_value_usd=0.67,
            ),
        ]
        engine = ShadowRiskEngine(RiskEngineConfig())
        first, first_state = replay(observations, engine)
        second, second_state = replay(observations, engine)
        comparable = lambda item: {
            key: value
            for key, value in item.to_dict().items()
            if key != "evaluated_at"
        }
        self.assertEqual([comparable(item) for item in first], [comparable(item) for item in second])
        self.assertEqual(first_state, second_state)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.jsonl"
            replay(observations, engine, log=JSONLDecisionLog(path))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            required = {
                "observed_at",
                "formula_version",
                "config_sha256",
                "risk_score",
                "baseline_annual_rate",
                "recommended_annual_rate",
                "pause_new_draws",
            }
            self.assertTrue(required.issubset(rows[0]))

    def test_example_csv_is_parseable(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data" / "shadow" / "replay_example.csv"
        rows = list(CSVObservationSource(path))
        self.assertEqual(len(rows), 8)


if __name__ == "__main__":
    unittest.main()
