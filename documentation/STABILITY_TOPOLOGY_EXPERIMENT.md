# Stability and topology experiment

## Research question

This experiment asks whether controller coefficients that converge are isolated
calibration accidents or members of a robust neighbourhood, and whether the
empirically stable set has a detectable connected-component or hole structure.
It is a computational stability study, not a formal convergence proof.

## Reproduction

From the repository root:

```bash
python3 analysis/run_stability_topology.py \
  --points 360 \
  --pilot-points 96 \
  --market-paths 192
```

The deterministic seed is `20261105`. All configurations receive identical
market paths (common random numbers), so between-configuration differences are
attributable to controller parameters rather than different shock draws.

## Parameter collection

The eight-dimensional vector is

\[
\theta=(\beta,w_\sigma,w_b,w_\delta,w_u,g_r,g_C,g_\lambda).
\]

| Parameter | Baseline | Broad interval | Role |
|---|---:|---:|---|
| `ewma_memory` \(\beta\) | 0.92 | [0.80, 0.98] | EWMA persistence |
| `volatility_weight` \(w_\sigma\) | 4.00 | [2.50, 5.50] | volatility contribution to risk |
| `basis_weight` \(w_b\) | 3.20 | [2.00, 4.50] | DEX-basis contribution |
| `disagreement_weight` \(w_\delta\) | 1.80 | [1.00, 2.80] | oracle-disagreement contribution |
| `utilization_weight` \(w_u\) | 0.90 | [0.40, 1.40] | excess-utilisation contribution |
| `rate_risk_gain` \(g_r\) | 0.90 | [0.50, 1.30] | borrowing-rate response |
| `ceiling_risk_gain` \(g_C\) | 1.75 | [0.80, 2.80] | debt-ceiling response |
| `liquidation_risk_gain` \(g_\lambda\) | 0.70 | [0.35, 1.10] | liquidation-ratio response |

The parameterised equations preserve the published baseline exactly:

\[
v_{t+1}=\beta v_t+(1-\beta)q_t^2,
\]

\[
R_t=\operatorname{clip}_{[0,1]}\left(
w_\sigma\sqrt{v_{t+1}}+w_b b_t+w_\delta\delta_t+
w_u(u_t-0.72)_+\right),
\]

\[
r_t^*=\operatorname{clip}_{[0.04,1.50]}
\left(0.08+g_rR_t+0.35(u_t-0.75)_+\right),
\]

\[
C_t^*=\operatorname{clip}_{[0.20,1.00]}(e^{-g_CR_t}),\qquad
\lambda_t^*=\operatorname{clip}_{[1.50,2.20]}(1.50+g_\lambda R_t).
\]

## Two-stage sampling

1. A 96-point maximin-style Latin-hypercube pilot covers the broad box. The
   published baseline is inserted as a reference point.
2. A stable centre is selected by minimising the convergence score with a small
   penalty for distance from the published baseline.
3. A second Latin-hypercube draws exactly 360 points in an axis-aligned local
   neighbourhood around that centre. Sampling is stratified in every dimension,
   rather than using independent pseudo-random draws that can leave large gaps.

The selected centre was

\[
(0.94569,3.17732,2.31667,1.48870,0.70887,0.52487,0.81518,0.57902).
\]

This is a candidate centre for robustness analysis, not a claimed optimum or a
replacement calibration.

## Convergence and stability definition

Each parameter vector is tested in a reduced closed-loop model with state

\[
z_t=(r_t,C_t,\lambda_t,D_t,b_t,v_t),
\]

where debt demand decreases with the rate and available ceiling, debt is repaid,
DEX basis responds to accepted draws and arbitrage capacity, and the breaker can
pause new draws. Nine perturbed initial states are used in each case.

There are six cases: calm, moderate, and crisis inputs, each with zero delay and
an eight-step (48-hour) control delay. A case is converged only if the trajectory
is finite and bounded, the normalised tail step is below 0.002, the tail range is
below 0.030, the terminal ensemble spread is below 0.040, and the terminal to
initial spread ratio is below 0.50. A vector is labelled robustly convergent if
all cases remain bounded, at least five of six converge, and worst terminal
spread is below 0.055.

