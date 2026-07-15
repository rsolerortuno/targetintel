"""
Target hypothesis card generation for TargetIntel-IO.

This module converts ranked TargetIntel-IO rows into readable Markdown
hypothesis cards.

The cards are intended as transparent target-ID summaries, not as clinical
recommendations or validated biological claims.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from targetintel.evidence.reporting import EvidenceCard


DEFAULT_CARD_DIR = Path("results/target_cards")


def _safe_str(value: Any) -> str:
    """Convert missing values into clean display strings."""
    if value is None:
        return "not available"

    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    value = str(value).strip()

    if not value:
        return "not available"

    return value


def _safe_float(value: Any, digits: int = 3) -> str:
    """Format numeric values safely."""
    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "not available"


def _safe_int(value: Any) -> str:
    """Format integer-like values safely."""
    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "not available"


def _split_pipe_text(value: Any) -> list[str]:
    """Split pipe-separated evidence strings."""
    text = _safe_str(value)

    if text == "not available":
        return []

    return [item.strip() for item in text.split("|") if item.strip()]


def _format_bullets(items: list[str]) -> str:
    """Format a list of strings as Markdown bullets."""
    if not items:
        return "- not available"

    return "\n".join(f"- {item}" for item in items)


def _format_extraction_confidence(value: float | int | None) -> str:
    if value is None:
        return "not reported (extraction-system confidence, not scientific confidence)"
    return f"{float(value):.3f} (extraction-system confidence, not scientific confidence)"


def _evidence_support(item: Any) -> tuple[str, str]:
    if item.quoted_span is not None and item.computed_support is not None:
        return "Hybrid quotation and computed support", f"Quoted span: {item.quoted_span}\n  Computed support: {item.computed_support}"
    if item.quoted_span is not None:
        return "Quoted source text", item.quoted_span
    return "Computed/database support", item.computed_support or "not available"


def make_evidence_card_section(evidence_card: EvidenceCard | None) -> str:
    """Render stored verified observations without target-level synthesis."""
    if evidence_card is None:
        return ""
    metrics = evidence_card.metrics
    records: list[str] = []
    for item in evidence_card.items:
        support_type, support = _evidence_support(item)
        family = item.evidence_family or "ineligible for independence metrics"
        records.append(
            f"### Evidence record: {item.evidence_id}\n\n"
            f"- **Evidence type / direction:** {item.evidence_type} / {item.evidence_direction}\n"
            f"- **Observation:** {item.observation}\n"
            f"- **Source:** {item.source} ({item.source_id})\n"
            f"- **Support type:** {support_type}\n"
            f"- **Supporting material:** {support}\n"
            f"- **Validation status:** {item.validation_status}\n"
            f"- **Extraction confidence:** {_format_extraction_confidence(item.extraction_confidence)}\n"
            f"- **Evidence family:** {family}"
        )
    return (
        "## Stored evidence observations\n\n"
        "These are source-linked observations. They do not alter the deterministic "
        "classification, scores, or rankings above.\n\n"
        "| Metric | Count |\n| --- | ---: |\n"
        f"| Distinct evidence records | {metrics.record_count} |\n"
        f"| Known publications | {metrics.publication_count} |\n"
        f"| Known experiments | {metrics.experiment_count} |\n"
        f"| Known patient cohorts | {metrics.patient_cohort_count} |\n"
        f"| Independence-eligible root families | {metrics.independent_family_count} |\n"
        f"| Records ineligible for family metrics | {metrics.ineligible_record_count} |\n\n"
        + "\n\n".join(records)
        + "\n"
    )


def recommend_next_experiment(row: pd.Series) -> tuple[str, str, str]:
    """
    Recommend a concise next validation experiment based on role and modality.

    Returns
    -------
    tuple
        next_best_experiment, experiment_rationale, validation_category
    """
    symbol = _safe_str(row.get("target_symbol"))
    role = _safe_str(row.get("role_classification")).lower()
    best_modality = _safe_str(row.get("best_modality")).lower()
    resistance_axis = _safe_str(row.get("resistance_axis")).lower()

    if "checkpoint" in resistance_axis or "anti-pd-1 combination" in role:
        return (
            f"Validate {symbol} expression in exhausted CD8 T-cell populations from anti-PD-1-resistant melanoma samples and test blockade in a melanoma/T-cell co-culture assay.",
            "This would test whether the candidate marks a relevant checkpoint axis and whether blockade can improve anti-tumor T-cell activity.",
            "immune-checkpoint functional validation",
        )

    if "myeloid" in role or "myeloid" in resistance_axis:
        return (
            f"Validate {symbol} expression in suppressive myeloid/macrophage populations and test perturbation in macrophage/T-cell co-culture.",
            "This would assess whether the target contributes to a suppressive tumor microenvironment and whether modulation improves T-cell function.",
            "myeloid/TME validation",
        )

    if "biomarker" in role or "patient stratification" in best_modality:
        return (
            f"Test whether {symbol} status or expression differs between anti-PD-1 responders and non-responders in an independent melanoma cohort.",
            "This would determine whether the candidate has practical value as a resistance biomarker or patient-stratification feature.",
            "biomarker validation",
        )

    if "small molecule" in best_modality or "tumor-intrinsic" in role:
        return (
            f"Evaluate whether perturbing {symbol} alters melanoma cell viability, pathway activity, or immune-sensitivity in tumor-cell intrinsic assays.",
            "This would test whether the candidate is a functional tumor-intrinsic dependency or pathway intervention point.",
            "tumor-intrinsic functional validation",
        )

    if "poor direct therapeutic target" in role:
        return (
            f"Use {symbol} as pathway context or stratification feature rather than prioritizing it for direct therapeutic targeting.",
            "The current TargetIntel-IO rules indicate biological relevance but weak direct targetability.",
            "deprioritization / context validation",
        )

    return (
        f"Perform literature review and cohort-level expression analysis for {symbol} in anti-PD-1-resistant melanoma.",
        "The current evidence is insufficient for a confident therapeutic interpretation.",
        "evidence-gathering",
    )


def make_target_card(
    row: pd.Series,
    evidence_card: EvidenceCard | None = None,
) -> str:
    """
    Generate one Markdown target hypothesis card.
    """
    symbol = _safe_str(row.get("target_symbol"))
    target_name = _safe_str(row.get("target_name"))

    next_experiment, experiment_rationale, validation_category = (
        recommend_next_experiment(row)
    )

    evidence_for_items = _split_pipe_text(row.get("evidence_for"))
    evidence_against_items = _split_pipe_text(row.get("evidence_against"))

    card = f"""# Target hypothesis card: {symbol}

