# TargetIntel-IO Agent Instructions

## Project purpose

TargetIntel-IO is a transparent and deterministic framework for classifying
and prioritizing targets in anti-PD-1-resistant melanoma according to
therapeutic intent.

It is a hypothesis-generation and target-triage framework. It does not
provide validated therapeutic targets, clinical recommendations, biomarker
qualification, or medical advice.

## Repository structure

- `targetintel/`: reusable Python package and CLI.
- `configs/`: biological rules, resistance axes, benchmarks, and scoring.
- `tests/`: unit, integration, and regression tests.
- `scripts/`: individual workflows and snapshot utilities.
- `examples/`: versioned example reports and validation outputs.
- `data/`: local cached and processed data; normally not committed.
- `results/`: generated local outputs; normally not committed.

## Non-negotiable scientific rules

1. Never invent biological evidence, numerical values, references, API
   responses, clinical findings, or citations.
2. Never describe an association as proof of causality.
3. Never describe the internal benchmark as independent biological or
   clinical validation.
4. Never change scoring weights, expected benchmark labels, resistance
   ontology, stable-role rules, or therapeutic directionality unless the
   task explicitly requests that specific scientific change.
5. Preserve the distinction between:
   therapeutic target, biomarker, resistance mechanism, immune-context
   marker, tumor-intrinsic driver, and poor direct target.
6. Preserve evidence provenance, source identifiers, release information,
   retrieval dates, cache behavior, and transformation history.
7. Missing evidence must not automatically be interpreted as negative
   evidence.
8. Retrieved evidence and LLM-generated interpretation must remain separate.
9. Any future LLM layer must be optional and must not silently alter the
   deterministic baseline rankings.
10. Stop and report uncertainty when a biological, clinical, or
    translational judgment is not specified.

## Engineering workflow

1. Read `README.md`, `pyproject.toml`, relevant configuration files, and
   existing tests before changing code.
2. Work only on a dedicated Git branch or worktree.
3. Keep changes limited to the assigned task.
4. Do not modify unrelated files.
5. Add or update tests for every behavior change.
6. Preserve backward compatibility unless the task explicitly permits a
   breaking change.
7. Do not commit secrets, API keys, `.env` files, local caches, generated
   results, confidential data, or identifiable patient-level data.
8. Do not push, merge, rewrite history, delete branches, or publish releases
   unless explicitly instructed.
9. Summarize assumptions, changed files, test results, and remaining risks
   before finishing.

## Required verification

For normal changes:

    python -m pytest tests -q

For changes affecting scoring, classification, configuration, outputs,
benchmarking, or the complete workflow:

    targetintel run --validate

Before completion:

    git status
    git diff --check
    git diff --stat

A task is not complete merely because code was written. Relevant tests must
pass, or the exact failure and likely cause must be reported.
