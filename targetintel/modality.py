"""
Modality-aware reasoning for TargetIntel-IO.

This module evaluates whether each candidate is a plausible fit for different
therapeutic or translational modalities:

- antibody
- small molecule
- biomarker
- IO-combination target
- poor direct therapeutic target

The logic is intentionally rule-based and transparent for the MVP.
It does not replace full target tractability assessment from resources such as
Open Targets, nor does it claim validated druggability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

import pandas as pd

# This module is intentionally the public home for both the legacy rule based
# modality call and the v0.4 descriptive feasibility decoration.  The imports
# below are contracts only: they do not invoke Open Targets, caches, scoring,
# ranking, roles, evidence, or transport.
from .feasibility.models import (
    PROFILE_FORMAT_VERSION,
    THERAPEUTIC_MODALITIES,
    TargetFeasibilityProfile,
    canonical_json,
)
from .feasibility.profiles import (
    FeasibilityDimensionCoverage,
    TargetFeasibilityProfileBuildResult,
)
from .feasibility.validation import ValidationError, require_valid_profile


_FEASIBILITY_DIMENSIONS = ("clinical_precedence", "tractability", "doability", "safety")
_COVERAGE_STATES = frozenset({"observed", "partial", "not_available", "not_applicable", "conflicting", "retrieval_failed"})
# The legacy evaluator has human-readable labels, not a controlled request
# vocabulary.  These are the only unambiguous compatibility aliases.
_LEGACY_MODALITY_ALIASES = MappingProxyType({
    "small molecule": "small_molecule",
    "small-molecule": "small_molecule",
    "small_molecule": "small_molecule",
    "antibody": "antibody",
    "protac": "protac",
    "other clinical": "other_clinical",
    "other_clinical": "other_clinical",
})


class ModalityFeasibilityCompositionError(ValueError):
    """Sanitized deterministic failure for profile-aware composition."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _identity(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}_{sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def normalize_feasibility_modality(modality: str) -> str:
    """Return an approved modality, accepting only documented legacy aliases."""
    if not isinstance(modality, str):
        raise ModalityFeasibilityCompositionError("unsupported_modality")
    normalized = _LEGACY_MODALITY_ALIASES.get(modality.strip().casefold())
    if normalized is None or normalized not in THERAPEUTIC_MODALITIES:
        raise ModalityFeasibilityCompositionError("unsupported_modality")
    return normalized


@dataclass(frozen=True)
class ModalityCall:
    """Container for modality-fit annotation."""

    antibody_fit: str
    small_molecule_fit: str
    biomarker_fit: str
    io_combination_fit: str
    poor_direct_target_flag: bool
    best_modality: str
    modality_rationale: str


SURFACE_CHECKPOINT_TARGETS = {
    "PDCD1",
    "CD274",
    "CTLA4",
    "LAG3",
    "TIGIT",
    "HAVCR2",
}

SURFACE_MYELOID_TME_TARGETS = {
    "CSF1R",
    "TREM2",
    "MARCO",
    "LILRB1",
    "LILRB2",
    "LILRB3",
    "MERTK",
    "CD163",
}

SURFACE_TREG_TARGETS = {
    "IL2RA",
    "TNFRSF18",
    "CTLA4",
}

SECRETED_OR_LIGAND_AXIS_TARGETS = {
    "TGFB1",
    "CXCL12",
}

RECEPTOR_OR_SURFACE_AXIS_TARGETS = {
    "TGFBR1",
    "TGFBR2",
    "CXCR4",
    "FAP",
}

SMALL_MOLECULE_COMPATIBLE_TARGETS = {
    "BRAF",
    "MAP2K1",
    "MAP2K2",
    "KIT",
    "CDK4",
    "MERTK",
    "AXL",
    "TGFBR1",
    "TGFBR2",
    "CXCR4",
    "IDO1",
    "ARG1",
}

