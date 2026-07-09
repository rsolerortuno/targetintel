# Weight-sensitivity snapshot

This directory contains a versioned snapshot of the TargetIntel-IO scoring
weight-sensitivity analysis.

The analysis perturbs one top-level scoring weight at a time by `-20%` or
`+20%`. After each perturbation, all weights are renormalized and the complete
ranking and benchmark evaluation are recalculated.

## Main result

Across 42 perturbation scenarios:

- all three therapeutic-intent profiles retained 100% of their baseline top 5;
- worst-case top-10 retention was 90% for antibody/IO, 100% for biomarker, and
  90% for small-molecule ranking;
- worst-case top-20 retention was 100%, 95%, and 100%, respectively;
- minimum Spearman rank correlation was 0.9852;
- no perturbation changed strict primary-intent accuracy or acceptable-intent
  accuracy.

![Weight-sensitivity overview](sensitivity_overview.png)

## Results by therapeutic-intent profile

| Profile | Scenarios | Minimum Spearman | Minimum top-5 retention | Minimum top-10 retention | Minimum top-20 retention | Maximum mean absolute rank change | Worst-correlation scenario |
|---|---:|---:|---:|---:|---:|---:|---|
| Antibody / IO | 14 | 1.0000 | 100.0% | 90.0% | 100.0% | 0.036 | antibody_io__confidence_score__minus20 |
| Biomarker | 14 | 1.0000 | 100.0% | 100.0% | 95.0% | 0.091 | biomarker__opentargets_score__plus20 |
| Small molecule | 14 | 0.9852 | 100.0% | 90.0% | 100.0% | 3.142 | small_molecule__role_fit_score__minus20 |

## Interpretation

The results indicate that the high-priority portion of each ranking is locally
robust to moderate changes in individual scoring weights.

The small-molecule profile is the most sensitive globally, but its complete
top 5 and top 20 remain unchanged in every tested scenario. Its worst-case
top-10 retention is 90%.

Large position changes can occur among low-scoring or tied targets near the
bottom of the ranking. These tail changes do not imply equivalent instability
among the prioritized targets.

## Scope and limitations

This is a local one-weight-at-a-time sensitivity analysis. It does not test:

- simultaneous perturbation of multiple weights;
- changes larger than 20%;
- alternative scoring functions;
- uncertainty in the curated biological rules;
- independent biological or clinical validation.

The result therefore supports local robustness of the implemented scoring
profiles, not universal independence from weight selection.

## Included files

| File | Description |
|---|---|
| `sensitivity_scenarios.csv` | Metrics for every profile, weight, and perturbation direction |
| `sensitivity_summary.csv` | Worst-case and mean stability metrics by therapeutic profile |
| `sensitivity_by_weight.csv` | Stability metrics grouped by profile and perturbed weight |
| `target_rank_stability.csv` | Per-target rank variation across all perturbation scenarios |
| `sensitivity_metrics.json` | Analysis parameters and machine-readable summary |
| `sensitivity_overview.png` | Compact visualization of worst-case ranking stability |
| `snapshot_manifest.json` | SHA-256 hashes and snapshot metadata |

## Reproduce the analysis

~~~bash
python scripts/11_run_sensitivity_analysis.py \
  --input results/benchmark/ranked_targets_benchmark_universe.csv \
  --benchmark-config configs/benchmark_targets.yaml \
  --outdir results/sensitivity \
  --perturbation 0.20 \
  --top-k 5 10 20

python scripts/12_generate_sensitivity_figure.py \
  --input results/sensitivity/sensitivity_summary.csv \
  --output results/sensitivity/sensitivity_overview.png
~~~

The maximum observed change in the two principal benchmark-accuracy metrics was
`0.0000`.