The full economic cross-check then runs every local vector on 192 common ARS
paths and 192 common TRY paths, each with 480 six-hour steps. Consequently the
local stage evaluates 138,240 four-month protocol paths.

## Results

- 11 of 96 broad pilot points were robustly convergent.
- The published baseline converged in four of six reduced cases. It remained
  bounded, but did not pass the stricter perturbation-contraction criterion.
- All 360 local points were robustly convergent; 261 converged in all six cases
  and 99 converged in five of six.
- Median pooled bad-debt-event probability was 0.2604%.
- Across the local cloud, pooled bad-debt-event probability ranged from 0% to
  1.3021%, mean credit from 0.1948 to 0.2307, and pause share from 0.4092 to
  0.6184.
- TRY retained a roughly 20.8% severe-depeg probability in this finite common
  path set, while ARS had none. Stability of the controller therefore does not
  imply elimination of every economic failure mode.

The strongest rank relationships were descriptive rather than causal:

- debt-ceiling gain versus stability score: \(\rho=0.931\);
- liquidation gain versus bad-debt probability: \(\rho=-0.839\);
- rate gain versus pause share: \(\rho=-0.587\); and
- debt-ceiling gain versus mean credit: \(\rho=-0.550\).

## Topological analysis

Parameters are rescaled to the unit cube. Persistent homology is computed on the
robustly convergent cloud using the Vietoris-Rips filtration.

The connected-component barcode becomes one component at radius 0.7390. The
largest observed one-dimensional persistence was 0.1844. To distinguish a real
hole from sparse high-dimensional sampling, the same statistic was computed for
30 eight-dimensional Latin-hypercube null clouds. Their median maximum
persistence was 0.1980 and their 95th percentile was 0.2265. The empirical null
p-value was 0.9355.

Therefore the experiment supports a connected local stable neighbourhood, but
does **not** support a non-trivial one-dimensional hole beyond what uniform
high-dimensional sampling produces. In ordinary language: the convergent region
looks like a connected basin locally, not several isolated islands or a robust
ring. This is finite-sample evidence, not a proof of global contractibility.

## Interpretation and limitations

The main conclusion is local robustness: after locating a stable centre, every
one of 360 stratified nearby configurations passed the robust criterion. This is
stronger than showing that one hand-selected coefficient vector converges.

The conclusion is deliberately limited:

- empirical convergence does not replace a Lyapunov or Lyapunov-Krasovskii proof;
- the topology is that of a sampled local parameter cloud, not the full global
  feasible set;
- thresholds defining convergence are preregistered computational criteria and
  should be sensitivity-tested in future work;
- persistent-homology cycles in sparse high-dimensional clouds can be sampling
  artefacts, which is why a matched null test is included; and
- economic safety and dynamical convergence are different claims. A convergent
  controller can still settle at a state with undesirable credit or depeg trade-offs.

## Output map

| Path | Contents |
|---|---|
| `results/stability_topology/pilot_parameter_search.csv` | 96 broad pilot points |
| `results/stability_topology/local_360_parameter_results.csv` | parameters, stability metrics, and pooled outcomes |
| `results/stability_topology/economic_results_by_currency.csv` | 720 point-currency records |
| `results/stability_topology/topology_persistence_intervals.csv` | H0 and H1 persistence intervals |
| `results/stability_topology/topology_betti_curves.csv` | Betti numbers across filtration scale |
| `results/stability_topology/parameter_influence.csv` | rank correlations and p-values |
| `results/stability_topology/experiment_summary.json` | seed, bounds, headline results, and SHA-256 hashes |
| `figures/stability_topology/` | six publication-ready figures, including the methodology pipeline in PNG and SVG |
| `analysis/create_methodology_diagram.py` | deterministic source for the methodology pipeline figure |