BIOMARKER_RESISTANCE_TARGETS = {
    "B2M",
    "HLA-A",
    "HLA-B",
    "HLA-C",
    "TAP1",
    "TAP2",
    "JAK1",
    "JAK2",
    "IFNGR1",
    "IFNGR2",
    "STAT1",
    "IRF1",
}

POOR_DIRECT_TARGETS = {
    "CDKN2A",
    "PTEN",
    "NF1",
    "BAP1",
    "TP53",
    "RB1",
}

TUMOR_INTRINSIC_BIOMARKERS = {
    "NRAS",
    "MITF",
    "TERT",
}

IMMUNE_CONTEXT_MARKERS = {
    "CD8A",
    "CD8B",
    "GZMB",
    "PRF1",
    "CXCL9",
    "CXCL10",
    "FOXP3",
}


def normalize_symbol(gene_symbol: Any) -> str:
    """Normalize a gene symbol for rule matching."""
    if pd.isna(gene_symbol):
        return ""

    return str(gene_symbol).strip().upper()


def assign_modality_fit(
    gene_symbol: str,
    role_classification: str | None = None,
    therapeutic_direction: str | None = None,
    resistance_axis: str | None = None,
) -> ModalityCall:
    """
    Assign modality-fit labels to one candidate gene.

    Parameters
    ----------
    gene_symbol:
        HGNC-style gene symbol.
    role_classification:
        Stable role from role_classifier.py.
    therapeutic_direction:
        Therapeutic direction from role_classifier.py.
    resistance_axis:
        Resistance-axis annotation from resistance_ontology.py.

    Returns
    -------
    ModalityCall
        Modality-fit labels and rationale.
    """
    symbol = normalize_symbol(gene_symbol)
    role = (role_classification or "").lower()
    direction = (therapeutic_direction or "").lower()
    axis = (resistance_axis or "").lower()

    if symbol in SURFACE_CHECKPOINT_TARGETS:
        return ModalityCall(
            antibody_fit="high",
            small_molecule_fit="low",
            biomarker_fit="medium",
            io_combination_fit="high",
            poor_direct_target_flag=False,
            best_modality="antibody / IO-combination target",
            modality_rationale=(
                f"{symbol} is a checkpoint-axis candidate. Surface/checkpoint "
                "biology supports antibody or bispecific IO-combination strategies, "
                "while small-molecule fit is lower for this MVP."
            ),
        )

    if symbol in SURFACE_MYELOID_TME_TARGETS:
        return ModalityCall(
            antibody_fit="medium-high",
            small_molecule_fit="medium" if symbol in SMALL_MOLECULE_COMPATIBLE_TARGETS else "low-medium",
            biomarker_fit="medium",
            io_combination_fit="medium-high",
            poor_direct_target_flag=False,
            best_modality="myeloid/TME IO-combination target",
            modality_rationale=(
                f"{symbol} maps to suppressive myeloid/TME biology. This supports "
                "IO-combination hypotheses, especially for surface-accessible "
                "myeloid targets, but therapeutic direction may be context-dependent."
            ),
        )

    if symbol in SURFACE_TREG_TARGETS:
        return ModalityCall(
            antibody_fit="medium-high",
            small_molecule_fit="low",
            biomarker_fit="medium",
            io_combination_fit="medium",
            poor_direct_target_flag=False,
            best_modality="antibody / Treg-associated IO-combination candidate",
            modality_rationale=(
                f"{symbol} is associated with Treg-mediated suppression. It may "
                "fit antibody-based depletion or blockade hypotheses, but safety "
                "and immune tolerance concerns require caution."
            ),
        )

    if symbol in SECRETED_OR_LIGAND_AXIS_TARGETS:
        return ModalityCall(
            antibody_fit="medium-high",
            small_molecule_fit="low-medium",
            biomarker_fit="medium",
            io_combination_fit="medium-high",
            poor_direct_target_flag=False,
            best_modality="ligand blockade / IO-combination target",
            modality_rationale=(
                f"{symbol} is part of a secreted ligand or stromal axis. Ligand "
                "blockade can be conceptually compatible with antibody strategies, "
                "but biology is pleiotropic and patient selection may be important."
            ),
        )

    if symbol in RECEPTOR_OR_SURFACE_AXIS_TARGETS:
        return ModalityCall(
            antibody_fit="medium",
            small_molecule_fit="medium-high" if symbol in SMALL_MOLECULE_COMPATIBLE_TARGETS else "medium",
            biomarker_fit="medium",
            io_combination_fit="medium",
            poor_direct_target_flag=False,
            best_modality="TME pathway targeting / IO-combination candidate",
            modality_rationale=(
                f"{symbol} belongs to a stromal or immune-exclusion axis. It may "
                "fit pathway targeting or IO-combination hypotheses, but safety "
                "and context-dependence are important limitations."
            ),
        )

    if symbol in SMALL_MOLECULE_COMPATIBLE_TARGETS:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="high",
            biomarker_fit="medium",
            io_combination_fit="low-medium",
            poor_direct_target_flag=False,
            best_modality="small molecule / pathway targeting",
            modality_rationale=(
                f"{symbol} is best interpreted as a small-molecule or pathway "
                "target in this MVP. It should not be prioritized primarily as "
                "an antibody IO-combination target."
            ),
        )

    if symbol in BIOMARKER_RESISTANCE_TARGETS:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="low-medium",
            biomarker_fit="high",
            io_combination_fit="low-medium",
            poor_direct_target_flag=False,
            best_modality="resistance biomarker / patient stratification",
            modality_rationale=(
                f"{symbol} is best interpreted as a resistance biomarker or "
                "mechanistic marker. It may inform patient stratification but is "
                "not a strong direct therapeutic target in this MVP."
            ),
        )

    if symbol in POOR_DIRECT_TARGETS:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="low",
            biomarker_fit="medium",
            io_combination_fit="low",
            poor_direct_target_flag=True,
            best_modality="biomarker / pathway context only",
            modality_rationale=(
                f"{symbol} is biologically relevant to melanoma but is a poor "
                "direct therapeutic target for this MVP, especially for antibody "
                "or IO-combination modalities. It is better treated as pathway "
                "context, biomarker, or stratification information."
            ),
        )

    if symbol in TUMOR_INTRINSIC_BIOMARKERS:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="medium",
            biomarker_fit="medium-high",
            io_combination_fit="low-medium",
            poor_direct_target_flag=False,
            best_modality="tumor-intrinsic biomarker / pathway context",
            modality_rationale=(
                f"{symbol} is relevant to tumor-intrinsic melanoma biology. "
                "It may support biomarker or pathway-context interpretation, "
                "but direct actionability depends on downstream tractability."
            ),
        )

    if symbol in IMMUNE_CONTEXT_MARKERS:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="low",
            biomarker_fit="medium-high",
            io_combination_fit="low",
            poor_direct_target_flag=True,
            best_modality="immune-context biomarker",
            modality_rationale=(
                f"{symbol} is best interpreted as an immune-context marker rather "
                "than a causal therapeutic target. It may help describe immune-hot "
                "or immune-cold tumor states."
            ),
        )

    if "biomarker" in role or "mechanistic resistance marker" in role:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="low-medium",
            biomarker_fit="medium-high",
            io_combination_fit="low-medium",
            poor_direct_target_flag=False,
            best_modality="biomarker / patient stratification",
            modality_rationale=(
                f"{symbol} is classified as a biomarker or mechanistic marker. "
                "The strongest MVP modality is patient stratification rather than "
                "direct therapeutic targeting."
            ),
        )

    if "combination target" in role or "io-combination" in role:
        return ModalityCall(
            antibody_fit="medium",
            small_molecule_fit="low-medium",
            biomarker_fit="medium",
            io_combination_fit="medium-high",
            poor_direct_target_flag=False,
            best_modality="IO-combination target",
            modality_rationale=(
                f"{symbol} is classified as an IO-combination candidate. Modality "
                "fit is provisionally assigned from the role classifier because no "
                "more specific symbol-level modality rule exists yet."
            ),
        )

    if "tumor-intrinsic driver" in role:
        return ModalityCall(
            antibody_fit="low",
            small_molecule_fit="medium",
            biomarker_fit="medium",
            io_combination_fit="low",
            poor_direct_target_flag=False,
            best_modality="tumor-intrinsic / small-molecule context",
            modality_rationale=(
                f"{symbol} is classified as a tumor-intrinsic driver. It should be "
                "evaluated primarily in small-molecule, pathway, or biomarker modes, "
                "not as a primary antibody IO-combination target."
            ),
        )

    if axis and axis != "unmapped":
        return ModalityCall(
            antibody_fit="unclear",
            small_molecule_fit="unclear",
            biomarker_fit="medium",
            io_combination_fit="unclear",
            poor_direct_target_flag=False,
            best_modality="unclear / resistance-axis-associated candidate",
            modality_rationale=(
                f"{symbol} maps to resistance axis '{resistance_axis}', but no "
                "specific modality rule is currently available. More evidence is "
                "needed before assigning a confident modality fit."
            ),
        )

    return ModalityCall(
        antibody_fit="unclear",
        small_molecule_fit="unclear",
        biomarker_fit="unclear",
        io_combination_fit="unclear",
        poor_direct_target_flag=False,
        best_modality="unclear",
        modality_rationale=(
            f"{symbol} has no curated modality rule and is not currently mapped "
            "to a TargetIntel-IO resistance axis. Its therapeutic modality fit is unclear."
        ),
    )


