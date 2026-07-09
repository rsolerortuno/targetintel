"""Unit tests for scoring-weight sensitivity analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from targetintel.sensitivity import (
    SensitivityAnalysis,
    _rank_metrics,
    load_scoring_configs,
    normalize_weights,
    perturb_config_weight,
    prepare_feature_dataframe,
    save_sensitivity_results,
)


def test_normalize_weights_sum_to_one() -> None:
    weights = normalize_weights(
        {
            "feature_a": 2.0,
            "feature_b": 1.0,
            "feature_c": 1.0,
        }
    )

    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["feature_a"] == pytest.approx(0.50)
    assert weights["feature_b"] == pytest.approx(0.25)
    assert weights["feature_c"] == pytest.approx(0.25)


@pytest.mark.parametrize(
    "weights",
    [
        {},
        {"feature_a": 0.0, "feature_b": 0.0},
        {"feature_a": -0.5, "feature_b": 1.5},
        {"feature_a": "invalid", "feature_b": 1.0},
    ],
)
def test_normalize_weights_rejects_invalid_values(
    weights: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        normalize_weights(weights)


def test_perturb_config_weight_changes_only_requested_weight() -> None:
    config = {
        "scoring_profile": {
            "id": "test_profile",
        },
        "weights": {
            "feature_a": 0.50,
            "feature_b": 0.30,
            "feature_c": 0.20,
        },
        "other_setting": {
            "value": 123,
        },
    }

    perturbed, normalized = perturb_config_weight(
        config,
        weight_name="feature_b",
        multiplier=1.20,
    )

    expected_total = 0.50 + (0.30 * 1.20) + 0.20

    assert normalized["feature_a"] == pytest.approx(
        0.50 / expected_total
    )
    assert normalized["feature_b"] == pytest.approx(
        0.36 / expected_total
    )
    assert normalized["feature_c"] == pytest.approx(
        0.20 / expected_total
    )

    assert sum(normalized.values()) == pytest.approx(1.0)

    assert config["weights"]["feature_b"] == pytest.approx(0.30)
    assert perturbed["other_setting"] == config["other_setting"]


def test_perturb_config_weight_rejects_unknown_weight() -> None:
    config = {
        "weights": {
            "feature_a": 1.0,
        }
    }

    with pytest.raises(KeyError):
        perturb_config_weight(
            config,
            weight_name="unknown_feature",
            multiplier=1.20,
        )


@pytest.mark.parametrize(
    "multiplier",
    [0.0, -0.5],
)
def test_perturb_config_weight_rejects_invalid_multiplier(
    multiplier: float,
) -> None:
    config = {
        "weights": {
            "feature_a": 1.0,
        }
    }

    with pytest.raises(ValueError):
        perturb_config_weight(
            config,
            weight_name="feature_a",
            multiplier=multiplier,
        )


def test_prepare_feature_dataframe_removes_generated_columns() -> None:
    input_df = pd.DataFrame(
        {
            "target_symbol": [
                " braf ",
                "ctla4",
            ],
            "opentargets_score": [
                0.85,
                0.60,
            ],
            "role_classification": [
                "tumor-intrinsic driver / small-molecule target",
                "anti-PD-1 combination target",
            ],
            "opentargets_rank": [
                1,
                2,
            ],
            "antibody_io_final_score": [
                0.10,
                0.90,
            ],
            "antibody_io_rank": [
                2,
                1,
            ],
            "biomarker_final_score": [
                0.20,
                0.30,
            ],
            "small_molecule_final_score": [
                0.90,
                0.10,
            ],
            "custom_input_feature": [
                1.0,
                2.0,
            ],
        }
    )

    prepared = prepare_feature_dataframe(
        input_df,
        profile_ids=[
            "antibody_io",
            "biomarker",
            "small_molecule",
        ],
    )

    assert prepared["target_symbol"].tolist() == [
        "BRAF",
        "CTLA4",
    ]

    assert "opentargets_rank" not in prepared.columns
    assert "antibody_io_final_score" not in prepared.columns
    assert "antibody_io_rank" not in prepared.columns
    assert "biomarker_final_score" not in prepared.columns
    assert "small_molecule_final_score" not in prepared.columns

    assert "opentargets_score" in prepared.columns
    assert "role_classification" in prepared.columns
    assert "custom_input_feature" in prepared.columns


def test_prepare_feature_dataframe_rejects_duplicate_symbols() -> None:
    input_df = pd.DataFrame(
        {
            "target_symbol": [
                "BRAF",
                " braf ",
            ],
            "opentargets_score": [
                0.85,
                0.80,
            ],
            "role_classification": [
                "role",
                "role",
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Duplicated target symbols",
    ):
        prepare_feature_dataframe(input_df)


def test_rank_metrics_detect_top_k_membership_change() -> None:
    baseline = pd.DataFrame(
        {
            "target_symbol": [
                "A",
                "B",
                "C",
                "D",
            ],
            "antibody_io_rank": [
                1,
                2,
                3,
                4,
            ],
            "antibody_io_final_score": [
                0.90,
                0.80,
                0.70,
                0.60,
            ],
        }
    )

    scenario = pd.DataFrame(
        {
            "target_symbol": [
                "A",
                "B",
                "C",
                "D",
            ],
            "antibody_io_rank": [
                1,
                3,
                2,
                4,
            ],
            "antibody_io_final_score": [
                0.91,
                0.72,
                0.79,
                0.60,
            ],
        }
    )

    metrics, comparison = _rank_metrics(
        baseline=baseline,
        scenario=scenario,
        profile_id="antibody_io",
        top_k_values=[2, 3],
    )

    assert metrics["spearman_rank_correlation"] == pytest.approx(
        0.8
    )

    assert metrics["mean_absolute_rank_change"] == pytest.approx(
        0.5
    )

    assert metrics["max_absolute_rank_change"] == pytest.approx(
        1.0
    )

    assert metrics["top_2_jaccard"] == pytest.approx(
        1 / 3
    )

    assert metrics["top_2_retention"] == pytest.approx(
        0.5
    )

    assert metrics["top_3_jaccard"] == pytest.approx(
        1.0
    )

    indexed = comparison.set_index("target_symbol")

    assert indexed.loc["B", "rank_change"] == 1
    assert indexed.loc["C", "rank_change"] == -1
    assert bool(indexed.loc["B", "baseline_top_2"]) is True
    assert bool(indexed.loc["B", "scenario_top_2"]) is False
    assert bool(indexed.loc["C", "baseline_top_2"]) is False
    assert bool(indexed.loc["C", "scenario_top_2"]) is True


def test_repository_scoring_configs_are_valid() -> None:
    configs = load_scoring_configs()

    assert set(configs) == {
        "antibody_io",
        "biomarker",
        "small_molecule",
    }

    for profile_id, config in configs.items():
        assert config["scoring_profile"]["id"] == profile_id

        weights = normalize_weights(
            config["weights"]
        )

        assert weights
        assert sum(weights.values()) == pytest.approx(1.0)


def test_save_sensitivity_results(
    tmp_path: Path,
) -> None:
    analysis = SensitivityAnalysis(
        scenarios=pd.DataFrame(
            {
                "scenario_id": [
                    "test__weight__plus20",
                ],
                "spearman_rank_correlation": [
                    0.99,
                ],
            }
        ),
        summary=pd.DataFrame(
            {
                "profile_id": [
                    "test",
                ],
                "minimum_spearman": [
                    0.99,
                ],
            }
        ),
        by_weight=pd.DataFrame(
            {
                "profile_id": [
                    "test",
                ],
                "weight_name": [
                    "weight",
                ],
            }
        ),
        target_rank_stability=pd.DataFrame(
            {
                "profile_id": [
                    "test",
                ],
                "target_symbol": [
                    "GENE1",
                ],
                "max_absolute_rank_change": [
                    2,
                ],
            }
        ),
        metrics={
            "analysis_id": "test_sensitivity",
            "scenario_count": 1,
        },
    )

    paths = save_sensitivity_results(
        analysis,
        output_dir=tmp_path,
    )

    assert set(paths) == {
        "scenarios",
        "summary",
        "by_weight",
        "target_rank_stability",
        "metrics",
    }

    for path in paths.values():
        assert path.is_file()

    metrics = json.loads(
        paths["metrics"].read_text(
            encoding="utf-8"
        )
    )

    assert metrics == {
        "analysis_id": "test_sensitivity",
        "scenario_count": 1,
    }

    saved_scenarios = pd.read_csv(
        paths["scenarios"]
    )

    assert len(saved_scenarios) == 1
    assert (
        saved_scenarios.iloc[0]["scenario_id"]
        == "test__weight__plus20"
    )

def test_prepare_feature_dataframe_preserves_modality_input_features() -> None:
    """Input modality features must not be mistaken for generated scores."""
    input_df = pd.DataFrame(
        {
            "target_symbol": [
                "BRAF",
                "B2M",
            ],
            "opentargets_score": [
                0.85,
                0.70,
            ],
            "role_classification": [
                "tumor-intrinsic driver / small-molecule target",
                "antigen-presentation resistance biomarker",
            ],
            "antibody_fit": [
                "low",
                "low",
            ],
            "io_combination_fit": [
                "low",
                "low",
            ],
            "biomarker_fit": [
                "medium",
                "high",
            ],
            "small_molecule_fit": [
                "high",
                "low",
            ],
            "antibody_io_final_score": [
                0.10,
                0.20,
            ],
            "biomarker_final_score": [
                0.30,
                0.80,
            ],
            "small_molecule_final_score": [
                0.90,
                0.10,
            ],
            "antibody_io_rank": [
                2,
                1,
            ],
            "biomarker_rank": [
                2,
                1,
            ],
            "small_molecule_rank": [
                1,
                2,
            ],
        }
    )

    prepared = prepare_feature_dataframe(
        input_df,
        profile_ids=[
            "antibody_io",
            "biomarker",
            "small_molecule",
        ],
    )

    for column in [
        "antibody_fit",
        "io_combination_fit",
        "biomarker_fit",
        "small_molecule_fit",
    ]:
        assert column in prepared.columns

    for column in [
        "antibody_io_final_score",
        "biomarker_final_score",
        "small_molecule_final_score",
        "antibody_io_rank",
        "biomarker_rank",
        "small_molecule_rank",
    ]:
        assert column not in prepared.columns

    assert prepared.loc[0, "small_molecule_fit"] == "high"
    assert prepared.loc[1, "biomarker_fit"] == "high"
