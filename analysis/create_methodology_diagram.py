#!/usr/bin/env python3
"""Create the publication-ready methodology pipeline figure."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "figures" / "stability_topology"


COLORS = {
    "ink": "#132238",
    "muted": "#5E6B7A",
    "line": "#AAB7C4",
    "paper": "#F7FAFC",
    "white": "#FFFFFF",
    "navy": "#153B5B",
    "teal": "#0B8F87",
    "teal_light": "#E6F6F3",
    "blue": "#3478B8",
    "blue_light": "#EAF3FB",
    "purple": "#7157A5",
    "purple_light": "#F1ECFA",
    "orange": "#D66A2C",
    "orange_light": "#FFF0E7",
    "green": "#318260",
    "green_light": "#EAF6F0",
    "gold": "#D8A126",
    "gold_light": "#FFF8E5",
}


def rounded_card(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    face: str,
    edge: str,
    radius: float = 0.018,
    shadow: bool = True,
    linewidth: float = 1.2,
) -> FancyBboxPatch:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=face,
        edgecolor=edge,
        linewidth=linewidth,
        zorder=3,
    )
    if shadow:
        patch.set_path_effects(
            [pe.SimplePatchShadow(offset=(2.2, -2.2), alpha=0.12), pe.Normal()]
        )
    ax.add_patch(patch)
    return patch


def arrow(
    ax: plt.Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: str | None = None,
    width: float = 1.8,
    connectionstyle: str = "arc3,rad=0",
    zorder: int = 2,
) -> None:
    patch = FancyArrowPatch(
        start,
        end,
        transform=ax.transAxes,
        arrowstyle="-|>",
        mutation_scale=14,
        linewidth=width,
        color=color or COLORS["line"],
        connectionstyle=connectionstyle,
        shrinkA=2,
        shrinkB=2,
        zorder=zorder,
    )
    ax.add_patch(patch)


def stage_label(ax: plt.Axes, number: str, label: str, x: float, y: float) -> None:
    ax.text(
        x,
        y,
        number,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color=COLORS["white"],
        bbox={
            "boxstyle": "circle,pad=0.38",
            "facecolor": COLORS["navy"],
            "edgecolor": "none",
        },
        zorder=8,
    )
    ax.text(
        x + 0.018,
        y,
        label.upper(),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=10.5,
        fontweight="bold",
        color=COLORS["navy"],
        zorder=8,
    )


def input_card(
    ax: plt.Axes,
    x: float,
    title: str,
    symbol: str,
    lines: tuple[str, ...],
    accent: str,
    light: str,
) -> None:
    rounded_card(ax, x, 0.770, 0.292, 0.105, face=COLORS["white"], edge="#D9E2EA")
    ax.add_patch(
        FancyBboxPatch(
            (x + 0.012, 0.789),
            0.042,
            0.062,
            boxstyle="round,pad=0.006,rounding_size=0.012",
            transform=ax.transAxes,
            facecolor=light,
            edgecolor="none",
            zorder=5,
        )
    )
    ax.text(
        x + 0.033,
        0.820,
        symbol,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=accent,
        zorder=6,
    )
    ax.text(
        x + 0.065,
        0.843,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=11.3,
        fontweight="bold",
        color=COLORS["ink"],
        zorder=6,
    )
    ax.text(
        x + 0.065,
        0.807,
        "\n".join(lines),
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.7,
        color=COLORS["muted"],
        linespacing=1.3,
        zorder=6,
    )


def sampling_node(
    ax: plt.Axes,
    x: float,
    width: float,
    title: str,
    subtitle: str,
    number: str,
) -> None:
    rounded_card(
        ax,
        x,
        0.683,
        width,
        0.066,
        face=COLORS["teal_light"],
        edge="#A9DCD5",
        radius=0.014,
        shadow=False,
    )
    ax.text(
        x + 0.024,
        0.716,
        number,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=12,
        fontweight="bold",
        color=COLORS["teal"],
        zorder=6,
    )
    ax.text(
        x + 0.047,
        0.726,
        title,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=9.8,
        fontweight="bold",
        color=COLORS["ink"],
        zorder=6,
    )
    ax.text(
        x + 0.047,
        0.704,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=8.3,
        color=COLORS["muted"],
        zorder=6,
    )


def metric_pill(
    ax: plt.Axes,
    x: float,
    y: float,
    text: str,
    face: str,
    color: str,
) -> None:
    ax.text(
        x,
        y,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.2,
        fontweight="bold",
        color=color,
        bbox={
            "boxstyle": "round,pad=0.35,rounding_size=0.7",
            "facecolor": face,
            "edgecolor": "none",
        },
        zorder=7,
    )


def build_figure() -> plt.Figure:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "mathtext.fontset": "dejavusans",
            "svg.fonttype": "none",
        }
    )
    fig, ax = plt.subplots(figsize=(16, 10), facecolor=COLORS["paper"])
    ax.set_facecolor(COLORS["paper"])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Title block.
    ax.text(
        0.04,
        0.963,
        "Methodological pipeline: from parameter sampling to stability evidence",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=20,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        0.04,
        0.927,
        "A deterministic 96 + 360 point design combining closed-loop convergence, economic simulation and persistent homology",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10.5,
        color=COLORS["muted"],
    )

    # Stage 1: inputs and sampling.
    stage_label(ax, "1", "Inputs and meaningful randomisation", 0.045, 0.895)
    input_card(
        ax,
        0.04,
        "Controller parameter space",
        r"$\theta$",
        (r"$\beta,\,w_\sigma,\,w_b,\,w_\delta,\,w_u$", r"$g_r,\,g_C,\,g_\lambda$  with broad bounds"),
        COLORS["purple"],
        COLORS["purple_light"],
    )
    input_card(
        ax,
        0.354,
        "Empirical market panel",
        "FX",
        ("ARS / TRY depreciation + ETH returns", "moving-block bootstrap preserves dependence"),
        COLORS["orange"],
        COLORS["orange_light"],
    )
    input_card(
        ax,
        0.668,
        "Experimental controls",
        "6h",
        ("seed 20261105 + common random numbers", "six-hour clock; identical shocks per point"),
        COLORS["blue"],
        COLORS["blue_light"],
    )

    sampling_node(ax, 0.058, 0.250, "Broad Latin hypercube", "global coverage of the 8D box", "96")
    sampling_node(ax, 0.375, 0.250, "Robust centre selection", r"minimise stability score near baseline", r"$\hat{\theta}$")
    sampling_node(ax, 0.692, 0.250, "Local Latin hypercube", r"$\pm18\%$ of each broad-range width", "360")
    arrow(ax, (0.316, 0.716), (0.367, 0.716), color=COLORS["teal"], width=2.1)
    arrow(ax, (0.633, 0.716), (0.684, 0.716), color=COLORS["teal"], width=2.1)

    # Stage 2: controller calculation.
    stage_label(ax, "2", "Parameterised adaptive controller", 0.045, 0.646)
    rounded_card(ax, 0.04, 0.454, 0.92, 0.165, face=COLORS["white"], edge="#C7D7E5")
    ax.text(
        0.066,
        0.584,
        "Observed state",
        transform=ax.transAxes,
        fontsize=9.5,
        fontweight="bold",
        color=COLORS["blue"],
        ha="left",
        va="center",
    )
    ax.text(
        0.066,
        0.552,
        r"$q_t$ return  •  $b_t$ DEX basis  •  $\delta_t$ disagreement  •  $u_t$ utilisation",
        transform=ax.transAxes,
        fontsize=9.3,
        color=COLORS["ink"],
        ha="left",
        va="center",
    )

    formula_positions = (0.075, 0.315, 0.555, 0.775)
    formula_widths = (0.205, 0.205, 0.185, 0.155)
    formula_titles = ("EWMA risk memory", "Composite risk score", "Control targets", "Bounded actuation")
    formulas = (
        r"$v_{t+1}=\beta v_t+(1-\beta)q_t^2$",
        r"$R_t=\mathrm{clip}_{[0,1]}\!\left(w_\sigma\sqrt{v}+w_bb+w_\delta\delta+w_u(u-.72)_+\right)$",
        r"$(r_t^*,C_t^*,\lambda_t^*)=f(R_t,u_t;\theta)$",
        r"$x_{t+1}=\mathrm{rate\!\!\_limit}(x_t,x_t^*)$",
    )
    for x, width, title, formula in zip(
        formula_positions, formula_widths, formula_titles, formulas, strict=True
    ):
        rounded_card(
            ax,
            x,
            0.485,
            width,
            0.053,
            face=COLORS["blue_light"],
            edge="#C6DDF0",
            radius=0.010,
            shadow=False,
            linewidth=0.8,
        )
        ax.text(
            x + width / 2,
            0.525,
            title,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=8.1,
            fontweight="bold",
            color=COLORS["blue"],
            zorder=7,
        )
        ax.text(
            x + width / 2,
            0.502,
            formula,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=8.2 if title != "Composite risk score" else 7.5,
            color=COLORS["ink"],
            zorder=7,
        )
    for start, end in ((0.282, 0.310), (0.522, 0.550), (0.742, 0.770)):
        arrow(ax, (start, 0.512), (end, 0.512), color=COLORS["blue"], width=1.6)
    metric_pill(ax, 0.760, 0.565, "breaker → pause draws", COLORS["gold_light"], "#8B6416")
    metric_pill(ax, 0.900, 0.565, "repayments stay open", COLORS["green_light"], COLORS["green"])
    ax.text(
        0.5,
        0.466,
        "Feedback: the updated rate, ceiling, liquidation ratio and breaker state shape debt demand, utilisation and the next observation.",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.4,
        color=COLORS["muted"],
        zorder=7,
    )

    # Split into the stability and economic branches.
    arrow(ax, (0.50, 0.451), (0.50, 0.428), color=COLORS["navy"], width=2.1)
    arrow(ax, (0.50, 0.428), (0.265, 0.405), color=COLORS["purple"], width=2.0)
    arrow(ax, (0.50, 0.428), (0.735, 0.405), color=COLORS["orange"], width=2.0)

    rounded_card(ax, 0.04, 0.205, 0.44, 0.195, face=COLORS["white"], edge="#D6CAE9")
    ax.add_patch(
        FancyBboxPatch(
            (0.04, 0.358),
            0.44,
            0.042,
            boxstyle="round,pad=0.008,rounding_size=0.018",
            transform=ax.transAxes,
            facecolor=COLORS["purple"],
            edgecolor=COLORS["purple"],
            linewidth=0,
            zorder=5,
        )
    )
    ax.text(
        0.06,
        0.379,
        "A  Reduced closed-loop convergence probe",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=11.2,
        fontweight="bold",
        color=COLORS["white"],
        zorder=6,
    )
    ax.text(
        0.065,
        0.332,
        "9 perturbed initial states",
        transform=ax.transAxes,
        fontsize=9.2,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        0.065,
        0.306,
        "calm  •  moderate  •  crisis   ×   delays 0 and 8 steps (48 h)",
        transform=ax.transAxes,
        fontsize=8.8,
        color=COLORS["muted"],
    )
    ax.text(
        0.065,
        0.275,
        r"State $z_t=(r_t,C_t,\lambda_t,D_t,b_t,v_t)$ evolved for 320 steps",
        transform=ax.transAxes,
        fontsize=8.8,
        color=COLORS["ink"],
    )
    metric_pill(ax, 0.112, 0.238, "tail movement", COLORS["purple_light"], COLORS["purple"])
    metric_pill(ax, 0.217, 0.238, "tail range", COLORS["purple_light"], COLORS["purple"])
    metric_pill(ax, 0.313, 0.238, "final spread", COLORS["purple_light"], COLORS["purple"])
    metric_pill(ax, 0.414, 0.238, "contraction", COLORS["purple_light"], COLORS["purple"])
    ax.text(
        0.26,
        0.216,
        "Robust ⇔ all bounded, ≥ 5/6 cases converge, worst final spread < 0.055",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.2,
        color=COLORS["purple"],
        fontweight="bold",
        zorder=7,
    )

    rounded_card(ax, 0.52, 0.205, 0.44, 0.195, face=COLORS["white"], edge="#F0CBB6")
    ax.add_patch(
        FancyBboxPatch(
            (0.52, 0.358),
            0.44,
            0.042,
            boxstyle="round,pad=0.008,rounding_size=0.018",
            transform=ax.transAxes,
            facecolor=COLORS["orange"],
            edgecolor=COLORS["orange"],
            linewidth=0,
            zorder=5,
        )
    )
    ax.text(
        0.54,
        0.379,
        "B  Full economic cross-check",
        transform=ax.transAxes,
        ha="left",
        va="center",
        fontsize=11.2,
        fontweight="bold",
        color=COLORS["white"],
        zorder=6,
    )
    ax.text(
        0.545,
        0.332,
        "192 common ARS paths  +  192 common TRY paths per parameter vector",
        transform=ax.transAxes,
        fontsize=9.1,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        0.545,
        0.306,
        "480 six-hour steps = four months  •  identical shocks across configurations",
        transform=ax.transAxes,
        fontsize=8.8,
        color=COLORS["muted"],
    )
    ax.text(
        0.545,
        0.275,
        r"$360\times(192+192)=138{,}240$ point–currency protocol paths",
        transform=ax.transAxes,
        fontsize=9.1,
        color=COLORS["ink"],
    )
    metric_pill(ax, 0.584, 0.238, "bad debt", COLORS["orange_light"], COLORS["orange"])
    metric_pill(ax, 0.668, 0.238, "depeg", COLORS["orange_light"], COLORS["orange"])
    metric_pill(ax, 0.752, 0.238, "credit", COLORS["orange_light"], COLORS["orange"])
    metric_pill(ax, 0.836, 0.238, "pause share", COLORS["orange_light"], COLORS["orange"])
    metric_pill(ax, 0.920, 0.238, "turnover", COLORS["orange_light"], COLORS["orange"])
    ax.text(
        0.74,
        0.216,
        "Economic safety and credit availability are evaluated separately from convergence.",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.2,
        color=COLORS["orange"],
        fontweight="bold",
        zorder=7,
    )

    # Stage 3: evidence synthesis.
    stage_label(ax, "3", "Evidence synthesis and topology", 0.045, 0.171)
    for start, end, color in (
        ((0.26, 0.202), (0.21, 0.144), COLORS["purple"]),
        ((0.74, 0.202), (0.50, 0.144), COLORS["orange"]),
        ((0.50, 0.202), (0.79, 0.144), COLORS["green"]),
    ):
        arrow(ax, start, end, color=color, width=1.7)

    output_specs = (
        (
            0.04,
            COLORS["purple"],
            COLORS["purple_light"],
            "LOCAL STABILITY",
            "360 / 360 robust",
            "261 pass all six cases; 99 pass five",
        ),
        (
            0.354,
            COLORS["orange"],
            COLORS["orange_light"],
            "ECONOMIC TRADE-OFF",
            "median bad-debt probability 0.2604%",
            "credit, depeg and breaker use remain explicit",
        ),
        (
            0.668,
            COLORS["green"],
            COLORS["green_light"],
            "STABLE-SET TOPOLOGY",
            r"normalise 8D → Vietoris–Rips + 30 null clouds",
            r"$\beta_0=1$; $H_1$ null $p=0.9355$: connected, no exceptional hole",
        ),
    )
    for x, accent, light, heading, main, detail in output_specs:
        rounded_card(ax, x, 0.045, 0.292, 0.091, face=light, edge=accent, radius=0.014, shadow=False)
        ax.text(
            x + 0.018,
            0.116,
            heading,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=8.2,
            fontweight="bold",
            color=accent,
            zorder=7,
        )
        ax.text(
            x + 0.018,
            0.086,
            main,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=9.2,
            fontweight="bold",
            color=COLORS["ink"],
            zorder=7,
        )
        ax.text(
            x + 0.018,
            0.061,
            detail,
            transform=ax.transAxes,
            ha="left",
            va="center",
            fontsize=7.8,
            color=COLORS["muted"],
            zorder=7,
        )

    ax.text(
        0.5,
        0.015,
        "Interpretation boundary: computational evidence for a connected local stability basin — not a global Lyapunov proof or a live-deployment claim.",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=8.2,
        color=COLORS["muted"],
        style="italic",
    )
    return fig


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    figure = build_figure()
    png_path = OUTPUT / "figure6_methodology_pipeline.png"
    svg_path = OUTPUT / "figure6_methodology_pipeline.svg"
    figure.savefig(png_path, dpi=240, bbox_inches="tight", facecolor=COLORS["paper"])
    figure.savefig(svg_path, bbox_inches="tight", facecolor=COLORS["paper"])
    plt.close(figure)
    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {svg_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