def annotate_modality_dataframe(
    df: pd.DataFrame,
    gene_column: str = "target_symbol",
    role_column: str = "role_classification",
    therapeutic_direction_column: str = "therapeutic_direction",
    resistance_axis_column: str = "resistance_axis",
) -> pd.DataFrame:
    """
    Add modality-fit annotations to a dataframe.

    Parameters
    ----------
    df:
        Input dataframe containing candidate targets.
    gene_column:
        Column containing gene symbols.
    role_column:
        Column containing stable role classification.
    therapeutic_direction_column:
        Column containing therapeutic direction.
    resistance_axis_column:
        Column containing resistance-axis annotation.

    Returns
    -------
    pandas.DataFrame
        Input dataframe with modality-fit columns appended.
    """
    if gene_column not in df.columns:
        raise KeyError(f"Column not found in dataframe: {gene_column}")

    df = df.copy()

    calls = []

    for _, row in df.iterrows():
        call = assign_modality_fit(
            gene_symbol=row.get(gene_column),
            role_classification=row.get(role_column, ""),
            therapeutic_direction=row.get(therapeutic_direction_column, ""),
            resistance_axis=row.get(resistance_axis_column, ""),
        )
        calls.append(call.__dict__)

    calls_df = pd.DataFrame(calls)

    for column in calls_df.columns:
        df[column] = calls_df[column]

    return df


