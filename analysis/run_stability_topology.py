#!/usr/bin/env python3
"""Run the 360-point convergence, robustness, and topology experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from model import (
    MAIN_ARCHITECTURES,
    SimulationConfig,
    build_market_paths,
    moving_block_bootstrap_joint,
    simulate_protocol,
)
from stability_topology import (
    EXPERIMENT_SEED,
    PARAMETER_SPECS,
    baseline_parameters,
    broad_bounds,
    config_from_parameters,
    evaluate_configuration,
    evaluate_parameter_frame,
    latin_hypercube,
    local_bounds,
    parameter_influence,
    select_stable_centre,
    topology_analysis,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results" / "stability_topology"
FIGURES = ROOT / "figures" / "stability_topology"
CONFIG = SimulationConfig()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_panel() -> pd.DataFrame:
    path = DATA / "processed" / "joint_monthly_market_panel.csv"
    panel = pd.read_csv(path, parse_dates=["month"])
    expected = {"ars_depreciation", "try_depreciation", "eth_return"}
    if not expected.issubset(panel.columns):
        raise ValueError(f"market panel is missing {sorted(expected - set(panel.columns))}")
    return panel


def common_markets(panel: pd.DataFrame, n_paths: int) -> dict[str, object]:
    markets: dict[str, object] = {}
    for currency, offset in (("ARS", 0), ("TRY", 10)):
        fx = "ars_depreciation" if currency == "ARS" else "try_depreciation"
        joint = panel[[fx, "eth_return"]].dropna().to_numpy()
        macro = moving_block_bootstrap_joint(
            joint,
            n_paths=n_paths,
            horizon=CONFIG.horizon_months,
            block_length=2,
            seed=EXPERIMENT_SEED + offset,
        )
        markets[currency] = build_market_paths(
            macro,
            seed=EXPERIMENT_SEED + 100 + offset,
            config=CONFIG,
            attack_probability=0.22,
        )
    return markets


def economic_evaluation(
    points: pd.DataFrame, markets: dict[str, object]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    records: list[dict[str, object]] = []
    architecture = MAIN_ARCHITECTURES[-1]
    total = len(points)
    for index, row in points.iterrows():
        risk_config = config_from_parameters(row)
        for currency, market in markets.items():
            result, _ = simulate_protocol(
                market,
                architecture,
                currency,
                CONFIG,
                keep_paths=0,
                risk_config=risk_config,
            )
            records.append(
                {
                    "point_id": row["point_id"],
                    "currency": currency,
                    "bad_debt_probability": float(result["bad_debt_event"].mean()),
                    "mean_bad_debt_share": float(
                        result["bad_debt_share_initial_debt"].mean()
                    ),
                    "p95_bad_debt_share": float(
                        result["bad_debt_share_initial_debt"].quantile(0.95)
                    ),
                    "severe_depeg_probability": float(result["deep_depeg_event"].mean()),
                    "mean_credit": float(result["credit_issued"].mean()),
                    "pause_share": float(result["pause_share"].mean()),
                    "mean_parameter_turnover": float(result["parameter_turnover"].mean()),
                    "mean_rate": float(result["mean_annual_rate"].mean()),
                    "mean_ceiling": float(result["mean_debt_ceiling"].mean()),
                    "mean_liquidation_ratio": float(
                        result["mean_liquidation_ratio"].mean()
                    ),
                }
            )
        completed = index + 1
        if completed % 30 == 0 or completed == total:
            print(f"Economic simulations: {completed}/{total} parameter points")
    by_currency = pd.DataFrame(records)
    pooled = (
        by_currency.groupby("point_id", as_index=False)
        .agg(
            pooled_bad_debt_probability=("bad_debt_probability", "mean"),
            pooled_mean_bad_debt_share=("mean_bad_debt_share", "mean"),
            pooled_p95_bad_debt_share=("p95_bad_debt_share", "mean"),
            pooled_severe_depeg_probability=("severe_depeg_probability", "mean"),
            pooled_mean_credit=("mean_credit", "mean"),
            pooled_pause_share=("pause_share", "mean"),
            pooled_parameter_turnover=("mean_parameter_turnover", "mean"),
            pooled_mean_rate=("mean_rate", "mean"),
            pooled_mean_ceiling=("mean_ceiling", "mean"),
            pooled_mean_liquidation_ratio=("mean_liquidation_ratio", "mean"),
        )
    )
    return by_currency, pooled


def _normalised_matrix(
    frame: pd.DataFrame, bounds: dict[str, tuple[float, float]]
) -> np.ndarray:
    values = frame[[spec.name for spec in PARAMETER_SPECS]].to_numpy()
    lower = np.array([bounds[spec.name][0] for spec in PARAMETER_SPECS])
    upper = np.array([bounds[spec.name][1] for spec in PARAMETER_SPECS])
    return (values - lower) / np.maximum(upper - lower, 1e-12)


def make_figures(
    frame: pd.DataFrame,
    topology: pd.DataFrame,
    influence: pd.DataFrame,
    bounds: dict[str, tuple[float, float]],
) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
            "figure.dpi": 140,
            "savefig.dpi": 220,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    stable = frame["robust_converged"].to_numpy(dtype=bool)
    matrix = _normalised_matrix(frame, bounds)
    centred = matrix - matrix.mean(axis=0, keepdims=True)
    _, singular, vectors = np.linalg.svd(centred, full_matrices=False)
    pca = centred @ vectors[:2].T
    explained = np.square(singular) / np.square(singular).sum()

    fig, ax = plt.subplots(figsize=(7.2, 5.1))
    scatter = ax.scatter(
        pca[:, 0],
        pca[:, 1],
        c=frame["stability_score"],
        cmap="viridis_r",
        s=np.where(stable, 36, 25),
        marker="o",
        edgecolor=np.where(stable, "#0A6847", "#9B2226"),
        linewidth=0.65,
        alpha=0.88,
    )
    ax.set_xlabel(f"PC1 ({100 * explained[0]:.1f}% variance)")
    ax.set_ylabel(f"PC2 ({100 * explained[1]:.1f}% variance)")
    ax.set_title("Local parameter cloud: convergence stability landscape")
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    colorbar.set_label("Stability score (lower is better)")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure1_parameter_cloud_pca.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(7.2, 4.8))
    if not topology.empty:
        ax1.plot(topology["epsilon"], topology["beta0"], "o-", color="#005F73", label=r"$\beta_0$")
        ax1.set_xlabel(r"Neighbourhood radius $\varepsilon$")
        ax1.set_ylabel(r"Connected components $\beta_0$", color="#005F73")
        ax1.tick_params(axis="y", labelcolor="#005F73")
        ax2 = ax1.twinx()
        ax2.plot(topology["epsilon"], topology["beta1"], "s--", color="#BB3E03", label=r"$\beta_1$")
        ax2.set_ylabel(r"One-dimensional holes $\beta_1$", color="#BB3E03")
        ax2.tick_params(axis="y", labelcolor="#BB3E03")
    ax1.set_title("Vietoris-Rips topology of the robustly convergent set")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure2_betti_curves.png", bbox_inches="tight")
    plt.close(fig)

    selected = influence[
        influence["outcome"].isin(
            ["stability_score", "pooled_bad_debt_probability"]
        )
    ].copy()
    pivot = selected.pivot(index="parameter", columns="outcome", values="spearman_rho")
    pivot = pivot.reindex([spec.name for spec in PARAMETER_SPECS])
    fig, ax = plt.subplots(figsize=(8.0, 5.4))
    y = np.arange(len(pivot))
    width = 0.36
    ax.barh(y - width / 2, pivot["stability_score"], height=width, color="#2A9D8F", label="Stability score")
    ax.barh(y + width / 2, pivot["pooled_bad_debt_probability"], height=width, color="#E76F51", label="Bad-debt probability")
    ax.axvline(0, color="#444444", linewidth=0.8)
    ax.set_yticks(y, [spec.name.replace("_", " ") for spec in PARAMETER_SPECS])
    ax.set_xlabel("Spearman rank correlation")
    ax.set_title("Parameter influence in the 360-point neighbourhood")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "figure3_parameter_influence.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    scatter = ax.scatter(
        frame["pooled_mean_credit"],
        frame["pooled_bad_debt_probability"],
        c=frame["pooled_pause_share"],
        cmap="plasma",
        marker="o",
        s=np.where(stable, 36, 24),
        edgecolor=np.where(stable, "#0A6847", "#9B2226"),
        linewidth=0.6,
        alpha=0.85,
    )
    ax.set_xlabel("Mean credit issued")
    ax.set_ylabel("Bad-debt event probability")
    ax.set_title("Economic trade-off across the local parameter cloud")
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    colorbar.set_label("Pause share")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure4_economic_tradeoff.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 4.0))
    axes[0].hist(frame["converged_case_share"], bins=np.linspace(0, 1, 8), color="#457B9D", edgecolor="white")
    axes[0].set_xlabel("Share of six stability cases converged")
    axes[0].set_ylabel("Parameter points")
    axes[0].set_title("Convergence coverage")
    axes[1].hist(frame["stability_score"], bins=20, color="#6A4C93", edgecolor="white")
    axes[1].set_xlabel("Stability score")
    axes[1].set_ylabel("Parameter points")
    axes[1].set_title("Local robustness distribution")
    fig.tight_layout()
    fig.savefig(FIGURES / "figure5_stability_distributions.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=int, default=360)
    parser.add_argument("--pilot-points", type=int, default=96)
    parser.add_argument("--market-paths", type=int, default=192)
    args = parser.parse_args()
    if min(args.points, args.pilot_points, args.market_paths) < 1:
        raise ValueError("all experiment sizes must be positive")

    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    pilot = latin_hypercube(args.pilot_points, seed=EXPERIMENT_SEED)
    pilot.iloc[0] = pd.Series(baseline_parameters())
    pilot.insert(0, "pilot_id", [f"P{i + 1:03d}" for i in range(len(pilot))])
    pilot_evaluated = evaluate_parameter_frame(pilot)
    centre = select_stable_centre(pilot_evaluated)
    neighbourhood = local_bounds(centre)

    points = latin_hypercube(
        args.points,
        seed=EXPERIMENT_SEED + 1,
        bounds=neighbourhood,
    )
    points.insert(0, "point_id", [f"L{i + 1:03d}" for i in range(len(points))])
    evaluated = evaluate_parameter_frame(points)

    panel = load_panel()
    markets = common_markets(panel, args.market_paths)
    by_currency, pooled = economic_evaluation(evaluated, markets)
    combined = evaluated.merge(pooled, on="point_id", validate="one_to_one")
    topology, topology_summary, _, persistence = topology_analysis(
        combined, neighbourhood
    )
    influence = parameter_influence(combined)
    make_figures(combined, topology, influence, neighbourhood)

    pilot_path = RESULTS / "pilot_parameter_search.csv"
    points_path = RESULTS / "local_360_parameter_results.csv"
    currency_path = RESULTS / "economic_results_by_currency.csv"
    topology_path = RESULTS / "topology_betti_curves.csv"
    influence_path = RESULTS / "parameter_influence.csv"
    persistence_path = RESULTS / "topology_persistence_intervals.csv"
    pilot_evaluated.to_csv(pilot_path, index=False, float_format="%.10g")
    combined.to_csv(points_path, index=False, float_format="%.10g")
    by_currency.to_csv(currency_path, index=False, float_format="%.10g")
    topology.to_csv(topology_path, index=False, float_format="%.10g")
    influence.to_csv(influence_path, index=False, float_format="%.10g")
    persistence.to_csv(persistence_path, index=False, float_format="%.10g")

    stable_count = int(combined["robust_converged"].sum())
    baseline_probe = evaluate_configuration(baseline_parameters())
    summary = {
        "experiment_seed": EXPERIMENT_SEED,
        "pilot_points": args.pilot_points,
        "local_points": args.points,
        "market_paths_per_currency": args.market_paths,
        "currencies": ["ARS", "TRY"],
        "common_market_paths": True,
        "stable_centre": centre,
        "local_bounds": {key: list(value) for key, value in neighbourhood.items()},
        "baseline_probe": baseline_probe,
        "robust_converged_points": stable_count,
        "robust_converged_share": stable_count / len(combined),
        "median_stability_score": float(combined["stability_score"].median()),
        "median_pooled_bad_debt_probability": float(
            combined["pooled_bad_debt_probability"].median()
        ),
        "median_pooled_credit": float(combined["pooled_mean_credit"].median()),
        "topology": topology_summary,
        "files": {},
    }
    summary_path = RESULTS / "experiment_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    output_files = [
        pilot_path,
        points_path,
        currency_path,
        topology_path,
        influence_path,
        persistence_path,
        *sorted(FIGURES.glob("*.png")),
    ]
    summary["files"] = {
        str(path.relative_to(ROOT)): sha256(path) for path in output_files
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"Completed {args.points} local points; {stable_count} robustly converged "
        f"({100 * stable_count / len(combined):.1f}%)."
    )
    print(f"Results: {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
