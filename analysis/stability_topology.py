"""Parameter-space stability and topology experiment.

The experiment separates a reduced-order closed-loop convergence probe from the
full economic simulation.  This avoids calling a configuration "convergent"
merely because it produces low bad debt over one finite market path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, minimum_spanning_tree
from scipy.spatial.distance import pdist, squareform
from scipy.stats import spearmanr
from ripser import ripser

from risk_engine import (
    RiskEngineConfig,
    breaker_trigger,
    compute_risk_score,
    compute_targets,
    rate_limited_update,
    update_ewma_variance,
)


EXPERIMENT_SEED = 20261105


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    symbol: str
    baseline: float
    lower: float
    upper: float
    interpretation: str


PARAMETER_SPECS = (
    ParameterSpec("ewma_memory", r"$\beta$", 0.92, 0.80, 0.98, "EWMA memory"),
    ParameterSpec(
        "volatility_weight", r"$w_\sigma$", 4.0, 2.5, 5.5, "volatility weight"
    ),
    ParameterSpec("basis_weight", r"$w_b$", 3.2, 2.0, 4.5, "DEX-basis weight"),
    ParameterSpec(
        "disagreement_weight",
        r"$w_\delta$",
        1.8,
        1.0,
        2.8,
        "oracle-disagreement weight",
    ),
    ParameterSpec(
        "utilization_weight",
        r"$w_u$",
        0.9,
        0.4,
        1.4,
        "excess-utilisation weight",
    ),
    ParameterSpec(
        "rate_risk_gain", r"$g_r$", 0.90, 0.50, 1.30, "rate response gain"
    ),
    ParameterSpec(
        "ceiling_risk_gain",
        r"$g_C$",
        1.75,
        0.80,
        2.80,
        "debt-ceiling response gain",
    ),
    ParameterSpec(
        "liquidation_risk_gain",
        r"$g_\lambda$",
        0.70,
        0.35,
        1.10,
        "liquidation-ratio response gain",
    ),
)


@dataclass(frozen=True)
class StressRegime:
    name: str
    ratio_log_return: float
    disagreement: float
    background_flow: float
    arbitrage_capacity: float
    demand_multiplier: float


STRESS_REGIMES = (
    StressRegime("calm", 0.006, 0.015, 0.0005, 0.0012, 1.00),
    StressRegime("moderate", 0.035, 0.080, 0.0012, 0.0008, 1.30),
    StressRegime("crisis", 0.075, 0.160, 0.0025, 0.0003, 1.80),
)


def latin_hypercube(
    n_points: int,
    specs: Iterable[ParameterSpec] = PARAMETER_SPECS,
    seed: int = EXPERIMENT_SEED,
    bounds: dict[str, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """Deterministic Latin-hypercube sample with one point in every stratum."""

    if n_points < 1:
        raise ValueError("n_points must be positive")
    selected = tuple(specs)
    rng = np.random.default_rng(seed)
    unit = np.empty((n_points, len(selected)), dtype=float)
    for column in range(len(selected)):
        strata = (np.arange(n_points) + rng.random(n_points)) / n_points
        unit[:, column] = strata[rng.permutation(n_points)]
    values: dict[str, np.ndarray] = {}
    for column, spec in enumerate(selected):
        low, high = (bounds or {}).get(spec.name, (spec.lower, spec.upper))
        if not low < high:
            raise ValueError(f"invalid sampling bounds for {spec.name}")
        values[spec.name] = low + unit[:, column] * (high - low)
    return pd.DataFrame(values)


def baseline_parameters() -> dict[str, float]:
    return {spec.name: spec.baseline for spec in PARAMETER_SPECS}


def broad_bounds() -> dict[str, tuple[float, float]]:
    return {spec.name: (spec.lower, spec.upper) for spec in PARAMETER_SPECS}


def local_bounds(
    centre: dict[str, float], half_width_fraction: float = 0.18
) -> dict[str, tuple[float, float]]:
    """Axis-aligned neighbourhood around a stable centre, clipped to broad bounds."""

    if not 0 < half_width_fraction < 0.5:
        raise ValueError("half_width_fraction must lie in (0, 0.5)")
    bounds: dict[str, tuple[float, float]] = {}
    for spec in PARAMETER_SPECS:
        half_width = half_width_fraction * (spec.upper - spec.lower)
        low = max(spec.lower, centre[spec.name] - half_width)
        high = min(spec.upper, centre[spec.name] + half_width)
        bounds[spec.name] = (low, high)
    return bounds


def config_from_parameters(parameters: dict[str, float] | pd.Series) -> RiskEngineConfig:
    updates = {spec.name: float(parameters[spec.name]) for spec in PARAMETER_SPECS}
    return replace(RiskEngineConfig(), **updates)


def _initial_ensemble(regime: StressRegime, n_perturbations: int = 9) -> np.ndarray:
    phase = np.linspace(0.0, 2.0 * np.pi, n_perturbations, endpoint=False)
    return np.column_stack(
        [
            0.08 + 0.035 * np.sin(phase),
            0.82 + 0.14 * np.cos(phase),
            1.68 + 0.13 * np.sin(phase + 0.7),
            0.62 + 0.12 * np.cos(phase + 1.1),
            np.clip(0.02 + 0.012 * np.sin(phase + 1.7), 0.0, 0.45),
            np.full(n_perturbations, max(regime.ratio_log_return**2, 1e-5)),
        ]
    )


def _normalise_state(state: np.ndarray) -> np.ndarray:
    scale = np.array([1.46, 0.80, 0.70, 1.20, 0.45, 0.0225])
    offset = np.array([0.04, 0.20, 1.50, 0.00, 0.00, 0.00])
    return (state - offset) / scale


def simulate_reduced_closed_loop(
    config: RiskEngineConfig,
    regime: StressRegime,
    delay_steps: int,
    n_steps: int = 320,
    tail_steps: int = 60,
) -> dict[str, float | bool | str | int]:
    """Probe convergence under constant stress from nine perturbed initial states.

    State columns are rate, ceiling, liquidation ratio, debt, DEX basis, and
    EWMA variance.  The reduced demand/debt/basis loop preserves the signs and
    bounds of the full simulator while making local-attractor tests inexpensive.
    """

    if delay_steps < 0 or tail_steps >= n_steps:
        raise ValueError("invalid reduced-loop horizon")
    initial = _initial_ensemble(regime)
    rate, ceiling, liquidation, debt, basis, variance = initial.T.copy()
    cooldown = np.zeros(len(rate), dtype=int)
    rate_queue = [rate.copy() for _ in range(delay_steps + 1)]
    ceiling_queue = [ceiling.copy() for _ in range(delay_steps + 1)]
    liquidation_queue = [liquidation.copy() for _ in range(delay_steps + 1)]
    history = np.empty((n_steps, len(rate), 6), dtype=float)
    step_years = 6.0 / (24.0 * 365.0)

    for step in range(n_steps):
        variance = update_ewma_variance(
            variance, regime.ratio_log_return, config.ewma_memory
        )
        volatility = np.sqrt(variance)
        utilization = debt / np.maximum(ceiling, 1e-12)
        risk = compute_risk_score(
            volatility, basis, regime.disagreement, utilization, config
        )
        targets = compute_targets(risk, utilization, config)
        proposed = rate_limited_update(
            rate, ceiling, liquidation, targets, config
        )
        rate_queue.append(proposed[0])
        ceiling_queue.append(proposed[1])
        liquidation_queue.append(proposed[2])
        rate = rate_queue.pop(0)
        ceiling = ceiling_queue.pop(0)
        liquidation = liquidation_queue.pop(0)

        triggered = breaker_trigger(
            basis, regime.disagreement, volatility, 6.0, config
        )
        cooldown = np.where(triggered, 4, np.maximum(cooldown - 1, 0))
        paused = cooldown > 0

        demand = 0.0018 * regime.demand_multiplier * np.exp(
            -2.4 * np.maximum(rate - config.initial_rate, 0.0)
        )
        demand *= np.maximum(1.0 - debt / np.maximum(ceiling, 1e-12), 0.0)
        demand = np.where(paused, 0.0, demand)
        accepted = np.minimum(demand, np.maximum(ceiling - debt, 0.0))
        repayment = 0.0030 * debt
        debt = np.clip(
            debt * np.exp(rate * step_years) + accepted - repayment,
            0.0,
            1.20,
        )

        net_pressure = np.maximum(
            regime.background_flow + 0.20 * accepted - regime.arbitrage_capacity,
            0.0,
        )
        basis = np.clip(0.94 * basis + 1.7 * net_pressure / 0.18, 0.0, 0.45)
        history[step] = np.column_stack(
            [rate, ceiling, liquidation, debt, basis, variance]
        )

    normal = _normalise_state(history)
    tail = normal[-tail_steps:]
    tail_step = float(np.mean(np.linalg.norm(np.diff(tail, axis=0), axis=2)))
    tail_range = float(np.mean(np.ptp(tail, axis=0)))
    final_spread = float(np.mean(np.std(tail[-1], axis=0)))
    initial_spread = float(np.mean(np.std(_normalise_state(initial), axis=0)))
    contraction = final_spread / max(initial_spread, 1e-12)
    bounded = bool(
        np.isfinite(history).all()
        and (history[:, :, 0] >= 0.04 - 1e-12).all()
        and (history[:, :, 0] <= config.max_rate + 1e-12).all()
        and (history[:, :, 1] >= config.min_ceiling - 1e-12).all()
        and (history[:, :, 1] <= config.initial_debt_ceiling + 1e-12).all()
        and (history[:, :, 2] >= config.initial_liquidation_ratio - 1e-12).all()
        and (history[:, :, 2] <= config.max_liquidation_ratio + 1e-12).all()
    )
    converged = bool(
        bounded
        and tail_step < 0.0020
        and tail_range < 0.030
        and final_spread < 0.040
        and contraction < 0.50
    )
    return {
        "regime": regime.name,
        "delay_steps": delay_steps,
        "tail_step_norm": tail_step,
        "tail_range": tail_range,
        "final_spread": final_spread,
        "contraction_ratio": contraction,
        "bounded": bounded,
        "converged": converged,
    }


def evaluate_configuration(parameters: dict[str, float] | pd.Series) -> dict[str, float | bool]:
    config = config_from_parameters(parameters)
    cases = [
        simulate_reduced_closed_loop(config, regime, delay)
        for regime in STRESS_REGIMES
        for delay in (0, 8)
    ]
    converged_share = float(np.mean([case["converged"] for case in cases]))
    bounded_share = float(np.mean([case["bounded"] for case in cases]))
    mean_tail_step = float(np.mean([case["tail_step_norm"] for case in cases]))
    worst_tail_range = float(max(case["tail_range"] for case in cases))
    worst_final_spread = float(max(case["final_spread"] for case in cases))
    worst_contraction = float(max(case["contraction_ratio"] for case in cases))
    stability_score = (
        3.0 * mean_tail_step
        + 0.40 * worst_tail_range
        + 0.40 * worst_final_spread
        + 0.10 * max(worst_contraction - 0.25, 0.0)
        + 0.25 * (1.0 - converged_share)
        + 0.50 * (1.0 - bounded_share)
    )
    robust = bool(
        bounded_share == 1.0
        and converged_share >= 5.0 / 6.0
        and worst_final_spread < 0.055
    )
    return {
        "converged_case_share": converged_share,
        "bounded_case_share": bounded_share,
        "mean_tail_step_norm": mean_tail_step,
        "worst_tail_range": worst_tail_range,
        "worst_final_spread": worst_final_spread,
        "worst_contraction_ratio": worst_contraction,
        "stability_score": stability_score,
        "robust_converged": robust,
    }


def evaluate_parameter_frame(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in frame.iterrows():
        records.append({**row.to_dict(), **evaluate_configuration(row)})
    return pd.DataFrame(records)


def select_stable_centre(pilot: pd.DataFrame) -> dict[str, float]:
    candidates = pilot[pilot["robust_converged"]].copy()
    if candidates.empty:
        candidates = pilot.nsmallest(max(5, len(pilot) // 10), "stability_score").copy()
    normal_distance = np.zeros(len(candidates))
    for spec in PARAMETER_SPECS:
        normal_distance += np.square(
            (candidates[spec.name].to_numpy() - spec.baseline)
            / (spec.upper - spec.lower)
        )
    candidates["centre_objective"] = (
        candidates["stability_score"].to_numpy() + 0.03 * np.sqrt(normal_distance)
    )
    selected = candidates.nsmallest(1, "centre_objective").iloc[0]
    return {spec.name: float(selected[spec.name]) for spec in PARAMETER_SPECS}


def _gf2_rank(columns: Iterable[int]) -> int:
    basis: dict[int, int] = {}
    for value in columns:
        column = value
        while column:
            pivot = column.bit_length() - 1
            if pivot in basis:
                column ^= basis[pivot]
            else:
                basis[pivot] = column
                break
    return len(basis)


def vietoris_rips_betti_01(distance: np.ndarray, epsilon: float) -> tuple[int, int, int, int]:
    """Betti-0 and Betti-1 of the Vietoris-Rips 2-skeleton at one scale."""

    n_points = len(distance)
    adjacency = (distance <= epsilon) & ~np.eye(n_points, dtype=bool)
    graph = csr_matrix(adjacency.astype(np.int8))
    beta0 = int(connected_components(graph, directed=False, return_labels=False))
    edges = [(i, j) for i in range(n_points) for j in range(i + 1, n_points) if adjacency[i, j]]
    edge_index = {edge: index for index, edge in enumerate(edges)}
    boundary_columns: list[int] = []
    triangle_count = 0
    for i, j in edges:
        common = np.flatnonzero(adjacency[i] & adjacency[j])
        for k in common:
            if k <= j:
                continue
            triangle_count += 1
            column = (
                (1 << edge_index[(i, j)])
                | (1 << edge_index[(i, int(k))])
                | (1 << edge_index[(j, int(k))])
            )
            boundary_columns.append(column)
    rank_boundary_2 = _gf2_rank(boundary_columns)
    beta1 = max(len(edges) - n_points + beta0 - rank_boundary_2, 0)
    return beta0, beta1, len(edges), triangle_count


def topology_analysis(
    frame: pd.DataFrame,
    bounds: dict[str, tuple[float, float]],
    n_scales: int = 24,
    null_replicates: int = 30,
) -> tuple[
    pd.DataFrame,
    dict[str, float | int | bool | str],
    np.ndarray,
    pd.DataFrame,
]:
    """Analyse the topology of the robustly convergent point cloud."""

    mask = frame["robust_converged"].to_numpy(dtype=bool)
    stable = frame.loc[mask, [spec.name for spec in PARAMETER_SPECS]].to_numpy()
    if len(stable) < 3:
        return (
            pd.DataFrame(columns=["epsilon", "beta0", "beta1", "edges", "triangles"]),
            {
                "stable_points": int(len(stable)),
                "topology_sufficient": False,
                "interpretation": "Too few robustly convergent points for topology.",
            },
            np.empty((len(stable), 2)),
            pd.DataFrame(columns=["dimension", "birth", "death", "persistence"]),
        )
    lower = np.array([bounds[spec.name][0] for spec in PARAMETER_SPECS])
    upper = np.array([bounds[spec.name][1] for spec in PARAMETER_SPECS])
    normal = (stable - lower) / np.maximum(upper - lower, 1e-12)
    distance = squareform(pdist(normal))
    diagrams = ripser(normal, maxdim=1)["dgms"]
    interval_rows: list[dict[str, float | int]] = []
    for dimension, diagram in enumerate(diagrams):
        for birth, death in diagram:
            interval_rows.append(
                {
                    "dimension": dimension,
                    "birth": float(birth),
                    "death": float(death),
                    "persistence": float(death - birth) if np.isfinite(death) else np.inf,
                }
            )
    intervals = pd.DataFrame(interval_rows)
    h0_finite = diagrams[0][np.isfinite(diagrams[0][:, 1])]
    h1_finite = diagrams[1][np.isfinite(diagrams[1][:, 1])]
    connection_radius = float(h0_finite[:, 1].max()) if len(h0_finite) else 0.0
    max_h1_persistence = (
        float(np.max(h1_finite[:, 1] - h1_finite[:, 0])) if len(h1_finite) else 0.0
    )
    max_death = max(
        connection_radius,
        float(h1_finite[:, 1].max()) if len(h1_finite) else 0.0,
    )
    scales = np.linspace(0.0, max(max_death * 1.05, 1e-6), n_scales)
    rows = []
    for epsilon in scales:
        beta0 = int(
            np.sum(
                (diagrams[0][:, 0] <= epsilon)
                & ((diagrams[0][:, 1] > epsilon) | ~np.isfinite(diagrams[0][:, 1]))
            )
        )
        beta1 = int(
            np.sum(
                (diagrams[1][:, 0] <= epsilon)
                & ((diagrams[1][:, 1] > epsilon) | ~np.isfinite(diagrams[1][:, 1]))
            )
        )
        rows.append({"epsilon": epsilon, "beta0": beta0, "beta1": beta1})
    topology = pd.DataFrame(rows)

    rng = np.random.default_rng(EXPERIMENT_SEED + 900)
    null_maxima = []
    for _ in range(null_replicates):
        null_cloud = np.empty_like(normal)
        for column in range(normal.shape[1]):
            strata = (np.arange(len(normal)) + rng.random(len(normal))) / len(normal)
            null_cloud[:, column] = strata[rng.permutation(len(normal))]
        null_h1 = ripser(null_cloud, maxdim=1)["dgms"][1]
        null_h1 = null_h1[np.isfinite(null_h1[:, 1])]
        null_maxima.append(
            float(np.max(null_h1[:, 1] - null_h1[:, 0])) if len(null_h1) else 0.0
        )
    null_maxima_array = np.asarray(null_maxima)
    null_p_value = float(
        (1 + np.sum(null_maxima_array >= max_h1_persistence))
        / (1 + len(null_maxima_array))
    )
    cloud_diameter = float(distance.max())
    nontrivial_h1 = bool(
        null_p_value < 0.05
        and max_h1_persistence > 0.05 * max(cloud_diameter, 1e-12)
    )
    centred = normal - normal.mean(axis=0, keepdims=True)
    _, singular, vectors = np.linalg.svd(centred, full_matrices=False)
    projection = centred @ vectors[:2].T
    explained = np.square(singular) / max(np.square(singular).sum(), 1e-12)
    summary: dict[str, float | int | bool | str] = {
        "stable_points": int(len(stable)),
        "topology_sufficient": True,
        "connection_radius": connection_radius,
        "minimum_beta0": int(topology["beta0"].min()),
        "maximum_beta1": int(topology["beta1"].max()),
        "maximum_h1_persistence": max_h1_persistence,
        "null_max_h1_persistence_median": float(np.median(null_maxima_array)),
        "null_max_h1_persistence_p95": float(np.quantile(null_maxima_array, 0.95)),
        "h1_null_test_p_value": null_p_value,
        "nontrivial_h1_beyond_uniform_null": nontrivial_h1,
        "pca_two_component_variance_share": float(explained[:2].sum()),
        "interpretation": (
            "Connected at the analysed neighbourhood scale"
            if int(topology["beta0"].min()) == 1
            else "Multiple components persist across the analysed scales"
        ),
    }
    return topology, summary, projection, intervals


def parameter_influence(frame: pd.DataFrame) -> pd.DataFrame:
    outcomes = [
        "stability_score",
        "pooled_bad_debt_probability",
        "pooled_severe_depeg_probability",
        "pooled_mean_credit",
        "pooled_pause_share",
    ]
    records = []
    for spec in PARAMETER_SPECS:
        for outcome in outcomes:
            if outcome not in frame:
                continue
            if frame[spec.name].nunique() < 2 or frame[outcome].nunique() < 2:
                correlation, p_value = np.nan, np.nan
            else:
                correlation, p_value = spearmanr(frame[spec.name], frame[outcome])
            records.append(
                {
                    "parameter": spec.name,
                    "outcome": outcome,
                    "spearman_rho": float(correlation),
                    "p_value": float(p_value),
                }
            )
    return pd.DataFrame(records)


def config_record(config: RiskEngineConfig) -> dict[str, float]:
    """Serializable helper used by tests and report metadata."""

    return {key: float(value) for key, value in asdict(config).items()}