def _observation_sort_key(item: Any) -> tuple[str, str, str, str, str]:
    return (
        item.dimension,
        "" if item.modality is None else item.modality,
        item.factor_identifier,
        "" if item.source_record_identifier is None else item.source_record_identifier,
        item.observation_id,
    )


def _fallback_coverage(profile: TargetFeasibilityProfile, dimension: str, modality: str | None) -> FeasibilityDimensionCoverage:
    """Make an Issue-403 coverage contract when callers supply a profile alone.

    A standalone profile deliberately has no build-result coverage.  This
    conservative terminal record preserves that missing build context; it is
    not a feasibility calculation and never converts absence into a negative.
    """
    selected = tuple(item for item in profile.observations if item.dimension == dimension and item.modality == modality)
    states = {state: sum(item.availability_state == state for item in selected) for state in
              ("observed", "not_available", "not_observed", "conflicting", "retrieval_failed")}
    if states["retrieval_failed"]:
        state = "retrieval_failed"
    elif states["conflicting"]:
        state = "conflicting"
    elif selected:
        state = "observed"
    else:
        state = "not_available"
    return FeasibilityDimensionCoverage(
        "v0.4.0", profile.target_identifier, profile.target_identifier_type,
        dimension, modality, 0, states["observed"], states["not_available"],
        states["not_observed"], states["conflicting"], states["retrieval_failed"],
        0, state, ("coverage_not_supplied_by_profile_build_result",),
    )


