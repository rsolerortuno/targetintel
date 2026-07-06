"""
Therapeutic-intent scoring for TargetIntel-IO.

This module applies configurable YAML scoring profiles to the TargetIntel-IO
feature table.

Each profile answers a different translational question:

- antibody_io:
    Which targets are best for antibody / IO-combination strategies?

- biomarker:
    Which targets are best interpreted as resistance biomarkers or
    patient-stratification markers?

- small_molecule:
    Which targets are best for tumor-intrinsic or small-molecule intervention?

The scores are transparent, rule-based, and configurable.
They are not statistical probabilities and do not claim clinical validity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


DEFAULT_SCORING_CONFIGS = {
    "antibody_io": Path("configs/scoring_antibody_io.yaml"),
    "biomarker": Path("configs/scoring_biomarker.yaml"),
    "small_molecule": Path("configs/scoring_small_molecule.yaml"),
}


DEFAULT_MODALITY_WEIGHTS = {
    "antibody_io": {
        "antibody_fit": 0.45,
        "io_combination_fit": 0.45,
        "biomarker_fit": 0.05,
        "small_molecule_fit": 0.05,
    },
    "biomarker": {
        "biomarker_fit": 0.70,
        "io_combination_fit": 0.10,
        "antibody_fit": 0.10,
        "small_molecule_fit": 0.10,
    },
    "small_molecule": {
        "small_molecule_fit": 0.70,
        "biomarker_fit": 0.15,
        "io_combination_fit": 0.10,
        "antibody_fit": 0.05,
    },
}


def load_scoring_config(config_path: str | Path) -> dict[str, Any]:
    """
    Load one therapeutic-intent scoring configuration from YAML.
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Scoring config not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise ValueError(f"Scoring config must be a YAML dictionary: {config_path}")

    required_sections = [
        "scoring_profile",
        "weights",
        "role_scores",
        "modality_scores",
        "confidence_scores",
        "penalties",
    ]

    missing = [section for section in required_sections if section not in config]

    if missing:
        raise ValueError(
            f"Scoring config {config_path} is missing sections: {missing}"
        )

    return config


