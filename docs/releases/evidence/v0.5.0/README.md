# DepMap Public 26Q1 release-closure evidence

This directory records the repository-safe evidence for the TargetIntel-IO
v0.5.0 real-data release-closure run.

## Verified scope

- Data release: `DepMap_Public_26Q1`
- Context: `melanoma_anti_pd1:v1`
- Primary cohort: 56 reviewed cutaneous melanoma models
- Acral sensitivity cohort: 4 models
- Benchmark universe: 56 genes
- Discovery universe: 331 genes after required benchmark union
- Background universe: 18,531 genes
- Benchmark coverage: 100%
- Holdout coverage: 100%

## Reproducibility

Two independent persistent executions were completed. Each run also passed
the workflow's internal replica comparison.

- Run A internal result: `reproducible`
- Run B internal result: `reproducible`
- External A-versus-B result: `reproducible`
- Differing scientific artifacts: 0
- Scientific closure identity:
  `v050closure_e57fa135ff266078d2170bf2a34df094f7888e7ce6002783c75f6a583690a3a4`

## Release boundary

The resulting state is `ready_research_preview_human_review`.

The production baseline remains preserved. Candidate activation remains
disabled and requires a separate human decision. These results establish
technical reproducibility for the local public-data workflow; they do not
constitute clinical validation or evidence of anti-PD-1 treatment response.

The DepMap matrices, local run directories, and machine-specific paths are
intentionally not committed.
