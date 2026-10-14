"""Read-only replay and shadow evaluation for the adaptive risk engine.

This module deliberately contains no transaction construction, signing, or
broadcasting path.  It observes data, evolves an isolated shadow state, and
emits recommendations that an operator can compare with the unchanged baseline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from urllib.request import Request, urlopen

import numpy as np

from risk_engine import (
    RiskEngineConfig,
    breaker_trigger,
    compute_risk_score,
    compute_targets,
    rate_limited_update,
    update_ewma_variance,
)


FORMULA_VERSION = "section-5-controller-v1"
REQUIRED_OBSERVATION_FIELDS = (
    "timestamp",
    "official_lcu_usd",
    "official_eth_usd",
    "dex_lcu_usd",
    "dex_eth_usd",
    "reference_lcu_usd",
    "reference_eth_usd",
    "dex_basis",
    "debt_value_usd",
    "oracle_age_hours",
)


@dataclass(frozen=True)
class MarketObservation:
    """One read-only input vector at a risk-engine evaluation time."""

    timestamp: str
    official_lcu_usd: float
    official_eth_usd: float
    dex_lcu_usd: float
    dex_eth_usd: float
    reference_lcu_usd: float
    reference_eth_usd: float
    dex_basis: float
    debt_value_usd: float
    oracle_age_hours: float
    ratio_log_return: float | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "MarketObservation":
        missing = [key for key in REQUIRED_OBSERVATION_FIELDS if key not in row]
        if missing:
            raise ValueError(f"missing observation fields: {', '.join(missing)}")
        values: dict[str, Any] = {"timestamp": str(row["timestamp"])}
        for key in REQUIRED_OBSERVATION_FIELDS[1:]:
            values[key] = float(row[key])
        optional_return = row.get("ratio_log_return")
        if optional_return not in (None, ""):
            values["ratio_log_return"] = float(optional_return)
        observation = cls(**values)
        observation.validate()
        return observation

    def validate(self) -> None:
        if not self.timestamp.strip():
            raise ValueError("timestamp must be non-empty")
        prices = (
            self.official_lcu_usd,
            self.official_eth_usd,
            self.dex_lcu_usd,
            self.dex_eth_usd,
            self.reference_lcu_usd,
            self.reference_eth_usd,
        )
        if any(not math.isfinite(value) or value <= 0 for value in prices):
            raise ValueError("all oracle prices must be finite and strictly positive")
        nonnegative = (self.dex_basis, self.debt_value_usd, self.oracle_age_hours)
        if any(not math.isfinite(value) or value < 0 for value in nonnegative):
            raise ValueError("basis, debt value, and oracle age must be finite and non-negative")
        if self.ratio_log_return is not None and not math.isfinite(
            self.ratio_log_return
        ):
            raise ValueError("ratio_log_return must be finite when provided")


@dataclass
class ShadowState:
    """Isolated controller state; it is never written back to a protocol."""

    annual_rate: float = 0.08
    debt_ceiling: float = 1.0
    liquidation_ratio: float = 1.50
    ewma_variance: float = 0.01**2
    breaker_cooldown: int = 0
    previous_oracle_ratio: float | None = None

    def validate(self) -> None:
        numeric = (
            self.annual_rate,
            self.debt_ceiling,
            self.liquidation_ratio,
            self.ewma_variance,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("shadow state contains a non-finite value")
        if self.debt_ceiling <= 0 or self.ewma_variance < 0:
            raise ValueError("debt ceiling must be positive and variance non-negative")
        if self.breaker_cooldown < 0:
            raise ValueError("breaker cooldown must be non-negative")


@dataclass(frozen=True)
class ShadowDecision:
    """Auditable recommendation plus all intermediate controller variables."""

    observed_at: str
    evaluated_at: str
    formula_version: str
    config_sha256: str
    oracle_lcu_usd: float
    oracle_eth_usd: float
    oracle_ratio: float
    ratio_log_return: float
    source_disagreement: float
    observed_volatility: float
    dex_basis: float
    debt_value_usd: float
    utilization: float
    risk_score: float
    volatility_component: float
    basis_component: float
    disagreement_component: float
    utilization_component: float
    baseline_annual_rate: float
    baseline_debt_ceiling: float
    baseline_liquidation_ratio: float
    target_annual_rate: float
    target_debt_ceiling: float
    target_liquidation_ratio: float
    recommended_annual_rate: float
    recommended_debt_ceiling: float
    recommended_liquidation_ratio: float
    breaker_triggered: bool
    pause_new_draws: bool
    breaker_cooldown: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: np.ndarray | float) -> float:
    return float(np.asarray(value).item())


def _config_hash(config: RiskEngineConfig, cooldown_steps: int) -> str:
    payload = {"controller": asdict(config), "breaker_cooldown_steps": cooldown_steps}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ShadowRiskEngine:
    """Evaluate Section 5 without any authority to execute recommendations."""

    def __init__(
        self,
        config: RiskEngineConfig | None = None,
        breaker_cooldown_steps: int = 4,
    ) -> None:
        self.config = config or RiskEngineConfig()
        if breaker_cooldown_steps < 1:
            raise ValueError("breaker_cooldown_steps must be positive")
        self.breaker_cooldown_steps = breaker_cooldown_steps
        self.config_sha256 = _config_hash(self.config, breaker_cooldown_steps)

    def step(
        self, observation: MarketObservation, state: ShadowState
    ) -> tuple[ShadowDecision, ShadowState]:
        observation.validate()
        state.validate()

        lcu_sources = np.array(
            [
                observation.official_lcu_usd,
                observation.dex_lcu_usd,
                observation.reference_lcu_usd,
            ]
        )
        eth_sources = np.array(
            [
                observation.official_eth_usd,
                observation.dex_eth_usd,
                observation.reference_eth_usd,
            ]
        )
        oracle_lcu = float(np.median(lcu_sources))
        oracle_eth = float(np.median(eth_sources))
        ratio_sources = eth_sources / lcu_sources
        disagreement = float(np.ptp(np.log(ratio_sources)))
        oracle_ratio = oracle_eth / oracle_lcu

        if observation.ratio_log_return is not None:
            ratio_return = observation.ratio_log_return
        elif state.previous_oracle_ratio is None:
            ratio_return = 0.0
        else:
            ratio_return = math.log(oracle_ratio / state.previous_oracle_ratio)

        ewma_variance = _float(
            update_ewma_variance(state.ewma_variance, ratio_return)
        )
        volatility = math.sqrt(ewma_variance)
        utilization = observation.debt_value_usd / state.debt_ceiling
        risk_score = _float(
            compute_risk_score(
                volatility,
                observation.dex_basis,
                disagreement,
                utilization,
            )
        )
        targets = compute_targets(risk_score, utilization, self.config)
        recommended = rate_limited_update(
            state.annual_rate,
            state.debt_ceiling,
            state.liquidation_ratio,
            targets,
        )
        triggered = bool(
            _float(
                breaker_trigger(
                    observation.dex_basis,
                    disagreement,
                    volatility,
                    observation.oracle_age_hours,
                    self.config,
                )
            )
        )
        cooldown = (
            self.breaker_cooldown_steps
            if triggered
            else max(state.breaker_cooldown - 1, 0)
        )

        decision = ShadowDecision(
            observed_at=observation.timestamp,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            formula_version=FORMULA_VERSION,
            config_sha256=self.config_sha256,
            oracle_lcu_usd=oracle_lcu,
            oracle_eth_usd=oracle_eth,
            oracle_ratio=oracle_ratio,
            ratio_log_return=ratio_return,
            source_disagreement=disagreement,
            observed_volatility=volatility,
            dex_basis=observation.dex_basis,
            debt_value_usd=observation.debt_value_usd,
            utilization=utilization,
            risk_score=risk_score,
            volatility_component=4.0 * volatility,
            basis_component=3.2 * observation.dex_basis,
            disagreement_component=1.8 * disagreement,
            utilization_component=0.9 * max(utilization - 0.72, 0.0),
            baseline_annual_rate=state.annual_rate,
            baseline_debt_ceiling=state.debt_ceiling,
            baseline_liquidation_ratio=state.liquidation_ratio,
            target_annual_rate=_float(targets[0]),
            target_debt_ceiling=_float(targets[1]),
            target_liquidation_ratio=_float(targets[2]),
            recommended_annual_rate=_float(recommended[0]),
            recommended_debt_ceiling=_float(recommended[1]),
            recommended_liquidation_ratio=_float(recommended[2]),
            breaker_triggered=triggered,
            pause_new_draws=cooldown > 0,
            breaker_cooldown=cooldown,
        )
        next_state = ShadowState(
            annual_rate=decision.recommended_annual_rate,
            debt_ceiling=decision.recommended_debt_ceiling,
            liquidation_ratio=decision.recommended_liquidation_ratio,
            ewma_variance=ewma_variance,
            breaker_cooldown=cooldown,
            previous_oracle_ratio=oracle_ratio,
        )
        return decision, next_state


class CSVObservationSource:
    """Deterministic historical-replay source."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __iter__(self) -> Iterator[MarketObservation]:
        with self.path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                yield MarketObservation.from_mapping(row)


