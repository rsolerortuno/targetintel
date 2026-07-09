"""
Therapeutic-intent-aware ranking for TargetIntel-IO.

This module ranks targets separately for each therapeutic intent:

- antibody_io
- biomarker
- small_molecule

The biological role of a target is stable, but its rank changes depending on
the therapeutic question being asked.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from targetintel.scoring import DEFAULT_SCORING_CONFIGS, score_all_profiles


DEFAULT_RANKED_TARGETS_PATH = Path("results/ranked_targets.csv")


DEFAULT_PROFILE_IDS = [
    "antibody_io",
    "biomarker",
    "small_molecule",
]


def add_opentargets_rank(
    df: pd.DataFrame,
    score_column: str = "opentargets_score",
) -> pd.DataFrame:
    """
    Add the Open Targets baseline rank.

    Only targets actually retrieved from Open Targets receive a baseline rank.
    Required targets added for complete benchmark evaluation retain a missing
    Open Targets rank.
    """
    df = df.copy()

    if score_column not in df.columns:
        raise KeyError(f"Column not found: {score_column}")

    score_values = pd.to_numeric(
        df[score_column],
        errors="coerce",
    )

    if "opentargets_evidence_available" in df.columns:
        evidence_available = (
            df["opentargets_evidence_available"]
            .fillna(False)
            .map(
                lambda value: (
                    value
                    if isinstance(value, bool)
                    else str(value).strip().lower()
                    in {"true", "1", "yes", "y"}
                )
            )
        )
    else:
        evidence_available = score_values.notna()

    opentargets_rank = pd.Series(
        pd.NA,
        index=df.index,
        dtype="Int64",
    )

    if evidence_available.any():
        available_ranks = (
            score_values.loc[evidence_available]
            .rank(
                method="min",
                ascending=False,
            )
            .astype("Int64")
        )

        opentargets_rank.loc[evidence_available] = (
            available_ranks
        )

    df["opentargets_rank"] = opentargets_rank

    return df


def add_intent_ranks(
    df: pd.DataFrame,
    profile_ids: list[str] | None = None,
) -> pd.DataFrame:
    """
    Add rank columns for each therapeutic-intent score.

    Ranking is deterministic and uses Open Targets score as a secondary
    tie-breaker. This avoids many zero-score candidates sharing the same
    apparently high rank.
    """
    df = df.copy()

    if profile_ids is None:
        profile_ids = DEFAULT_PROFILE_IDS

    for profile_id in profile_ids:
        score_column = f"{profile_id}_final_score"
        rank_column = f"{profile_id}_rank"
        priority_column = f"{profile_id}_priority"

        if score_column not in df.columns:
            raise KeyError(
                f"Score column not found: {score_column}. "
                "Run score_all_profiles() before add_intent_ranks()."
            )

        sorted_index = (
            df.sort_values(
                by=[score_column, "opentargets_score"],
                ascending=[False, False],
            )
            .index
        )

        df[rank_column] = pd.NA
        df.loc[sorted_index, rank_column] = range(1, len(df) + 1)
        df[rank_column] = df[rank_column].astype(int)

        df[priority_column] = df[score_column].apply(assign_priority_label)

    return df

def assign_priority_label(score: float) -> str:
    """
    Convert final score into a qualitative priority label.

    This label is useful for dashboards and prevents low/zero-score genes
    from being interpreted as meaningful top candidates.
    """
    if pd.isna(score):
        return "not prioritized"

    score = float(score)

    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    if score > 0.10:
        return "low"

    return "not prioritized"

def add_rank_shift_vs_opentargets(
    df: pd.DataFrame,
    profile_ids: list[str] | None = None,
) -> pd.DataFrame:
    """
    Add rank-shift columns relative to Open Targets baseline.

    Definition:
        rank_shift_vs_opentargets = opentargets_rank - intent_rank

    Positive value:
        target moved up in the TargetIntel-IO intent-specific ranking.

    Negative value:
        target moved down relative to Open Targets-only ranking.
    """
    df = df.copy()

    if "opentargets_rank" not in df.columns:
        df = add_opentargets_rank(df)

    if profile_ids is None:
        profile_ids = DEFAULT_PROFILE_IDS

    for profile_id in profile_ids:
        rank_column = f"{profile_id}_rank"
        shift_column = f"{profile_id}_rank_shift_vs_opentargets"

        if rank_column not in df.columns:
            raise KeyError(
                f"Rank column not found: {rank_column}. "
                "Run add_intent_ranks() first."
            )

        df[shift_column] = df["opentargets_rank"] - df[rank_column]

    return df


def build_intent_rankings(
    feature_df: pd.DataFrame,
    config_paths: dict[str, str | Path] | None = None,
) -> pd.DataFrame:
    """
    Score and rank targets across all therapeutic-intent profiles.
    """
    if config_paths is None:
        config_paths = DEFAULT_SCORING_CONFIGS

    ranked_df = feature_df.copy()

    ranked_df = add_opentargets_rank(ranked_df)

    ranked_df = score_all_profiles(
        ranked_df,
        config_paths=config_paths,
    )

    ranked_df = add_intent_ranks(ranked_df)

    ranked_df = add_rank_shift_vs_opentargets(ranked_df)

    ranked_df = reorder_ranking_columns(ranked_df)

    return ranked_df


def reorder_ranking_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Move key ranking columns near the front of the table.
    """
    preferred_columns = [
        "target_symbol",
        "target_name",
        "opentargets_score",
        "opentargets_rank",

        "role_classification",
        "role_confidence",
        "therapeutic_direction",
        "best_modality",

        "resistance_axis",
        "matched_resistance_programs",

        "antibody_fit",
        "small_molecule_fit",
        "biomarker_fit",
        "io_combination_fit",
        "poor_direct_target_flag",

        "confidence_level",
        "contradiction_score",
        "data_completeness_score",

        "antibody_io_final_score",
        "antibody_io_rank",
        "antibody_io_priority",
        "antibody_io_rank_shift_vs_opentargets",

        "biomarker_final_score",
        "biomarker_rank",
        "biomarker_priority",
        "biomarker_rank_shift_vs_opentargets",

        "small_molecule_final_score",
        "small_molecule_rank",
        "small_molecule_priority",
        "small_molecule_rank_shift_vs_opentargets",

        "evidence_for",
        "evidence_against",
        "main_limitation",
        "deprioritization_reason",
    ]

    existing_preferred_columns = [
        column for column in preferred_columns if column in df.columns
    ]

    remaining_columns = [
        column for column in df.columns if column not in existing_preferred_columns
    ]

    return df[existing_preferred_columns + remaining_columns]


def save_ranked_targets(
    df: pd.DataFrame,
    output_path: str | Path = DEFAULT_RANKED_TARGETS_PATH,
) -> Path:
    """
    Save ranked TargetIntel-IO targets to CSV.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(output_path, index=False)

    return output_path
