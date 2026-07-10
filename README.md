# TargetIntel-IO

[![Tests](https://github.com/rsolerortuno/TargetIntel-IO/actions/workflows/tests.yml/badge.svg)](https://github.com/rsolerortuno/TargetIntel-IO/actions/workflows/tests.yml)
[![Latest release](https://img.shields.io/github/v/release/rsolerortuno/TargetIntel-IO)](https://github.com/rsolerortuno/TargetIntel-IO/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Explainable therapeutic-intent-aware target triage for anti-PD-1-resistant melanoma.**

TargetIntel-IO is a transparent, rule-based translational bioinformatics
framework that classifies and prioritizes candidate genes according to the
therapeutic question being asked.

A biologically relevant gene is not automatically a good drug target. It may
instead be a resistance biomarker, a mechanistic marker, a tumor-intrinsic
driver, an immune-context signal, or a poor direct therapeutic candidate.
TargetIntel-IO makes those distinctions explicit and traceable.

> The central question is not “What is the best target?”
> It is “Best candidate for which therapeutic intent, and why?”

## What it produces

For every candidate, TargetIntel-IO generates:

- a stable biological and translational role;
- a therapeutic direction;
- matched anti-PD-1 resistance programs;
- modality-fit assessments;
- evidence supporting and arguing against prioritization;
- confidence and uncertainty annotations;
- separate rankings for three therapeutic intents;
- structured Markdown hypothesis cards;
- browsable HTML reports;
- summary figures and rank-shift analyses.

The three current ranking modes are:

| Mode | Prioritizes |
|---|---|
| Antibody / IO combination | Surface-accessible checkpoints, myeloid targets, suppressive immune axes, and combination rationale |
| Resistance biomarker | Antigen-presentation loss, IFNγ resistance, immune exclusion, and patient-stratification potential |
| Small molecule | Tumor-intrinsic drivers, kinases, oncogenic pathways, and small-molecule tractability |

## Quick start

### Conda

~~~bash
git clone https://github.com/rsolerortuno/TargetIntel-IO.git
cd TargetIntel-IO

conda env create -f environment.yml
conda activate targetintel
~~~

### Pip

~~~bash
git clone https://github.com/rsolerortuno/TargetIntel-IO.git
cd TargetIntel-IO

python -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
~~~

## Run the complete workflow

Generate the feature table, therapeutic-intent rankings, target cards, HTML
reports, and figures:

~~~bash
targetintel run
~~~

Run the same workflow and additionally execute the internal benchmark and
weight-sensitivity analysis:

~~~bash
targetintel run --validate
~~~

Force a new Open Targets request instead of using the local cache:

~~~bash
targetintel run --refresh
~~~

See all available options:

~~~bash
targetintel run --help
~~~

## Main outputs

~~~text
data/processed/
└── targetintel_feature_table_v0_1.csv

results/
├── ranked_targets.csv
├── target_cards/
├── html_reports/
│   └── index.html
├── figures/
├── benchmark/
└── sensitivity/
~~~

After a successful run, open:

~~~text
results/html_reports/index.html
~~~

Versioned example outputs are committed under:

- [`examples/html_reports/`](examples/html_reports/)
- [`examples/figures/`](examples/figures/)
- [`examples/benchmark/`](examples/benchmark/README.md)
- [`examples/sensitivity/`](examples/sensitivity/README.md)

## How it works

### 1. Public evidence retrieval

The workflow retrieves melanoma-associated targets from the Open Targets
GraphQL API and caches the response locally for reproducibility.

### 2. Translational feature construction

Each target is annotated using:

- disease-association evidence;
- anti-PD-1 resistance-axis membership;
- therapeutic modality fit;
- tractability and known-drug evidence;
- safety and contradiction flags;
- evidence completeness and confidence.

### 3. Stable role classification

Each candidate receives one stable role independent of ranking mode, such as:

- direct therapeutic target;
- anti-PD-1 combination target;
- resistance biomarker;
- mechanistic resistance marker;
- tumor-intrinsic driver;
- immune-context marker;
- poor direct therapeutic target.

This explicitly separates:

~~~text
therapeutic target ≠ biomarker ≠ resistance mechanism ≠ poor direct target
~~~

### 4. Therapeutic-intent-aware scoring

The same candidate is scored differently for antibody/IO, biomarker, and
small-molecule use. Every final score retains its component values, penalties,
role interpretation, and supporting or opposing evidence.

### 5. Human-readable outputs

The workflow converts the ranked table into hypothesis cards, HTML reports,
figures, benchmark summaries, and machine-readable validation outputs.

## Internal benchmark snapshot

TargetIntel-IO includes a curated 56-target benchmark for internal rule-based
sanity validation.

| Metric | Result |
|---|---:|
| Benchmark targets evaluated | 56 / 56 |
| TargetIntel evaluation coverage | 100% |
| Open Targets top-300 retrieval coverage | 44.6% |
| Stable-role accuracy | 100.0% |
| Strict primary-intent accuracy | 91.1% |
| Acceptable-intent accuracy | 100.0% |
| Cross-intent specificity | 90.6% |
| Control not-prioritized rate | 100.0% |
| Mean top-10 recall | 58.1% |
| Mean top-20 recall | 79.5% |

Only **25/56 (44.6%)** benchmark targets appeared among the top 300 melanoma
associations retrieved from Open Targets. The remaining 31 targets were added
explicitly to the augmented benchmark universe without retrieved Open Targets
evidence.

Therefore, **56/56 (100%) TargetIntel evaluation coverage** means that the
software evaluated every curated benchmark target. It does not mean that Open
Targets independently recovered every target.

The benchmark produced **100.0% stable-role accuracy**, but its expected roles
were curated using the same biological and translational framework represented
by the implemented rules. This measures implementation consistency, not
independent biological accuracy.

Strict primary-intent accuracy was **91.1% (51/56)**, with five strict
disagreements. Acceptable-intent accuracy was **100.0%** because predefined,
therapeutically plausible alternative intents were accepted.

Mean recall across therapeutic-intent profiles was **58.1% at top 10** and
**79.5% at top 20**.

Complete results and per-target predictions are available in the
[versioned benchmark snapshot](examples/benchmark/README.md).

## Weight sensitivity

The local sensitivity analysis evaluated **42 scenarios** in which one scoring
weight was changed by `-20%` or `+20%` and all weights were subsequently
renormalized.

- Worst-case top-5 retention was:
  **antibody/IO 100%, biomarker 100%, small-molecule 80%**.
- Worst-case top-10 retention was:
  **antibody/IO 90%, biomarker 100%, small-molecule 90%**.
- Worst-case top-20 retention was:
  **antibody/IO 100%, biomarker 95%, small-molecule 100%**.
- The minimum observed Spearman rank correlation was **0.8762**.
- The maximum absolute change in strict primary-intent accuracy was
  **5.36 percentage points**.
- The maximum absolute change in acceptable-intent accuracy was
  **3.57 percentage points**.
- The maximum absolute change in cross-intent specificity was
  **5.66 percentage points**.

![Worst-case ranking stability](examples/sensitivity/sensitivity_overview.png)

The analysis shows strong local stability at top 10 and top 20 while
identifying greater weight sensitivity in the small-molecule profile. It does
not establish that rankings are independent of weight selection.

Complete scenarios and per-target rank changes are available in the
[versioned sensitivity snapshot](examples/sensitivity/README.md).

## Interpretation and limitations

TargetIntel-IO is a hypothesis-generation and target-triage framework. It does
not provide clinical recommendations, biomarker qualification, validated
therapeutic targets, or medical advice.

The benchmark is internally curated rather than derived from an independent,
blinded, prospective, or clinical dataset. **No external patient-level
responder/non-responder cohort** is currently used to validate the rankings.

The current implementation is specific to anti-PD-1-resistant melanoma.
Association evidence does not establish causality, therapeutic tractability,
safety, clinical benefit, or successful combination with anti-PD-1 therapy.

The sensitivity analysis tests only one-weight-at-a-time perturbations of
±20%. It does not assess simultaneous weight changes, larger perturbations,
alternative scoring functions, or uncertainty in the curated biological rules.

Large rank changes can occur among low-scoring or tied targets near the bottom
of a ranking even when the highest-priority candidates remain stable.

All generated hypotheses require independent experimental, translational, and
clinical validation.

## Reproducibility

The project includes:

- compatible dependency ranges in `pyproject.toml`;
- a Conda environment definition in `environment.yml`;
- an exact Python 3.11 lockfile with package hashes;
- local API caching;
- deterministic ranking and tie-breaking;
- versioned benchmark and sensitivity snapshots;
- SHA-256 snapshot manifests;
- GitHub Actions continuous integration;
- offline unit and regression tests.

Install the exact environment used by CI with:

~~~bash
python -m pip install \
  --require-hashes \
  --requirement requirements-lock.txt

python -m pip install \
  --no-deps \
  --no-build-isolation \
  --editable .
~~~

Run the test suite with:

~~~bash
python -m pytest tests -q
~~~

## Repository map

~~~text
configs/        Disease context, resistance axes, benchmark, and scoring YAMLs
targetintel/    Reusable Python package and command-line workflow
scripts/        Individual pipeline and snapshot-management commands
tests/          Unit, integration, and regression tests
examples/       Versioned reports, figures, benchmark, and sensitivity outputs
data/           Cached and processed local data, excluded from version control
results/        Generated local analysis outputs, excluded from version control
~~~

## Data sources

The current implementation uses public data and curated public-domain
biological knowledge. The principal external source is the Open Targets
Platform GraphQL API.

No confidential, proprietary, company-internal, or identifiable patient data
is included.

## Citation

~~~text
Soler Ortuño R. TargetIntel-IO: Explainable therapeutic-intent-aware target
triage for anti-PD-1-resistant melanoma.
~~~

## Author

**Rafael Soler Ortuño, PhD**

Computational biologist focused on immuno-oncology, biomarker discovery,
patient stratification, single-cell and spatial transcriptomics, and
AI-assisted drug discovery.

[LinkedIn](https://www.linkedin.com/in/rafael-soler-ortuno/)

## License

Released under the [MIT License](LICENSE).
