# TargetIntel-IO

[![Tests](https://github.com/rsolerortuno/TargetIntel-IO/actions/workflows/tests.yml/badge.svg)](https://github.com/rsolerortuno/TargetIntel-IO/actions/workflows/tests.yml)

**Explainable therapeutic-intent-aware target triage for anti-PD-1-resistant melanoma**

TargetIntel-IO is a transparent, rule-based translational bioinformatics framework for prioritizing and classifying candidate genes in **anti-PD-1-resistant melanoma**.

The project addresses a common challenge in early-stage immuno-oncology target discovery: many genes are associated with melanoma, immune response, or therapy resistance, but not all of them are good therapeutic targets.

Some genes are true therapeutic targets. Others are better interpreted as immunotherapy-combination opportunities, resistance biomarkers, mechanistic resistance markers, tumor-intrinsic drivers, immune-context markers, or poor direct therapeutic candidates.

TargetIntel-IO is designed to answer a more translational question:

> In anti-PD-1-resistant melanoma, is this candidate a therapeutic target, an immunotherapy-combination target, a resistance biomarker, a mechanistic resistance marker, a tumor-intrinsic driver, or a poor direct target — and what evidence supports or argues against that classification?

Rather than producing a single generic ranked gene list, TargetIntel-IO assigns each candidate a stable biological/translational role and ranks it differently depending on the therapeutic intent.

---

## Core idea

**Target priority is not absolute. It depends on therapeutic intent.**

A gene may be highly relevant as a resistance biomarker but weak as an antibody target. Another gene may be a strong tumor-intrinsic small-molecule target but not a good immunotherapy-combination target.

TargetIntel-IO therefore separates two concepts:

1. **Stable role classification**
   What type of translational entity is this gene?

2. **Therapeutic-intent-aware ranking**
   How useful is this gene for a specific therapeutic question?

Initial therapeutic intent modes:

* **Antibody / IO-combination targeting**
* **Resistance biomarker discovery**
* **Tumor-intrinsic / small-molecule intervention**

---

## What TargetIntel-IO is

TargetIntel-IO is:

* an explainable target triage framework;
* a rule-based translational prioritization tool;
* a public-data-driven portfolio project;
* a reproducible workflow for immuno-oncology target assessment;
* a framework for separating therapeutic targets, biomarkers, mechanisms, and poor direct candidates;
* a tool for generating structured target hypothesis cards.

---

## What TargetIntel-IO is not

TargetIntel-IO is not:

* a full AI drug discovery platform;
* a de novo target discovery algorithm;
* a clinical prediction model;
* a replacement for experimental validation;
* a black-box biomarker predictor;
* a claim that the top-ranked genes are newly validated therapeutic targets.

The goal is not to claim new validated biology. The goal is to build a transparent, auditable, and biologically interpretable framework for translational target triage.

---

## Biological use case

The first disease context is:

**Anti-PD-1-resistant melanoma**

Immune checkpoint blockade has transformed melanoma treatment, but many patients show primary or acquired resistance to anti-PD-1 therapy.

TargetIntel-IO focuses on resistance mechanisms such as:

* T-cell exhaustion;
* checkpoint redundancy;
* antigen-presentation loss;
* IFNγ-pathway resistance;
* myeloid suppression;
* Treg-mediated suppression;
* TGFβ/CAF-driven immune exclusion;
* immune-cold tumor states;
* metabolic immune suppression;
* melanoma plasticity and dedifferentiation;
* stromal exclusion;
* poor T-cell infiltration.

The project aims to move from:

> Which genes are associated with melanoma?

to:

> Which genes are relevant to anti-PD-1 resistance, what translational role do they have, and how should they be prioritized depending on therapeutic intent?

---

## MVP architecture

TargetIntel-IO v1 is organized around the following modules.

### 1. Open Targets ingestion

The first evidence layer retrieves melanoma-associated targets from Open Targets.

For each candidate, the pipeline extracts, when available:

* target symbol;
* Open Targets disease-association score;
* tractability information;
* known drugs;
* maximum clinical phase;
* modality-related evidence;
* genetic association evidence;
* safety signals.

Open Targets provides the baseline disease-association and tractability layer, but TargetIntel-IO does not simply reproduce an Open Targets ranking. It adds a translational classification and therapeutic-intent-aware ranking layer on top.

Expected output columns include:

```text
target_symbol
opentargets_score
known_drug_count
max_clinical_phase
tractability_antibody
tractability_small_molecule
tractability_protac
safety_flags
genetic_association_evidence
```

---

### 2. API caching and reproducibility

TargetIntel-IO uses public APIs, so the project includes local caching from the beginning.

The first run fetches API data and stores it locally. Later runs use cached data unless the user explicitly requests a refresh.

Suggested cache structure:

```text
data/cache/
├── opentargets_cache.json
├── pubmed_counts_cache.json
├── clinicaltrials_cache.json
└── targetintel_cache.sqlite
```

This makes the project faster, more reproducible, and more professional.

---

### 3. Anti-PD-1 resistance ontology

TargetIntel-IO includes a curated ontology of biological resistance axes relevant to anti-PD-1-resistant melanoma.

Initial resistance axes include:

| Resistance axis                         | Example genes / targets                            |
| --------------------------------------- | -------------------------------------------------- |
| Checkpoint redundancy                   | LAG3, TIGIT, HAVCR2, CTLA4                         |
| Antigen-presentation loss               | B2M, HLA-A, HLA-B, HLA-C, TAP1, TAP2               |
| IFNγ resistance                         | JAK1, JAK2, IFNGR1, IFNGR2, STAT1, IRF1            |
| Myeloid suppression                     | CSF1R, TREM2, MARCO, LILRB1, LILRB2, LILRB3, MERTK |
| Metabolic immune suppression            | NT5E, ENTPD1, IDO1, ARG1                           |
| TGFβ/CAF exclusion                      | TGFB1, TGFBR1, TGFBR2, CXCL12, CXCR4, FAP          |
| Melanoma plasticity / dedifferentiation | AXL, WNT5A, TWIST2, NGFR                           |
| Tumor-intrinsic driver biology          | BRAF, NRAS, MAP2K1, PTEN, CDKN2A                   |

Expected output columns include:

```text
resistance_axis
resistance_axis_score
matched_resistance_programs
matched_signature_genes
resistance_axis_confidence
```

---

### 4. Stable rule-based translational role classifier

Each candidate receives a stable biological/translational role classification.

This role is calculated once and does not change depending on the ranking mode.

Possible role labels include:

* direct therapeutic target;
* anti-PD-1 combination target;
* resistance biomarker;
* patient-stratification biomarker;
* mechanistic resistance marker;
* tumor-intrinsic driver;
* immune-context marker;
* poor direct therapeutic target;
* unclear / low-confidence candidate.

Example classifications:

| Target        | Expected stable classification                              |
| ------------- | ----------------------------------------------------------- |
| LAG3          | Anti-PD-1 combination target                                |
| TIGIT         | Anti-PD-1 combination target                                |
| HAVCR2 / TIM3 | Checkpoint redundancy / exhausted T-cell combination target |
| CD274 / PD-L1 | Checkpoint axis / biomarker / therapeutic target            |
| B2M           | Antigen-presentation resistance mechanism / biomarker       |
| JAK1 / JAK2   | IFNγ resistance mechanism / biomarker                       |
| BRAF          | Tumor-intrinsic melanoma driver / small-molecule target     |
| NRAS          | Tumor-intrinsic melanoma driver                             |
| CDKN2A        | Melanoma driver/risk marker; poor direct therapeutic target |
| CSF1R         | Myeloid/TME combination target candidate                    |
| TREM2         | Myeloid/TME combination target candidate                    |
| LILRB-family  | Myeloid immune-suppression target candidates                |
| NT5E / CD73   | Metabolic immune-suppression target                         |
| ENTPD1 / CD39 | Metabolic immune-suppression target                         |
| IDO1          | Metabolic immune-suppression target                         |
| AXL / MERTK   | Tumor plasticity / resistance-associated candidate          |

This classifier explicitly distinguishes:

```text
therapeutic target ≠ biomarker ≠ resistance mechanism ≠ poor direct target
```

---

### 5. Therapeutic directionality

Therapeutic directionality is an output of the role classifier.

Possible directionality labels include:

* block / inhibit;
* activate / restore;
* deplete target-expressing suppressive cells;
* reprogram the tumor microenvironment;
* use as biomarker only;
* use for patient stratification;
* avoid as direct target;
* unclear.

Example logic:

| Target type                        | Therapeutic direction                        |
| ---------------------------------- | -------------------------------------------- |
| Immune checkpoint receptor         | Blockade / inhibition                        |
| Suppressive myeloid surface target | Blockade, depletion, or reprogramming        |
| Antigen-presentation loss gene     | Biomarker / restore pathway / stratification |
| IFNγ resistance gene               | Biomarker / stratification                   |
| Tumor-intrinsic kinase             | Small-molecule inhibition                    |
| Nuclear tumor suppressor           | Avoid as direct therapeutic target           |

---

### 6. Modality-aware reasoning

TargetIntel-IO evaluates whether each candidate fits a therapeutic modality.

Initial modality labels include:

* antibody;
* bispecific antibody;
* small molecule;
* biomarker;
* patient stratification;
* IO-combination target;
* poor direct target;
* unclear.

The modality-aware layer considers:

* antibody tractability;
* small-molecule tractability;
* known drugs;
* clinical phase;
* surface or secreted status;
* intracellular or nuclear localization;
* safety concerns;
* broad normal tissue expression;
* whether the target is likely causal or only a marker.

This prevents a common prioritization error: ranking biologically important but therapeutically inaccessible genes as if they were actionable drug targets.

Expected output columns include:

```text
antibody_fit
small_molecule_fit
biomarker_fit
io_combination_fit
poor_direct_target_flag
modality_rationale
```

---

### 7. Therapeutic-intent-aware ranking

TargetIntel-IO assigns each candidate a stable biological role, but ranks it differently depending on the therapeutic question.

The first three ranking modes are:

#### Antibody / IO-combination mode

Prioritizes:

* surface-accessible immune checkpoints;
* myeloid/TME targets;
* ligands;
* suppressive immune axes;
* anti-PD-1 combination rationale;
* antibody or bispecific tractability.

Expected high-ranking targets:

```text
LAG3, TIGIT, HAVCR2, CSF1R, TREM2, LILRB-family, NT5E
```

#### Resistance biomarker mode

Prioritizes:

* antigen-presentation loss;
* IFNγ resistance;
* IPRES/TIDE-like resistance programs;
* immune-exclusion markers;
* responder vs non-responder relevance;
* patient-stratification potential.

Expected high-ranking targets:

```text
B2M, JAK1, JAK2, HLA genes, TAP1, TAP2, AXL, WNT5A
```

#### Tumor-intrinsic / small-molecule mode

Prioritizes:

* tumor-cell drivers;
* kinases;
* oncogenic signaling pathways;
* small-molecule tractability;
* tumor-intrinsic resistance mechanisms.

Expected high-ranking targets:

```text
BRAF, MAP2K1, NRAS, AXL, MERTK, PTEN-related pathway genes
```

The key question is not:

> What is the best target?

but:

> Best candidate for what therapeutic intent?

---

### 8. Quantitative evidence density and novelty/crowding

TargetIntel-IO quantifies evidence density using simple, interpretable metrics:

* PubMed count for gene + melanoma;
* PubMed count for gene + melanoma + PD-1 / immunotherapy / resistance;
* ClinicalTrials.gov count for gene/target + melanoma;
* known-drug count from Open Targets;
* maximum clinical phase from Open Targets.

These metrics are not treated as proof of causality. Instead, they help classify whether a target is:

* established and crowded;
* clinically active;
* known but still relevant;
* emerging;
* underexplored but plausible;
* weakly supported;
* insufficiently studied.

Expected output columns include:

```text
pubmed_melanoma_count
pubmed_pd1_resistance_count
clinical_trials_count
known_drug_count
max_clinical_phase
literature_density_score
crowding_score
novelty_label
```

---

### 9. Confidence and uncertainty

TargetIntel-IO includes an explicit data-completeness and uncertainty layer.

The tool should not force every gene into a confident classification. If key evidence is missing, the output should say so.

Possible confidence labels:

* high confidence;
* medium confidence;
* low confidence;
* insufficient evidence to classify.

Expected output columns include:

```text
data_completeness_score
missing_evidence_fields
confidence_level
uncertainty_reason
```

Knowing when the tool does not know is a strength, not a weakness.

---

### 10. Evidence-for / evidence-against auditor

For every candidate, TargetIntel-IO explicitly separates supporting and opposing evidence.

Evidence supporting a candidate may include:

* melanoma disease association;
* anti-PD-1 resistance-axis relevance;
* expression in relevant tumor or immune compartments;
* surface or secreted localization;
* known tractability;
* known drugs;
* clinical-phase evidence;
* immune-suppressive function;
* combination rationale with anti-PD-1;
* high intent-specific fit.

Evidence against a candidate may include:

* intracellular or nuclear localization;
* poor antibody fit;
* broad normal tissue expression;
* essentiality or toxicity risk;
* weak resistance-specific evidence;
* being a marker of immune abundance rather than a causal target;
* lack of functional validation;
* saturated or crowded target space;
* contradictory evidence;
* unclear therapeutic directionality;
* insufficient data completeness.

This is one of the main strengths of the project: most prioritization tools explain why a target is interesting; TargetIntel-IO also explains why it may fail.

---

### 11. Target hypothesis cards

The final user-facing output is a structured target hypothesis card.

Each card includes:

* target name;
* stable role classification;
* therapeutic direction;
* resistance axis;
* best modality fit;
* intent-specific rankings;
* evidence for;
* evidence against;
* novelty/crowding estimate;
* confidence level;
* recommended next validation experiment.

Example card:

```text
Target: HAVCR2 / TIM3

Stable role:
Anti-PD-1 combination target

Therapeutic direction:
Blockade

Best modality:
Antibody / bispecific

Resistance axis:
Checkpoint redundancy / T-cell exhaustion

Intent-specific ranking:
- Antibody / IO-combination mode: high priority
- Resistance biomarker mode: medium priority
- Tumor-intrinsic small-molecule mode: low priority

Evidence for:
HAVCR2 is linked to exhausted T-cell biology and may represent a compensatory checkpoint axis in tumors with incomplete response to PD-1 blockade.

Evidence against:
The checkpoint space is crowded, patient selection may be required, and expression may reflect exhausted immune-cell abundance rather than causal resistance in every tumor.

Next experiment:
Validate TIM3 expression in CD8 T-cell subsets from anti-PD-1-resistant melanoma samples and test whether TIM3 blockade improves tumor-cell killing in a melanoma/T-cell co-culture model.

Confidence:
Medium-high
```

---

## Expected output table

The final ranked table will include columns such as:

```text
target_symbol
opentargets_score
resistance_axis_score
modality_fit_score
antibody_fit
small_molecule_fit
biomarker_fit
role_classification
therapeutic_direction
resistance_axis
evidence_for
evidence_against
safety_flags
known_drug_count
max_clinical_phase
pubmed_melanoma_count
pubmed_pd1_resistance_count
clinical_trials_count
novelty_label
crowding_score
contradiction_score
data_completeness_score
confidence_level
antibody_io_score
antibody_io_rank
biomarker_score
biomarker_rank
small_molecule_score
small_molecule_rank
next_best_experiment
```

---

## Benchmarking and validation

A validation framework is a core part of the MVP.

The project will include a benchmark of approximately 40–60 genes with literature-consensus labels across several categories:

| Category                         | Example genes                                      |
| -------------------------------- | -------------------------------------------------- |
| Checkpoint / combination targets | PDCD1, CD274, CTLA4, LAG3, TIGIT, HAVCR2           |
| Myeloid/TME targets              | CSF1R, TREM2, MARCO, LILRB1, LILRB2, LILRB3, MERTK |
| Metabolic immune suppression     | NT5E, ENTPD1, IDO1, ARG1                           |
| Antigen presentation             | B2M, HLA-A, HLA-B, HLA-C, TAP1, TAP2               |
| IFNγ resistance                  | JAK1, JAK2, IFNGR1, IFNGR2, STAT1, IRF1            |
| Tumor-intrinsic drivers          | BRAF, NRAS, MAP2K1, PTEN, CDKN2A                   |
| Plasticity / resistance programs | AXL, WNT5A, TWIST2, NGFR                           |
| TGFβ/CAF exclusion               | TGFB1, TGFBR1, TGFBR2, CXCL12, CXCR4, FAP          |

Evaluation will include:

* confusion matrix for role classification;
* agreement with expected benchmark labels;
* precision/recall for biomarker vs direct-target classification;
* rank-shift analysis compared with Open Targets-only ranking;
* checking whether checkpoint/combination targets move upward in antibody/IO mode;
* checking whether B2M/JAK1/JAK2 are classified as biomarkers/mechanisms rather than direct antibody targets;
* checking whether CDKN2A-like intracellular genes are deprioritized in antibody/IO mode;
* checking whether tumor-intrinsic drivers move upward in small-molecule mode;
* checking whether resistance biomarkers move upward in biomarker mode;
* YAML weight sensitivity analysis;
* top-10 stability across scoring configurations.

---

## Dashboard

The final MVP will include a Streamlit dashboard.

The dashboard will allow users to:

* select therapeutic intent mode;
* view ranked targets;
* compare Open Targets-only rank vs TargetIntel-IO rank;
* inspect score components;
* view role classification;
* view evidence for and evidence against;
* view confidence and missing evidence;
* open target hypothesis cards;
* compare ranks across therapeutic modes.

Planned figures:

1. **Rank-shift plot vs Open Targets baseline**
2. **Therapeutic-intent rank heatmap**
3. **Score component barplot**
4. **Benchmark confusion matrix**
5. **Top target evidence table**

---

## Repository structure

Planned structure:

```text
TargetIntel/
├── README.md
├── environment.yml
├── pyproject.toml
├── Dockerfile
├── configs/
│   ├── disease_context.yaml
│   ├── resistance_axes.yaml
│   ├── scoring_antibody_io.yaml
│   ├── scoring_biomarker.yaml
│   └── scoring_small_molecule.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   ├── benchmark/
│   └── cache/
├── targetintel/
│   ├── __init__.py
│   ├── opentargets.py
│   ├── cache.py
│   ├── resistance_ontology.py
│   ├── evidence_counts.py
│   ├── role_classifier.py
│   ├── scoring.py
│   ├── intent_ranking.py
│   ├── evidence_auditor.py
│   ├── confidence.py
│   ├── hypothesis_cards.py
│   ├── benchmark.py
│   └── plotting.py
├── scripts/
│   ├── 01_fetch_opentargets.py
│   ├── 02_fetch_evidence_counts.py
│   ├── 03_build_feature_table.py
│   ├── 04_score_targets.py
│   ├── 05_generate_cards.py
│   └── 06_run_benchmark.py
├── notebooks/
│   ├── 01_exploratory_analysis.ipynb
│   └── 02_benchmark_results.ipynb
├── app/
│   └── streamlit_app.py
├── results/
│   ├── ranked_targets.csv
│   ├── target_cards/
│   └── benchmark_report.csv
└── figures/
    ├── rank_shift_vs_opentargets.png
    ├── therapeutic_intent_rank_heatmap.png
    ├── score_components_top_targets.png
    └── benchmark_confusion_matrix.png
```

---

## Current status

This project is under active development.

### Completed

* Initial project concept defined.
* First Open Targets-based melanoma prioritization prototype created.
* Initial IO relevance weighting explored.
* First ranked target table and exploratory figures generated.

### In progress

* Refactoring project from generic target prioritization to TargetIntel-IO.
* Adding caching and reproducible API ingestion.
* Building anti-PD-1 resistance ontology.
* Implementing stable translational role classification.
* Implementing therapeutic-intent-aware scoring profiles.

### Planned MVP milestones

#### v0.1 — Foundation

* [ ] Refactor project structure.
* [ ] Add API caching.
* [ ] Build reproducible Open Targets ingestion.
* [ ] Create anti-PD-1 resistance ontology.
* [ ] Generate first feature table.

#### v0.2 — Translational classification

* [ ] Add stable rule-based role classifier.
* [ ] Add therapeutic directionality.
* [ ] Add modality-aware reasoning.
* [ ] Add evidence-for and evidence-against fields.
* [ ] Add confidence and uncertainty flags.

#### v0.3 — Therapeutic-intent-aware ranking

* [ ] Add antibody / IO-combination scoring profile.
* [ ] Add resistance biomarker scoring profile.
* [ ] Add tumor-intrinsic / small-molecule scoring profile.
* [ ] Generate rank-shift analysis versus Open Targets baseline.
* [ ] Generate target hypothesis cards.

#### v0.4 — Benchmarking

* [ ] Build 40–60 gene benchmark set.
* [ ] Evaluate role-classifier agreement.
* [ ] Generate confusion matrix.
* [ ] Run score sensitivity analysis.
* [ ] Assess top-10 stability across scoring profiles.

#### v0.5 — Dashboard and documentation

* [ ] Build Streamlit dashboard.
* [ ] Add therapeutic intent selector.
* [ ] Display ranked targets, evidence, confidence, and target cards.
* [ ] Add visual outputs.
* [ ] Polish documentation and limitations.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/rsolerortuno/TargetIntel.git
cd TargetIntel
```

Create the conda environment:

```bash
conda env create -f environment.yml
conda activate targetintel
```

Alternatively, install dependencies with pip if a `requirements.txt` file is provided:

```bash
pip install -r requirements.txt
```

---

## Usage

The current prototype can be run from the command line or notebooks as the project evolves.

Planned workflow:

```bash
python scripts/01_fetch_opentargets.py
python scripts/02_fetch_evidence_counts.py
python scripts/03_build_feature_table.py
python scripts/04_score_targets.py
python scripts/05_generate_cards.py
python scripts/06_run_benchmark.py
```

Expected main outputs:

```text
data/processed/targetintel_feature_table.csv
results/ranked_targets.csv
results/target_cards/
results/benchmark_report.csv
figures/
```

---

## Data sources

TargetIntel-IO is designed to use public data only.

Initial and planned sources include:

* Open Targets Platform;
* PubMed / NCBI E-utilities;
* ClinicalTrials.gov;
* curated anti-PD-1 resistance gene sets;
* optional future public melanoma single-cell or spatial datasets.

No confidential, proprietary, clinical, or company-internal data is included.

---

## Optional future extensions

The following features are intentionally postponed until after the core MVP:

* STRING first-neighbor resistance-axis overlap;
* melanoma single-cell case study;
* spatial transcriptomics case study;
* DepMap/CRISPR dependency evidence;
* source-grounded LLM evidence synthesis using PMID-cited abstracts;
* BioNeMo or protein-embedding demonstration;
* lightweight network-context analysis;
* GitHub Pages or Quarto project website;
* Dockerized demo;
* JOSS-style software paper.

These are future extensions, not core claims of the current MVP.

---

## Limitations

TargetIntel-IO is a transparent hypothesis-generation and target-triage
framework. It does not provide clinical recommendations, validated therapeutic
targets, biomarker qualification, or medical advice.

### External evidence retrieval

- Only **25/56 (44.6%)**
  benchmark targets appeared among the top 300 melanoma associations retrieved
  from Open Targets.
- The remaining **31 targets** were added explicitly to
  the augmented benchmark universe with no retrieved Open Targets evidence.
- Therefore, **56/56
  (100%) TargetIntel evaluation coverage** means that the
  software evaluated every curated benchmark target. It does not mean that
  Open Targets independently recovered every target.

### Internal benchmark interpretation

- The benchmark produced **100.0% stable-role accuracy**, but the
  expected roles were curated using the same biological and translational
  framework represented by the implemented rules. This measures implementation
  consistency, not independent biological accuracy.
- Strict primary-intent accuracy was
  **91.1%
  (51/56)**, with
  **5 strict disagreements**.
- Acceptable-intent accuracy was **100.0%** because
  predefined therapeutically plausible alternative intents were accepted.
  This should not be interpreted as prospective predictive performance.
- Mean recall across the therapeutic-intent profiles was
  **58.1% at top 10** and
  **79.5% at top 20**. Consequently, not every curated positive
  target is placed near the top of its expected ranking.

See the
[versioned benchmark snapshot](examples/benchmark/README.md)
for the complete metrics and per-target predictions.

### Weight sensitivity

- The local sensitivity analysis evaluated **42 scenarios** in
  which one scoring weight was changed by `-20%` or `+20%` and all weights were
  subsequently renormalized.
- All profiles retained 100% of their baseline top 5.
- Worst-case top-10 retention was: **antibody/IO 90%, biomarker 100%, small-molecule 90%**.
- Worst-case top-20 retention was: **antibody/IO 100%, biomarker 95%, small-molecule 100%**.
- The minimum observed Spearman rank correlation was
  **0.9852**.
- The maximum observed change in strict or acceptable benchmark-intent accuracy
  was **0.0000**.

These results support local robustness to moderate changes in individual
weights. They do not establish that the rankings are independent of weight
selection. The analysis does not test simultaneous changes to multiple weights,
perturbations larger than 20%, alternative scoring functions, or uncertainty in
the curated biological rules.

See the
[versioned sensitivity snapshot](examples/sensitivity/README.md)
for all scenarios and per-target rank changes.

### Biological and generalizability limitations

- The resistance axes, therapeutic roles, directions, and acceptable intents
  are manually curated and may encode expert assumptions.
- The current implementation is specific to anti-PD-1-resistant melanoma and
  has not yet demonstrated equivalent performance in another disease context.
- The benchmark is internally curated rather than derived from an independent,
  blinded, prospective, or clinical dataset.
- No external patient-level responder/non-responder cohort is currently used to
  validate target rankings.
- Public association evidence does not establish causality, therapeutic
  tractability, safety, clinical benefit, or successful combination with
  anti-PD-1 therapy.
- Large rank changes can occur among low-scoring or tied targets near the bottom
  of a ranking, even when the prioritized top targets remain stable.

All generated hypotheses require independent experimental, translational, and
clinical validation.

## Tech stack

Planned tools and libraries include:

* Python;
* pandas;
* numpy;
* requests;
* PyYAML;
* scikit-learn;
* matplotlib;
* seaborn;
* Streamlit;
* Open Targets GraphQL API;
* NCBI E-utilities;
* ClinicalTrials.gov API.

---

## Author

**Rafael Soler Ortuño**

Computational Biologist focused on immuno-oncology, biomarker discovery, patient stratification, single-cell/spatial transcriptomics, and AI-assisted drug discovery.

LinkedIn: https://www.linkedin.com/in/rafael-soler-ortuno/

---

## License

This project is released under the MIT License.

---

## Citation

A citation file will be added in a future release.

```text
TargetIntel-IO: Explainable therapeutic-intent-aware target triage for anti-PD-1-resistant melanoma.
```

## Internal therapeutic-intent benchmark

TargetIntel-IO includes a curated 56-target benchmark for internal,
rule-based sanity validation across three therapeutic intents:

- antibody and immuno-oncology combination targets;
- biomarkers and resistance mechanisms;
- small-molecule intervention targets.

The benchmark target universe combines the top melanoma-associated targets
retrieved from Open Targets with all curated benchmark genes. This separates
external retrieval coverage from TargetIntel-IO evaluation coverage.

### Current benchmark results

| Metric | Result |
|---|---:|
| Benchmark targets evaluated | 56 / 56 |
| TargetIntel evaluation coverage | 100% |
| Open Targets top-300 retrieval coverage | 44.6% |
| Stable-role accuracy | 100% |
| Strict primary-intent accuracy | 91.1% |
| Acceptable-intent accuracy | 100% |
| Cross-intent specificity | 90.6% |
| Control not-prioritized rate | 100% |
| Mean top-10 recall | 58.1% |
| Mean top-20 recall | 79.5% |

The five strict intent disagreements are therapeutically plausible alternative
interpretations accepted by the benchmark:

- `FOXP3`: biomarker instead of antibody/IO;
- `MITF` and `TERT`: small-molecule or pathway intervention instead of biomarker;
- `CXCR4` and `TGFBR1`: antibody/IO instead of small molecule.

These results demonstrate consistency between the curated reasoning rules and
the expected therapeutic-intent categories. They do not constitute independent
clinical validation or evidence of therapeutic efficacy.

A versioned benchmark-output snapshot is available in [`examples/benchmark/`](examples/benchmark/README.md).

A versioned weight-sensitivity snapshot is available in [`examples/sensitivity/`](examples/sensitivity/README.md).

### Run the benchmark

Build the augmented benchmark universe:

~~~bash
python scripts/09_build_benchmark_universe.py \
  --page-size 100 \
  --max-pages 3
~~~

Run the benchmark:

~~~bash
python scripts/08_run_benchmark.py \
  --input results/benchmark/ranked_targets_benchmark_universe.csv \
  --config configs/benchmark_targets.yaml \
  --outdir results/benchmark \
  --show-missing \
  --show-errors
~~~

### Continuous integration

The GitHub Actions workflow validates package imports, Python syntax, YAML
configurations, and unit tests on every push and pull request to `main`.