def _path_get(payload: Mapping[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"JSON field path not found: {dotted_path}")
        value = value[part]
    return value


class HTTPJSONObservationSource:
    """Fetch observations via HTTP GET; POST and mutation verbs are absent."""

    def __init__(
        self,
        url: str,
        field_map: Mapping[str, str] | None = None,
        timeout_seconds: float = 10.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("HTTP source URL must start with http:// or https://")
        self.url = url
        self.field_map = dict(field_map or {})
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})

    def fetch(self) -> MarketObservation:
        request = Request(self.url, headers=self.headers, method="GET")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        mapped = {
            name: _path_get(payload, self.field_map.get(name, name))
            for name in REQUIRED_OBSERVATION_FIELDS
        }
        if "ratio_log_return" in self.field_map or "ratio_log_return" in payload:
            mapped["ratio_log_return"] = _path_get(
                payload, self.field_map.get("ratio_log_return", "ratio_log_return")
            )
        return MarketObservation.from_mapping(mapped)


class ReadOnlyJSONRPCClient:
    """Minimal JSON-RPC client with an explicit read-only method allow-list."""

    ALLOWED_METHODS = frozenset(
        {"eth_blockNumber", "eth_call", "eth_chainId", "eth_getBlockByNumber"}
    )

    def __init__(self, url: str, timeout_seconds: float = 10.0) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("RPC URL must start with http:// or https://")
        self.url = url
        self.timeout_seconds = timeout_seconds

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        if method not in self.ALLOWED_METHODS:
            raise PermissionError(f"JSON-RPC method is not read-only/allowed: {method}")
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        ).encode("utf-8")
        request = Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        if "error" in payload:
            raise RuntimeError(f"read-only JSON-RPC error: {payload['error']}")
        return payload["result"]