def _profile_and_coverage(value: Any) -> tuple[TargetFeasibilityProfile, tuple[FeasibilityDimensionCoverage, ...]]:
    if isinstance(value, TargetFeasibilityProfileBuildResult):
        if value.status not in {"built", "built_with_gaps"} or value.profile is None:
            raise ModalityFeasibilityCompositionError("failed_profile_build_result")
        profile = value.profile
        coverage = tuple(value.dimension_coverage)
    elif isinstance(value, TargetFeasibilityProfile):
        profile = value
        coverage = ()
    elif value is None:
        raise ModalityFeasibilityCompositionError("missing_profile")
    else:
        raise ModalityFeasibilityCompositionError("invalid_feasibility_profile")
    if profile.profile_format_version != PROFILE_FORMAT_VERSION or not profile.profile_id:
        raise ModalityFeasibilityCompositionError("unsupported_profile_version")
    try:
        require_valid_profile(profile)
    except (ValidationError, ValueError, TypeError):
        raise ModalityFeasibilityCompositionError("invalid_feasibility_profile") from None
    for item in coverage:
        if not isinstance(item, FeasibilityDimensionCoverage):
            raise ModalityFeasibilityCompositionError("malformed_coverage")
        if (item.target_identifier != profile.target_identifier or
                item.target_identifier_type != profile.target_identifier_type or
                item.coverage_state not in _COVERAGE_STATES):
            raise ModalityFeasibilityCompositionError("malformed_coverage")
    return profile, coverage


