# Changelog

All notable changes to TargetIntel-IO are documented in this file.

## [Unreleased]

### Added

- Added the `targetintel` command-line interface.
- Added `targetintel run` as a single end-to-end command for public-data
  ingestion, feature construction, therapeutic-intent scoring, hypothesis
  cards, HTML reports, and summary figures.
- Added `targetintel run --validate` to additionally execute the internal
  56-target benchmark and 42-scenario weight-sensitivity analysis.
- Added pipeline and command-line regression tests.

### Changed

- Reworked the main README around the new `targetintel run` end-to-end workflow.
- Consolidated duplicated benchmark, sensitivity, installation, and project-status documentation.
- Replaced obsolete prototype commands and planned milestones with the implemented package, CLI, outputs, and validation workflow.
- Added README regression tests for the repository URL, CLI quick start, versioned examples, obsolete content, and document length.

## [0.1.2] - 2026-07-10

### Fixed

- Corrected sensitivity preprocessing that incorrectly removed the
  `biomarker_fit` and `small_molecule_fit` input features when recalculating
  perturbed rankings.
- Regenerated the complete weight-sensitivity snapshot from the current
  benchmark universe and scoring configurations.
- Added regression validation requiring the sensitivity baseline benchmark
  to match the official benchmark snapshot.
- Replaced the sensitivity visualization with an annotated heatmap using a
  focused scale so differences near 1.0 remain visible.

### Corrected sensitivity results

Across 42 one-weight-at-a-time perturbation scenarios:

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

These corrected results supersede the sensitivity metrics published in
v0.1.1. The benchmark snapshot itself was not affected.

## [0.1.1] - 2026-07-09

### Added

- One-weight-at-a-time scoring sensitivity analysis with `-20%` and `+20%`
  perturbations followed by weight renormalization.
- Ranking-stability metrics including Spearman correlation, top-k Jaccard
  similarity, top-k retention, and per-target rank variation.
- Versioned sensitivity-analysis snapshot with machine-readable outputs,
  SHA-256 manifest, visualization, and regression tests.
- Quantitative README limitations grounded in the committed benchmark and
  sensitivity snapshots.
- Complete runtime dependency declarations in `pyproject.toml` and
  `environment.yml`.
- Exact Python 3.11 dependency lockfile with transitive dependencies and
  package hashes.
- CI installation from the locked dependency environment.

### Sensitivity results

Across 42 one-weight-at-a-time perturbation scenarios:

- all therapeutic-intent profiles retained 100% of their baseline top five;
- worst-case top-10 retention was 90% for antibody/IO, 100% for biomarker,
  and 90% for small-molecule ranking;
- worst-case top-20 retention was 100%, 95%, and 100%, respectively;
- minimum Spearman rank correlation was 0.9852;
- no tested perturbation changed strict primary-intent accuracy or
  acceptable-intent accuracy.

### Documentation

- Clarified that only 25 of 56 benchmark targets were retrieved among the
  top 300 Open Targets melanoma associations.
- Clarified that 100% stable-role accuracy measures consistency with the
  implemented curated rules rather than independent biological validation.
- Documented the scope and limitations of the internal benchmark and local
  weight-sensitivity analysis.

## [0.1.0] - 2026-07-09

### Added

- Open Targets melanoma-associated target retrieval with local caching.
- Stable biological and translational role classification.
- Resistance-axis ontology for anti-PD-1-resistant melanoma.
- Modality-aware reasoning for antibody, biomarker, and small-molecule use.
- Evidence auditing, contradiction detection, and confidence assignment.
- Therapeutic-intent-specific scoring profiles.
- Deterministic ranking and rank-shift analysis.
- Explainable hypothesis cards and HTML target reports.
- Benchmark and ranking visualizations.
- Curated 56-target therapeutic-intent benchmark.
- Augmented benchmark universe separating Open Targets retrieval coverage from
  TargetIntel-IO evaluation coverage.
- Versioned benchmark result snapshot with SHA-256 manifest.
- Automated benchmark snapshot regeneration command.
- Offline unit and regression test suite with 42 tests.
- GitHub Actions continuous integration.

### Benchmark snapshot

- TargetIntel evaluation coverage: 56/56 targets.
- Open Targets top-300 retrieval coverage: 25/56 targets.
- Stable-role accuracy: 100%.
- Strict primary-intent accuracy: 91.1%.
- Acceptable-intent accuracy: 100%.
- Cross-intent specificity: 90.6%.
- Mean top-10 recall: 58.1%.
- Mean top-20 recall: 79.5%.

### Fixed

- Corrected the Open Targets GraphQL disease argument to use `efoId` while
  retaining the valid melanoma identifier `MONDO_0005105`.
- Improved Open Targets HTTP and GraphQL error reporting.
- Prevented benchmark-only targets from receiving artificial Open Targets
  ranks.
- Corrected benchmark command formatting in the main README.

### Validation scope

The benchmark is an internal, rule-based sanity validation. It does not
constitute independent clinical validation, biomarker qualification, or
evidence of therapeutic efficacy.