## Target identity

- **Target symbol:** {symbol}
- **Target name:** {target_name}
- **Open Targets melanoma score:** {_safe_float(row.get("opentargets_score"))}
- **Open Targets baseline rank:** {_safe_int(row.get("opentargets_rank"))}

## Stable TargetIntel-IO classification

- **Role classification:** {_safe_str(row.get("role_classification"))}
- **Role confidence:** {_safe_str(row.get("role_confidence"))}
- **Therapeutic direction:** {_safe_str(row.get("therapeutic_direction"))}
- **Best modality:** {_safe_str(row.get("best_modality"))}
- **Resistance axis:** {_safe_str(row.get("resistance_axis"))}
- **Matched resistance programs:** {_safe_str(row.get("matched_resistance_programs"))}

## Therapeutic-intent rankings

| Therapeutic intent | Score | Rank | Priority | Rank shift vs Open Targets |
| --- | ---: | ---: | --- | ---: |
| Antibody / IO-combination | {_safe_float(row.get("antibody_io_final_score"))} | {_safe_int(row.get("antibody_io_rank"))} | {_safe_str(row.get("antibody_io_priority"))} | {_safe_int(row.get("antibody_io_rank_shift_vs_opentargets"))} |
| Resistance biomarker | {_safe_float(row.get("biomarker_final_score"))} | {_safe_int(row.get("biomarker_rank"))} | {_safe_str(row.get("biomarker_priority"))} | {_safe_int(row.get("biomarker_rank_shift_vs_opentargets"))} |
| Tumor-intrinsic / small molecule | {_safe_float(row.get("small_molecule_final_score"))} | {_safe_int(row.get("small_molecule_rank"))} | {_safe_str(row.get("small_molecule_priority"))} | {_safe_int(row.get("small_molecule_rank_shift_vs_opentargets"))} |

## Evidence for

{_format_bullets(evidence_for_items)}

## Evidence against / limitations

{_format_bullets(evidence_against_items)}

## Confidence and uncertainty

- **Confidence level:** {_safe_str(row.get("confidence_level"))}
- **Data completeness score:** {_safe_float(row.get("data_completeness_score"))}
- **Contradiction score:** {_safe_float(row.get("contradiction_score"))}
- **Main limitation:** {_safe_str(row.get("main_limitation"))}
- **Uncertainty reason:** {_safe_str(row.get("uncertainty_reason"))}
- **Deprioritization reason:** {_safe_str(row.get("deprioritization_reason"))}

## Recommended next validation experiment

- **Validation category:** {validation_category}
- **Next experiment:** {next_experiment}
- **Rationale:** {experiment_rationale}

## Interpretation note

This card is generated by TargetIntel-IO as a transparent, rule-based target triage summary. It is intended for hypothesis generation and portfolio demonstration only. It does not represent clinical advice or validated therapeutic evidence.

{make_evidence_card_section(evidence_card)}
"""

    return card


def write_target_card(
    row: pd.Series,
    output_dir: str | Path = DEFAULT_CARD_DIR,
    evidence_card: EvidenceCard | None = None,
) -> Path:
    """
    Write one target card to Markdown.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    symbol = _safe_str(row.get("target_symbol"))
    output_path = output_dir / f"{symbol}.md"

    output_path.write_text(
        make_target_card(row, evidence_card=evidence_card),
        encoding="utf-8",
    )

    return output_path


def write_top_target_cards(
    ranked_df: pd.DataFrame,
    output_dir: str | Path = DEFAULT_CARD_DIR,
    top_n_per_mode: int = 10,
    evidence_cards: Mapping[str, EvidenceCard] | None = None,
) -> list[Path]:
    """
    Write Markdown target cards for the top targets across all modes.

    The union of top-N targets from antibody_io, biomarker, and small_molecule
    rankings is used to avoid duplicate cards.
    """
    required_rank_columns = [
        "antibody_io_rank",
        "biomarker_rank",
        "small_molecule_rank",
    ]

    for column in required_rank_columns:
        if column not in ranked_df.columns:
            raise KeyError(f"Required rank column not found: {column}")

    selected_symbols = set()

    for rank_column in required_rank_columns:
        top_symbols = (
            ranked_df.sort_values(rank_column)
            .head(top_n_per_mode)["target_symbol"]
            .tolist()
        )
        selected_symbols.update(top_symbols)

    selected_df = ranked_df[
        ranked_df["target_symbol"].isin(selected_symbols)
    ].copy()

    selected_df = selected_df.sort_values(
        by=[
            "antibody_io_rank",
            "biomarker_rank",
            "small_molecule_rank",
        ]
    )

    written_paths = []

    for _, row in selected_df.iterrows():
        written_paths.append(write_target_card(
            row,
            output_dir=output_dir,
            evidence_card=(evidence_cards or {}).get(str(row["target_symbol"])),
        ))

    return written_paths