def _safe_str(value: Any) -> str:
    """Convert a value to a safe lowercase-stripped string."""
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely."""
    try:
        if value is None or pd.isna(value):
            return default
    except TypeError:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    """Convert common truthy values to bool."""
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _clip01(value: float) -> float:
    """Clip a score to the [0, 1] range."""
    return max(0.0, min(1.0, value))


def _lookup_score(
    value: Any,
    score_map: dict[str, float],
    default: float = 0.0,
) -> float:
    """
    Look up a score from a mapping.

    Matching is attempted first with the original string and then with a
    lower-case version for robustness.
    """
    value_str = _safe_str(value)

    if value_str in score_map:
        return float(score_map[value_str])

    lower_map = {
        str(key).lower(): float(score)
        for key, score in score_map.items()
    }

    return lower_map.get(value_str.lower(), default)


def calculate_role_fit_score(
    row: pd.Series,
    config: dict[str, Any],
) -> float:
    """
    Calculate role-fit score for one row.
    """
    role = row.get("role_classification", "")
    role_scores = config.get("role_scores", {})

    return _lookup_score(role, role_scores, default=0.0)


def calculate_modality_fit_score(
    row: pd.Series,
    config: dict[str, Any],
) -> float:
    """
    Calculate profile-specific modality-fit score.

    The YAML defines how each fit label maps to a numeric score.
    This function then combines modality columns with profile-specific
    modality weights.
    """
    profile_id = config["scoring_profile"]["id"]

    modality_scores = config.get("modality_scores", {})
    modality_weights = config.get(
        "modality_weights",
        DEFAULT_MODALITY_WEIGHTS.get(profile_id, {}),
    )

    if not modality_weights:
        return 0.0

    weighted_scores = []
    weights = []

    for modality_column, weight in modality_weights.items():
        if modality_column not in modality_scores:
            continue

        fit_label = row.get(modality_column, "unclear")
        score_map = modality_scores[modality_column]

        fit_score = _lookup_score(fit_label, score_map, default=0.0)

        weighted_scores.append(fit_score * float(weight))
        weights.append(float(weight))

    if not weights:
        return 0.0

    return sum(weighted_scores) / sum(weights)


def calculate_evidence_balance_score(row: pd.Series) -> float:
    """
    Convert contradiction score into a positive evidence-balance score.

    contradiction_score:
        0 means little opposing evidence.
        1 means high contradiction / strong caution.

    evidence_balance_score:
        1 means favorable evidence balance.
        0 means poor evidence balance.
    """
    contradiction_score = _safe_float(row.get("contradiction_score"), default=0.0)

    return _clip01(1.0 - contradiction_score)


def calculate_novelty_or_crowding_score(row: pd.Series) -> float:
    """
    Placeholder novelty/crowding score.

    The current MVP does not yet include PubMed or ClinicalTrials counts.
    Until the evidence-density module is implemented, use a neutral value.

    Future version:
    - crowded / saturated targets may be penalized
    - emerging but plausible targets may be rewarded
    """
    if "novelty_or_crowding_score" in row.index:
        return _safe_float(row.get("novelty_or_crowding_score"), default=0.5)

    if "crowding_score" in row.index:
        crowding_score = _safe_float(row.get("crowding_score"), default=0.5)
        return _clip01(1.0 - crowding_score)

    return 0.5


def calculate_penalty(
    row: pd.Series,
    config: dict[str, Any],
) -> float:
    """
    Calculate additive penalties for a scoring profile.

    Penalties in YAML are expected to be negative values.
    """
    penalties = config.get("penalties", {})

    penalty = 0.0

    if _safe_bool(row.get("poor_direct_target_flag", False)):
        penalty += float(penalties.get("poor_direct_target_flag", 0.0))

    contradiction_score = _safe_float(row.get("contradiction_score"), default=0.0)

    if contradiction_score >= 0.6:
        penalty += float(penalties.get("high_contradiction_score", 0.0))

    resistance_axis = _safe_str(row.get("resistance_axis", "")).lower()

    if resistance_axis in {"", "unmapped", "nan"}:
        penalty += float(penalties.get("unmapped_resistance_axis", 0.0))

    return penalty


def score_row(
    row: pd.Series,
    config: dict[str, Any],
) -> dict[str, float]:
    """
    Score one target for one therapeutic-intent profile.
    """
    weights = config["weights"]
    confidence_scores = config["confidence_scores"]

    opentargets_score = _clip01(
        _safe_float(row.get("opentargets_score"), default=0.0)
    )

    resistance_axis_score = _clip01(
        _safe_float(row.get("resistance_axis_score"), default=0.0)
    )

    role_fit_score = _clip01(
        calculate_role_fit_score(row, config)
    )

    modality_fit_score = _clip01(
        calculate_modality_fit_score(row, config)
    )

    confidence_score = _clip01(
        _lookup_score(
            row.get("confidence_level", ""),
            confidence_scores,
            default=0.0,
        )
    )

    evidence_balance_score = _clip01(
        calculate_evidence_balance_score(row)
    )

    novelty_or_crowding_score = _clip01(
        calculate_novelty_or_crowding_score(row)
    )

    raw_score = (
        weights.get("opentargets_score", 0.0) * opentargets_score
        + weights.get("resistance_axis_score", 0.0) * resistance_axis_score
        + weights.get("role_fit_score", 0.0) * role_fit_score
        + weights.get("modality_fit_score", 0.0) * modality_fit_score
        + weights.get("confidence_score", 0.0) * confidence_score
        + weights.get("evidence_balance_score", 0.0) * evidence_balance_score
        + weights.get("novelty_or_crowding_score", 0.0) * novelty_or_crowding_score
    )

    penalty = calculate_penalty(row, config)

    final_score = _clip01(raw_score + penalty)

    return {
        "opentargets_component_score": opentargets_score,
        "resistance_axis_component_score": resistance_axis_score,
        "role_fit_component_score": role_fit_score,
        "modality_fit_component_score": modality_fit_score,
        "confidence_component_score": confidence_score,
        "evidence_balance_component_score": evidence_balance_score,
        "novelty_or_crowding_component_score": novelty_or_crowding_score,
        "penalty_score": penalty,
        "final_score": final_score,
    }


def score_dataframe_with_config(
    df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """
    Apply one scoring profile to a dataframe.

    Adds profile-specific component columns and the final score column.
    """
    df = df.copy()

    profile_id = config["scoring_profile"]["id"]

    calls = []

    for _, row in df.iterrows():
        calls.append(score_row(row, config))

    score_df = pd.DataFrame(calls)

    rename_map = {
        column: f"{profile_id}_{column}"
        for column in score_df.columns
    }

    score_df = score_df.rename(columns=rename_map)

    return pd.concat(
        [df.reset_index(drop=True), score_df.reset_index(drop=True)],
        axis=1,
    )


def score_dataframe(
    df: pd.DataFrame,
    config_path: str | Path,
) -> pd.DataFrame:
    """
    Load one YAML scoring profile and apply it to a dataframe.
    """
    config = load_scoring_config(config_path)

    return score_dataframe_with_config(df, config)


def score_all_profiles(
    df: pd.DataFrame,
    config_paths: dict[str, str | Path] | None = None,
) -> pd.DataFrame:
    """
    Apply all therapeutic-intent scoring profiles to a dataframe.
    """
    df = df.copy()

    if config_paths is None:
        config_paths = DEFAULT_SCORING_CONFIGS

    for _, config_path in config_paths.items():
        config = load_scoring_config(config_path)
        df = score_dataframe_with_config(df, config)

    return df
