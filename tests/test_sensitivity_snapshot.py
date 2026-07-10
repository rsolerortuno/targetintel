"""Regression tests for the committed sensitivity-analysis snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest


SNAPSHOT_DIR = Path("examples/sensitivity")
BENCHMARK_SUMMARY_PATH = Path(
    "examples/benchmark/benchmark_summary.json"
)

EXPECTED_FILES = {
    "README.md",
    "sensitivity_scenarios.csv",
    "sensitivity_summary.csv",
    "sensitivity_by_weight.csv",
    "target_rank_stability.csv",
    "sensitivity_metrics.json",
    "sensitivity_overview.png",
    "snapshot_manifest.json",
}

EXPECTED_PROFILES = {
    "antibody_io",
    "biomarker",
    "small_molecule",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _equivalent(
    left: Any,
    right: Any,
    tolerance: float = 1e-4,
) -> bool:
    if (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
    ):
        return abs(
            float(left) - float(right)
        ) <= tolerance

    return left == right


def test_snapshot_contains_expected_files() -> None:
    actual_files = {
        path.name
        for path in SNAPSHOT_DIR.iterdir()
        if path.is_file()
    }

    assert EXPECTED_FILES <= actual_files


def test_sensitivity_snapshot_has_expected_scenarios() -> None:
    scenarios = pd.read_csv(
        SNAPSHOT_DIR / "sensitivity_scenarios.csv"
    )

    assert len(scenarios) == 42
    assert set(
        scenarios["perturbed_profile"]
    ) == EXPECTED_PROFILES

    counts = (
        scenarios["perturbed_profile"]
        .value_counts()
        .to_dict()
    )

    assert counts == {
        "antibody_io": 14,
        "biomarker": 14,
        "small_molecule": 14,
    }

    assert set(
        scenarios["direction"]
    ) == {
        "minus",
        "plus",
    }

    assert set(
        scenarios["perturbation_fraction"]
    ) == {
        0.20,
    }


def test_corrected_profile_stability_metrics() -> None:
    summary = (
        pd.read_csv(
            SNAPSHOT_DIR / "sensitivity_summary.csv"
        )
        .set_index("profile_id")
    )

    assert set(summary.index) == EXPECTED_PROFILES

    expected = {
        "antibody_io": {
            "minimum_spearman": 1.0000,
            "minimum_top_5_retention": 1.00,
            "minimum_top_10_retention": 0.90,
            "minimum_top_20_retention": 1.00,
        },
        "biomarker": {
            "minimum_spearman": 1.0000,
            "minimum_top_5_retention": 1.00,
            "minimum_top_10_retention": 1.00,
            "minimum_top_20_retention": 0.95,
        },
        "small_molecule": {
            "minimum_spearman": 0.8762,
            "minimum_top_5_retention": 0.80,
            "minimum_top_10_retention": 0.90,
            "minimum_top_20_retention": 1.00,
        },
    }

    for profile_id, metrics in expected.items():
        for metric, expected_value in metrics.items():
            assert (
                summary.loc[
                    profile_id,
                    metric,
                ]
                == pytest.approx(
                    expected_value,
                    abs=1e-4,
                )
            )


def test_corrected_benchmark_metric_deltas() -> None:
    summary = pd.read_csv(
        SNAPSHOT_DIR / "sensitivity_summary.csv"
    )

    assert (
        summary[
            "maximum_absolute_primary_intent_accuracy_delta"
        ].max()
        == pytest.approx(
            0.0536,
            abs=1e-4,
        )
    )

    assert (
        summary[
            "maximum_absolute_acceptable_intent_accuracy_delta"
        ].max()
        == pytest.approx(
            0.0357,
            abs=1e-4,
        )
    )

    assert (
        summary[
            "maximum_absolute_cross_intent_specificity_delta"
        ].max()
        == pytest.approx(
            0.0566,
            abs=1e-4,
        )
    )


def test_sensitivity_baseline_matches_official_benchmark() -> None:
    benchmark = json.loads(
        BENCHMARK_SUMMARY_PATH.read_text(
            encoding="utf-8"
        )
    )

    metrics = json.loads(
        (
            SNAPSHOT_DIR / "sensitivity_metrics.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    baseline = metrics[
        "baseline_benchmark_summary"
    ]

    assert set(baseline) == set(benchmark)

    differences = {
        key: (
            benchmark[key],
            baseline[key],
        )
        for key in benchmark
        if not _equivalent(
            benchmark[key],
            baseline[key],
        )
    }

    assert differences == {}


def test_metrics_metadata_is_consistent() -> None:
    metrics = json.loads(
        (
            SNAPSHOT_DIR / "sensitivity_metrics.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert metrics["analysis_id"] == (
        "targetintel_weight_sensitivity_v0_1"
    )
    assert metrics["analysis_type"] == (
        "one_weight_at_a_time"
    )
    assert metrics[
        "perturbation_fraction"
    ] == pytest.approx(0.20)
    assert metrics["scenario_count"] == 42
    assert metrics["target_count"] == 331
    assert set(
        metrics["profiles"]
    ) == EXPECTED_PROFILES
    assert metrics["top_k_values"] == [
        5,
        10,
        20,
    ]


def test_snapshot_figure_is_non_empty() -> None:
    figure_path = (
        SNAPSHOT_DIR / "sensitivity_overview.png"
    )

    assert figure_path.is_file()
    assert figure_path.stat().st_size > 10_000


def test_snapshot_manifest_hashes_are_current() -> None:
    manifest = json.loads(
        (
            SNAPSHOT_DIR / "snapshot_manifest.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    expected_hashed_files = {
        "sensitivity_scenarios.csv",
        "sensitivity_summary.csv",
        "sensitivity_by_weight.csv",
        "target_rank_stability.csv",
        "sensitivity_metrics.json",
        "sensitivity_overview.png",
    }

    assert set(
        manifest["files"]
    ) == expected_hashed_files
    assert manifest["scenario_count"] == 42
    assert manifest[
        "perturbation_fraction"
    ] == pytest.approx(0.20)
    assert manifest[
        "corrected_in_release"
    ] == "0.1.2"

    for filename, metadata in manifest[
        "files"
    ].items():
        path = SNAPSHOT_DIR / filename

        assert path.is_file()
        assert (
            path.stat().st_size
            == metadata["size_bytes"]
        )
        assert (
            _sha256(path)
            == metadata["sha256"]
        )
