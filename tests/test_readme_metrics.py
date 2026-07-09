"""Regression tests for quantitative claims in the main README."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


README_PATH = Path("README.md")
BENCHMARK_PATH = Path(
    "examples/benchmark/benchmark_summary.json"
)
SENSITIVITY_SUMMARY_PATH = Path(
    "examples/sensitivity/sensitivity_summary.csv"
)
SENSITIVITY_METRICS_PATH = Path(
    "examples/sensitivity/sensitivity_metrics.json"
)


def test_readme_benchmark_limitations_match_snapshot() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    benchmark = json.loads(
        BENCHMARK_PATH.read_text(
            encoding="utf-8"
        )
    )

    total = int(
        benchmark["total_benchmark_targets"]
    )

    retrieved = int(
        benchmark[
            "opentargets_retrieved_benchmark_targets"
        ]
    )

    retrieval_coverage = float(
        benchmark[
            "opentargets_retrieval_coverage"
        ]
    )

    role_accuracy = float(
        benchmark["role_accuracy_covered"]
    )

    strict_accuracy = float(
        benchmark[
            "primary_intent_accuracy_covered"
        ]
    )

    acceptable_accuracy = float(
        benchmark[
            "acceptable_intent_accuracy_covered"
        ]
    )

    assert (
        f"**{retrieved}/{total} "
        f"({retrieval_coverage:.1%})**"
        in readme
    )

    assert (
        f"**{role_accuracy:.1%} "
        "stable-role accuracy**"
        in readme
    )

    assert (
        f"**{strict_accuracy:.1%}"
        in readme
    )

    assert (
        f"**{acceptable_accuracy:.1%}**"
        in readme
    )


def test_readme_sensitivity_limitations_match_snapshot() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    summary = pd.read_csv(
        SENSITIVITY_SUMMARY_PATH
    )

    metrics = json.loads(
        SENSITIVITY_METRICS_PATH.read_text(
            encoding="utf-8"
        )
    )

    scenario_count = int(
        metrics["scenario_count"]
    )

    minimum_spearman = float(
        summary["minimum_spearman"].min()
    )

    assert (
        f"**{scenario_count} scenarios**"
        in readme
    )

    assert (
        f"**{minimum_spearman:.4f}**"
        in readme
    )

    assert (
        "All profiles retained 100% "
        "of their baseline top 5."
        in readme
    )


def test_readme_distinguishes_internal_from_external_validation() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    normalized_readme = " ".join(
        readme.split()
    )

    required_statements = [
        "implementation consistency, not independent biological accuracy",
        "does not mean that Open Targets independently recovered every target",
        "not derived from an independent",
        "No external patient-level responder/non-responder cohort",
        "require independent experimental, translational, and clinical validation",
    ]

    for statement in required_statements:
        normalized_statement = " ".join(
            statement.split()
        )

        assert normalized_statement in normalized_readme
