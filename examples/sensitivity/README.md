# Weight-sensitivity snapshot

This directory contains a versioned snapshot of the TargetIntel-IO scoring
weight-sensitivity analysis.

The analysis perturbs one top-level scoring weight at a time by `-20%` or
`+20%`. After each perturbation, all weights are renormalized and the complete
ranking and benchmark evaluation are recalculated.

This corrected snapshot supersedes the sensitivity snapshot originally
published in v0.1.1. The earlier sensitivity preprocessing incorrectly removed
the `biomarker_fit` and `small_molecule_fit` input features before rescoring.
The official benchmark snapshot was not affected.

## Main result

Across 42 perturbation scenarios:

- worst-case top-5 retention was 100% for antibody/IO, 100% for biomarker,
  and 80% for small molecule;
- worst-case top-10 retention was 90%, 100%, and 90%, respectively;
- worst-case top-20 retention was 100%, 95%, and 100%, respectively;
- minimum Spearman rank correlation was 0.8762;
- maximum absolute strict primary-intent accuracy change was 5.36 percentage
  points;
- maximum absolute acceptable-intent accuracy change was 3.57 percentage
  points;
- maximum absolute cross-intent specificity change was 5.66 percentage
  points.

![Weight-sensitivity overview](sensitivity_overview.png)

## Results by therapeutic-intent profile

| Profile | Scenarios | Minimum Spearman | Minimum top-5 retention | Minimum top-10 retention | Minimum top-20 retention | Maximum mean absolute rank change | Worst-correlation scenario |
|---|---:|---:|---:|---:|---:|---:|---|
| Antibody / IO | 14 | 1.0000 | 100.0% | 90.0% | 100.0% | 0.0363 | `antibody_io__confidence_score__minus20` |
| Biomarker | 14 | 1.0000 | 100.0% | 100.0% | 95.0% | 0.1692 | `biomarker__resistance_axis_score__minus20` |
| Small molecule | 14 | 0.8762 | 80.0% | 90.0% | 100.0% | 17.0091 | `small_molecule__opentargets_score__plus20` |

## Interpretation

The antibody/IO and biomarker profiles are highly stable under the tested
local perturbations.

The small-molecule profile is more sensitive to individual weight changes:

- one of its five baseline top targets can leave the top five;
- its worst-case global rank correlation falls to 0.8762;
- its top-10 retention nevertheless remains at least 90%;
- its top-20 set remains unchanged in every tested scenario.

Large rank changes also occur among low-scoring or tied targets near the bottom
of the ranking. Those tail movements should not be interpreted as equivalent
instability among the highest-priority candidates.

## Benchmark consistency

The baseline benchmark summary embedded in `sensitivity_metrics.json` matches
the official benchmark snapshot in
`examples/benchmark/benchmark_summary.json`.

The baseline therefore retains:

- strict primary-intent accuracy: 91.07%;
- acceptable-intent accuracy: 100%;
- cross-intent specificity: 90.57%;
- mean top-10 recall: 58.10%;
- mean top-20 recall: 79.46%.

## Scope and limitations

This is a local one-weight-at-a-time sensitivity analysis. It does not test:

- simultaneous perturbation of multiple weights;
- changes larger than 20%;
- alternative scoring functions;
- uncertainty in the curated biological rules;
- independent biological or clinical validation.

The result supports bounded local robustness of the implemented scoring
profiles. It does not demonstrate universal independence from weight selection.

## Included files

| File | Description |
|---|---|
| `sensitivity_scenarios.csv` | Metrics for every profile, weight, and perturbation direction |
| `sensitivity_summary.csv` | Worst-case and mean stability metrics by therapeutic profile |
| `sensitivity_by_weight.csv` | Stability metrics grouped by profile and perturbed weight |
| `target_rank_stability.csv` | Per-target rank variation across all perturbation scenarios |
| `sensitivity_metrics.json` | Analysis parameters, baseline benchmark, and machine-readable summary |
| `sensitivity_overview.png` | Annotated heatmap of worst-case ranking stability |
| `snapshot_manifest.json` | SHA-256 hashes and snapshot metadata |

## Reproduce the analysis

    python scripts/11_run_sensitivity_analysis.py \
      --input results/benchmark/ranked_targets_benchmark_universe.csv \
      --benchmark-config configs/benchmark_targets.yaml \
      --outdir results/sensitivity \
      --perturbation 0.20 \
      --top-k 5 10 20

    python scripts/12_generate_sensitivity_figure.py \
      --input results/sensitivity/sensitivity_summary.csv \
      --output results/sensitivity/sensitivity_overview.png