@dataclass(frozen=True)
class ModalityFeasibilityAnnotation:
    """Immutable, source-linked feasibility context for one requested modality."""

    annotation_format_version: str
    target_identifier: str
    target_identifier_type: str
    requested_modality: str
    feasibility_profile_id: str
    source_name: str
    source_release: str
    release_verification_states: tuple[str, ...] | list[str]
    modality_specific_observation_ids: Mapping[str, tuple[str, ...] | list[str]]
    target_context_observation_ids: Mapping[str, tuple[str, ...] | list[str]]
    dimension_coverage: tuple[FeasibilityDimensionCoverage, ...] | list[FeasibilityDimensionCoverage]
    contradiction_observation_ids: tuple[str, ...] | list[str]
    limitations: tuple[str, ...] | list[str]
    research_only: bool = True
    no_score_calculated: bool = True
    no_ranking_modified: bool = True
    no_recommendation_generated: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_verification_states", tuple(sorted(set(self.release_verification_states))))
        object.__setattr__(self, "modality_specific_observation_ids", _freeze({key: tuple(sorted(set(value))) for key, value in self.modality_specific_observation_ids.items()}))
        object.__setattr__(self, "target_context_observation_ids", _freeze({key: tuple(sorted(set(value))) for key, value in self.target_context_observation_ids.items()}))
        object.__setattr__(self, "dimension_coverage", tuple(sorted(self.dimension_coverage, key=lambda item: (item.dimension, "" if item.modality is None else item.modality, item.coverage_id))))
        object.__setattr__(self, "contradiction_observation_ids", tuple(sorted(set(self.contradiction_observation_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        if (self.requested_modality not in THERAPEUTIC_MODALITIES or not self.feasibility_profile_id or
                not self.target_identifier or not self.target_identifier_type):
            raise ValueError("invalid modality feasibility annotation")
        if not (self.research_only and self.no_score_calculated and self.no_ranking_modified and self.no_recommendation_generated):
            raise ValueError("annotation boundaries must remain true")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "annotation_format_version": self.annotation_format_version,
            "target_identifier": self.target_identifier,
            "target_identifier_type": self.target_identifier_type,
            "requested_modality": self.requested_modality,
            "feasibility_profile_id": self.feasibility_profile_id,
            "source_name": self.source_name, "source_release": self.source_release,
            "release_verification_states": list(self.release_verification_states),
            "modality_specific_observation_ids": _thaw(self.modality_specific_observation_ids),
            "target_context_observation_ids": _thaw(self.target_context_observation_ids),
            "coverage_ids": [item.coverage_id for item in self.dimension_coverage],
            "contradiction_observation_ids": list(self.contradiction_observation_ids),
            "limitations": list(self.limitations), "research_only": True,
            "no_score_calculated": True, "no_ranking_modified": True,
            "no_recommendation_generated": True,
        }

    # Named read-only views keep the clinical and scientific distinction clear
    # to callers without duplicating observations or their source payloads.
    @property
    def modality_specific_tractability_observation_ids(self) -> tuple[str, ...]:
        return self.modality_specific_observation_ids["tractability"]

    @property
    def modality_specific_clinical_precedence_observation_ids(self) -> tuple[str, ...]:
        return self.modality_specific_observation_ids["clinical_precedence"]

    @property
    def modality_specific_doability_observation_ids(self) -> tuple[str, ...]:
        return self.modality_specific_observation_ids["doability"]

    @property
    def modality_specific_safety_observation_ids(self) -> tuple[str, ...]:
        return self.modality_specific_observation_ids["safety"]

    @property
    def target_context_clinical_precedence_observation_ids(self) -> tuple[str, ...]:
        return self.target_context_observation_ids["clinical_precedence"]

    @property
    def target_context_doability_observation_ids(self) -> tuple[str, ...]:
        return self.target_context_observation_ids["doability"]

    @property
    def target_context_safety_observation_ids(self) -> tuple[str, ...]:
        return self.target_context_observation_ids["safety"]

    @property
    def annotation_id(self) -> str:
        return _identity("mfa", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "annotation_id": self.annotation_id,
                "dimension_coverage": [item.to_dict() for item in self.dimension_coverage]}


@dataclass(frozen=True)
class ModalityAssessmentWithFeasibility:
    """Pure composition retaining a legacy :class:`ModalityCall` unchanged."""

    result_format_version: str
    original_assessment: ModalityCall
    original_assessment_id: str
    feasibility_annotation: ModalityFeasibilityAnnotation
    target_identifier: str
    target_identifier_type: str
    requested_modality: str
    limitations: tuple[str, ...] | list[str]
    original_assessment_unmodified: bool = True
    scores_unmodified: bool = True
    rankings_unmodified: bool = True
    no_recommendation_generated: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        if not (self.original_assessment_unmodified and self.scores_unmodified and self.rankings_unmodified and self.no_recommendation_generated):
            raise ValueError("composition boundaries must remain true")

    def identity_payload(self) -> dict[str, Any]:
        return {"result_format_version": self.result_format_version,
                "original_assessment_id": self.original_assessment_id,
                "annotation_id": self.feasibility_annotation.annotation_id,
                "target_identifier": self.target_identifier,
                "target_identifier_type": self.target_identifier_type,
                "requested_modality": self.requested_modality,
                "limitations": list(self.limitations), "original_assessment_unmodified": True,
                "scores_unmodified": True, "rankings_unmodified": True,
                "no_recommendation_generated": True}

    @property
    def result_id(self) -> str:
        return _identity("mawf", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "result_id": self.result_id,
                "original_assessment": asdict(self.original_assessment),
                "feasibility_annotation": self.feasibility_annotation.to_dict()}


def compose_modality_with_feasibility(
    modality_assessment: ModalityCall,
    feasibility_profile_or_build_result: TargetFeasibilityProfile | TargetFeasibilityProfileBuildResult,
    requested_modality: str,
    *,
    target_identifier: str,
    target_identifier_type: str,
) -> ModalityAssessmentWithFeasibility:
    """Attach descriptive feasibility context without changing a legacy call.

    ``target_identifier`` and ``target_identifier_type`` are explicit because
    ``ModalityCall`` predates feasibility contracts and deliberately contains
    no identity.  This function performs no profile construction or I/O.
    """
    if not isinstance(modality_assessment, ModalityCall):
        raise ModalityFeasibilityCompositionError("invalid_modality_assessment")
    modality = normalize_feasibility_modality(requested_modality)
    profile, supplied_coverage = _profile_and_coverage(feasibility_profile_or_build_result)
    if not isinstance(target_identifier, str) or not target_identifier:
        raise ModalityFeasibilityCompositionError("target_mismatch")
    if target_identifier != profile.target_identifier:
        raise ModalityFeasibilityCompositionError("target_mismatch")
    if target_identifier_type != profile.target_identifier_type:
        raise ModalityFeasibilityCompositionError("identifier_type_mismatch")

    specific = {dimension: tuple(item.observation_id for item in sorted(
        (item for item in profile.observations if item.dimension == dimension and item.modality == modality),
        key=_observation_sort_key)) for dimension in _FEASIBILITY_DIMENSIONS}
    contextual = {dimension: tuple(item.observation_id for item in sorted(
        (item for item in profile.observations if item.dimension == dimension and item.modality is None),
        key=_observation_sort_key)) for dimension in _FEASIBILITY_DIMENSIONS}
    selected = [item for item in profile.observations if item.observation_id in
                {identifier for values in (*specific.values(), *contextual.values()) for identifier in values}]
    contradictions = tuple(sorted(item.observation_id for item in selected
                                  if item.observation_id in profile.contradiction_indicators["observation_ids"]))
    release_states = tuple(sorted({str(item.provenance.get("release_verification_state"))
                                   for item in selected if item.provenance.get("release_verification_state") is not None}))
    coverage: list[FeasibilityDimensionCoverage] = []
    for dimension in _FEASIBILITY_DIMENSIONS:
        # Issue 403 has modality-specific coverage for tractability.  Future
        # explicitly modality-linked dimensions use their matching coverage if supplied.
        modality_coverage = [item for item in supplied_coverage if item.dimension == dimension and item.modality == modality]
        target_coverage = [item for item in supplied_coverage if item.dimension == dimension and item.modality is None]
        coverage.extend(modality_coverage or [_fallback_coverage(profile, dimension, modality)])
        coverage.extend(target_coverage or [_fallback_coverage(profile, dimension, None)])
    limitations = set(profile_observation_limitations for item in selected for profile_observation_limitations in item.limitations)
    limitations.add("feasibility_decorates_modality_assessment")
    limitations.add("no_modality_recommendation_generated")
    if not specific["tractability"]:
        limitations.add("requested_modality_tractability_not_available")
    original_id = _identity("mc", asdict(modality_assessment))
    annotation = ModalityFeasibilityAnnotation(
        "v0.4.0", profile.target_identifier, profile.target_identifier_type,
        modality, profile.profile_id, profile.source_name, profile.source_release,
        release_states, specific, contextual, coverage, contradictions, tuple(limitations),
    )
    return ModalityAssessmentWithFeasibility(
        "v0.4.0", modality_assessment, original_id, annotation,
        profile.target_identifier, profile.target_identifier_type, modality,
        ("feasibility_decorates_modality_assessment", "no_scores_modified", "no_rankings_modified", "no_recommendation_generated"),
    )