class JSONLDecisionLog:
    """Append-only, machine-readable decision log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, decision: ShadowDecision) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision.to_dict(), sort_keys=True) + "\n")


def replay(
    observations: Iterable[MarketObservation],
    engine: ShadowRiskEngine,
    initial_state: ShadowState | None = None,
    log: JSONLDecisionLog | None = None,
) -> tuple[list[ShadowDecision], ShadowState]:
    """Evaluate a finite sequence deterministically apart from audit timestamps."""

    state = initial_state or ShadowState()
    decisions: list[ShadowDecision] = []
    for observation in observations:
        decision, state = engine.step(observation, state)
        decisions.append(decision)
        if log is not None:
            log.append(decision)
    return decisions, state


def poll_live(
    source: HTTPJSONObservationSource,
    engine: ShadowRiskEngine,
    state: ShadowState,
    log: JSONLDecisionLog,
    interval_seconds: float,
    max_iterations: int = 0,
) -> ShadowState:
    """Poll a GET endpoint; ``max_iterations=0`` means run until interrupted."""

    if interval_seconds <= 0 or max_iterations < 0:
        raise ValueError("invalid live polling limits")
    count = 0
    while max_iterations == 0 or count < max_iterations:
        observation = source.fetch()
        decision, state = engine.step(observation, state)
        log.append(decision)
        count += 1
        if max_iterations == 0 or count < max_iterations:
            time.sleep(interval_seconds)
    return state
