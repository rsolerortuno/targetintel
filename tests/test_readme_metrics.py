"""Regression tests for quantitative claims in the main README."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


README_PATH = Path("README.md")
BENCHMARK_PATH = Path("examples/benchmark/benchmark_summary.json")
SENSITIVITY_SUMMARY_PATH = Path(
    "examples/sensitivity/sensitivity_summary.csv"
)
SENSITIVITY_METRICS_PATH = Path(
    "examples/sensitivity/sensitivity_metrics.json"
)


def _normalized_readme() -> str:
    return " ".join(
        README_PATH.read_text(
            encoding="utf-8"
        ).split()
    )


def test_readme_benchmark_limitations_match_snapshot() -> None:
    readme = _normalized_readme()

    benchmark = json.loads(
        BENCHMARK_PATH.read_text(
            encoding="utf-8"
        )
    )

    total = int(benchmark["total_benchmark_targets"])
    retrieved = int(
        benchmark["opentargets_retrieved_benchmark_targets"]
    )
    retrieval_coverage = float(
        benchmark["opentargets_retrieval_coverage"]
    )
    role_accuracy = float(
        benchmark["role_accuracy_covered"]
    )
    strict_accuracy = float(
        benchmark["primary_intent_accuracy_covered"]
    )
    acceptable_accuracy = float(
        benchmark["acceptable_intent_accuracy_covered"]
    )

    assert (
        f"**{retrieved}/{total} "
        f"({retrieval_coverage:.1%})**"
        in readme
    )
    assert (
        f"**{role_accuracy:.1%} stable-role accuracy**"
        in readme
    )
    assert f"**{strict_accuracy:.1%}" in readme
    assert f"**{acceptable_accuracy:.1%}**" in readme


def test_readme_sensitivity_limitations_match_snapshot() -> None:
    readme = _normalized_readme()

    summary = (
        pd.read_csv(SENSITIVITY_SUMMARY_PATH)
        .set_index("profile_id")
    )

    metrics = json.loads(
        SENSITIVITY_METRICS_PATH.read_text(
            encoding="utf-8"
        )
    )

    scenario_count = int(metrics["scenario_count"])
    assert f"**{scenario_count} scenarios**" in readme

    expected_top_5 = (
        "Worst-case top-5 retention was: "
        f"**antibody/IO "
        f"{summary.loc['antibody_io', 'minimum_top_5_retention']:.0%}, "
        f"biomarker "
        f"{summary.loc['biomarker', 'minimum_top_5_retention']:.0%}, "
        f"small-molecule "
        f"{summary.loc['small_molecule', 'minimum_top_5_retention']:.0%}**."
    )

    expected_top_10 = (
        "Worst-case top-10 retention was: "
        f"**antibody/IO "
        f"{summary.loc['antibody_io', 'minimum_top_10_retention']:.0%}, "
        f"biomarker "
        f"{summary.loc['biomarker', 'minimum_top_10_retention']:.0%}, "
        f"small-molecule "
        f"{summary.loc['small_molecule', 'minimum_top_10_retention']:.0%}**."
    )

    expected_top_20 = (
        "Worst-case top-20 retention was: "
        f"**antibody/IO "
        f"{summary.loc['antibody_io', 'minimum_top_20_retention']:.0%}, "
        f"biomarker "
        f"{summary.loc['biomarker', 'minimum_top_20_retention']:.0%}, "
        f"small-molecule "
        f"{summary.loc['small_molecule', 'minimum_top_20_retention']:.0%}**."
    )

    assert expected_top_5 in readme
    assert expected_top_10 in readme
    assert expected_top_20 in readme

    minimum_spearman = float(
        summary["minimum_spearman"].min()
    )
    maximum_primary_delta = float(
        summary[
            "maximum_absolute_primary_intent_accuracy_delta"
        ].max()
    )
    maximum_acceptable_delta = float(
        summary[
            "maximum_absolute_acceptable_intent_accuracy_delta"
        ].max()
    )
    maximum_specificity_delta = float(
        summary[
            "maximum_absolute_cross_intent_specificity_delta"
        ].max()
    )

    assert f"**{minimum_spearman:.4f}**" in readme
    assert (
        f"**{maximum_primary_delta * 100:.2f} percentage points**"
        in readme
    )
    assert (
        f"**{maximum_acceptable_delta * 100:.2f} percentage points**"
        in readme
    )
    assert (
        f"**{maximum_specificity_delta * 100:.2f} percentage points**"
        in readme
    )


def test_readme_distinguishes_internal_from_external_validation() -> None:
    readme = _normalized_readme()

    required_statements = [
        (
            "implementation consistency, not "
            "independent biological accuracy"
        ),
        (
            "does not mean that Open Targets "
            "independently recovered every target"
        ),
        (
            "internally curated rather than "
            "derived from an independent"
        ),
        (
            "No external patient-level "
            "responder/non-responder cohort"
        ),
        (
            "require independent experimental, "
            "translational, and clinical validation"
        ),
    ]

    for statement in required_statements:
        assert " ".join(statement.split()) in readme
