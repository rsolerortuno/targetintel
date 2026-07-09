"""Regression tests for the committed benchmark-result snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from targetintel.benchmark import (
    benchmark_config_to_dataframe,
    load_benchmark_config,
)


SNAPSHOT_DIR = Path("examples/benchmark")
CONFIG_PATH = Path("configs/benchmark_targets.yaml")

EXPECTED_SNAPSHOT_FILES = {
    "benchmark_predictions.csv",
    "benchmark_summary.csv",
    "benchmark_summary.json",
    "intent_metrics.csv",
    "role_confusion_matrix.csv",
    "snapshot_manifest.json",
    "README.md",
}

EXPECTED_INTENTS = {
    "antibody_io",
    "biomarker",
    "small_molecule",
    "none",
}


def _sha256(path: Path) -> str:
    """Calculate the SHA-256 digest of a file."""
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _read_summary() -> dict[str, object]:
    """Read the committed benchmark summary."""
    summary_path = SNAPSHOT_DIR / "benchmark_summary.json"

    return json.loads(
        summary_path.read_text(encoding="utf-8")
    )


def test_snapshot_contains_expected_files() -> None:
    """All public benchmark snapshot files must be present."""
    actual_files = {
        path.name
        for path in SNAPSHOT_DIR.iterdir()
        if path.is_file()
    }

    assert EXPECTED_SNAPSHOT_FILES <= actual_files


def test_snapshot_predictions_match_benchmark_config() -> None:
    """The snapshot must contain every configured benchmark target once."""
    benchmark_config = load_benchmark_config(CONFIG_PATH)
    reference_df = benchmark_config_to_dataframe(
        benchmark_config
    )

    predictions = pd.read_csv(
        SNAPSHOT_DIR / "benchmark_predictions.csv"
    )

    expected_symbols = set(
        reference_df["target_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    predicted_symbols = set(
        predictions["target_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    assert len(reference_df) == 56
    assert reference_df["target_symbol"].nunique() == 56

    assert len(predictions) == 56
    assert predictions["target_symbol"].nunique() == 56

    assert predicted_symbols == expected_symbols


def test_snapshot_has_complete_evaluation_coverage() -> None:
    """Every benchmark target must have a TargetIntel prediction."""
    predictions = pd.read_csv(
        SNAPSHOT_DIR / "benchmark_predictions.csv"
    )

    assert "prediction_available" in predictions.columns

    prediction_available = (
        predictions["prediction_available"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "y"})
    )

    assert prediction_available.all()


def test_snapshot_summary_metrics_remain_valid() -> None:
    """Core benchmark quality metrics must not regress silently."""
    summary = _read_summary()

    assert summary["total_benchmark_targets"] == 56
    assert summary["covered_benchmark_targets"] == 56
    assert summary["missing_benchmark_targets"] == 0

    assert summary["targetintel_evaluation_coverage"] == pytest.approx(
        1.0
    )

    assert summary["opentargets_retrieved_benchmark_targets"] == 25

    assert summary["opentargets_retrieval_coverage"] == pytest.approx(
        25 / 56,
        abs=1e-4,
    )

    assert summary["role_accuracy_covered"] == pytest.approx(
        1.0
    )

    assert summary["role_macro_f1_covered"] == pytest.approx(
        1.0
    )

    assert summary[
        "primary_intent_accuracy_covered"
    ] >= 0.90

    assert summary[
        "primary_intent_macro_f1_covered"
    ] >= 0.90

    assert summary[
        "acceptable_intent_accuracy_covered"
    ] == pytest.approx(1.0)

    assert summary[
        "cross_intent_specificity_covered"
    ] >= 0.90

    assert summary[
        "control_not_prioritized_rate_covered"
    ] == pytest.approx(1.0)

    assert summary[
        "mean_mode_top_10_recall_covered"
    ] >= 0.55

    assert summary[
        "mean_mode_top_20_recall_covered"
    ] >= 0.75


def test_snapshot_intent_metrics_are_complete() -> None:
    """Intent metrics must cover the three modes and controls."""
    intent_metrics = pd.read_csv(
        SNAPSHOT_DIR / "intent_metrics.csv"
    )

    assert set(intent_metrics["intent"]) == EXPECTED_INTENTS

    target_counts = dict(
        zip(
            intent_metrics["intent"],
            intent_metrics["expected_target_count"],
            strict=True,
        )
    )

    assert target_counts == {
        "antibody_io": 19,
        "biomarker": 24,
        "small_molecule": 10,
        "none": 3,
    }

    evaluated_counts = dict(
        zip(
            intent_metrics["intent"],
            intent_metrics["covered_target_count"],
            strict=True,
        )
    )

    assert evaluated_counts == target_counts


def test_snapshot_role_confusion_matrix_is_perfect() -> None:
    """The stable-role confusion matrix must contain no off-diagonal errors."""
    matrix = pd.read_csv(
        SNAPSHOT_DIR / "role_confusion_matrix.csv",
        index_col=0,
    )

    numeric_matrix = matrix.apply(
        pd.to_numeric,
        errors="raise",
    )

    off_diagonal_total = 0

    for row_label in numeric_matrix.index:
        for column_label in numeric_matrix.columns:
            if row_label != column_label:
                off_diagonal_total += int(
                    numeric_matrix.loc[
                        row_label,
                        column_label,
                    ]
                )

    assert off_diagonal_total == 0
    assert int(numeric_matrix.to_numpy().sum()) == 56


def test_snapshot_manifest_hashes_are_current() -> None:
    """Manifest hashes must match the committed result files."""
    manifest_path = (
        SNAPSHOT_DIR / "snapshot_manifest.json"
    )

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )

    assert manifest["benchmark_id"] == (
        "targetintel_io_internal_v0_1"
    )

    assert manifest["benchmark_version"] == "0.1.0"

    assert manifest["benchmark_config"] == (
        "configs/benchmark_targets.yaml"
    )

    manifest_files = manifest["files"]

    expected_hashed_files = {
        "benchmark_predictions.csv",
        "benchmark_summary.csv",
        "benchmark_summary.json",
        "intent_metrics.csv",
        "role_confusion_matrix.csv",
    }

    assert set(manifest_files) == expected_hashed_files

    for filename, metadata in manifest_files.items():
        path = SNAPSHOT_DIR / filename

        assert path.exists()
        assert path.stat().st_size == metadata["size_bytes"]
        assert _sha256(path) == metadata["sha256"]
