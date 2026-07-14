"""Deterministic intrinsic validation for evidence-layer contracts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
from types import MappingProxyType
from typing import Any
from collections.abc import Mapping

from . import models


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


class ValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(f"{issue.field}: {issue.message}" for issue in issues))


@dataclass(frozen=True)
class SemanticValidationContext:
    """Read-only records available for validating derived-evidence lineage.

    The candidate being validated is added to this context transiently.  The
    validator never changes either the candidate or these parent records.
    """

    evidence_items: Mapping[str, models.EvidenceItem]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_items", MappingProxyType(dict(self.evidence_items)))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc_datetime(value: Any) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _issue_if_not_string(issues: list[ValidationIssue], field: str, value: Any, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not _non_empty_string(value):
        issues.append(ValidationIssue(field, "must be a non-empty string"))


def validate_intrinsic(item: models.EvidenceItem) -> list[ValidationIssue]:
    """Validate only field-local Issue 202 contract rules, without semantics."""
    issues: list[ValidationIssue] = []
    required_strings = ("evidence_id", "target_symbol", "disease_name", "disease_id", "evidence_type", "evidence_direction", "observation", "source", "source_id", "species", "model_system", "extraction_method", "validation_status", "evidence_family_algorithm_version", "evidence_family_basis")
    optional_strings = ("target_id", "treatment_name", "treatment_id", "interpretation", "document_location", "quoted_span", "computed_support", "publication_id", "source_dataset_id", "patient_cohort_id", "experiment_id", "comparison", "endpoint", "data_modality", "sample_context", "effect_size_metric", "uncertainty_metric", "data_release", "evidence_family", "independence_ineligibility_reason", "record_hash")
    for field in required_strings:
        _issue_if_not_string(issues, field, getattr(item, field))
    for field in optional_strings:
        _issue_if_not_string(issues, field, getattr(item, field), nullable=True)

    vocabularies = (("evidence_type", models.EVIDENCE_TYPES), ("evidence_direction", models.EVIDENCE_DIRECTIONS), ("species", models.SPECIES), ("model_system", models.MODEL_SYSTEMS), ("extraction_method", models.EXTRACTION_METHODS), ("validation_status", models.VALIDATION_STATUSES), ("evidence_family_basis", models.FAMILY_BASES))
    for field, allowed in vocabularies:
        if getattr(item, field) not in allowed:
            issues.append(ValidationIssue(field, "is not an allowed controlled-vocabulary value"))
    if item.evidence_family_algorithm_version != models.FAMILY_ALGORITHM_VERSION:
        issues.append(ValidationIssue("evidence_family_algorithm_version", "must be 'efam-v1'"))
    if not isinstance(item.independence_eligible, bool):
        issues.append(ValidationIssue("independence_eligible", "must be a boolean"))
    if item.independence_eligible is False:
        if item.evidence_family_basis != "ineligible":
            issues.append(ValidationIssue("evidence_family_basis", "must be 'ineligible' when independence_eligible is false"))
        if item.evidence_family is not None:
            issues.append(ValidationIssue("evidence_family", "must be null when independence_eligible is false"))
        if not _non_empty_string(item.independence_ineligibility_reason):
            issues.append(ValidationIssue("independence_ineligibility_reason", "must be non-empty when independence_eligible is false"))

    for field in ("effect_size", "uncertainty", "extraction_confidence"):
        value = getattr(item, field)
        if value is not None and not _is_number(value):
            issues.append(ValidationIssue(field, "must be a finite number or null"))
    if item.extraction_confidence is not None and _is_number(item.extraction_confidence) and not 0 <= item.extraction_confidence <= 1:
        issues.append(ValidationIssue("extraction_confidence", "must be in [0, 1]"))
    if item.sample_size is not None and (not isinstance(item.sample_size, int) or isinstance(item.sample_size, bool) or item.sample_size <= 0):
        issues.append(ValidationIssue("sample_size", "must be a positive integer or null"))
    if not _utc_datetime(item.retrieved_at):
        issues.append(ValidationIssue("retrieved_at", "must be a timezone-aware UTC datetime"))
    if not isinstance(item.derived_from, tuple) or not all(_non_empty_string(parent) for parent in item.derived_from):
        issues.append(ValidationIssue("derived_from", "must be a list of non-empty strings"))
    if not isinstance(item.provenance_history, tuple) or not all(isinstance(step, models.ProvenanceStep) for step in item.provenance_history):
        issues.append(ValidationIssue("provenance_history", "must be a list of ProvenanceStep values"))
    for index, step in enumerate(item.provenance_history):
        if not _non_empty_string(step.step_type):
            issues.append(ValidationIssue(f"provenance_history[{index}].step_type", "must be a non-empty string"))
        if not _utc_datetime(step.recorded_at):
            issues.append(ValidationIssue(f"provenance_history[{index}].recorded_at", "must be a timezone-aware UTC datetime"))
        if not isinstance(step.details, Mapping):
            issues.append(ValidationIssue(f"provenance_history[{index}].details", "must be a mapping"))
        if not isinstance(step.is_operational, bool):
            issues.append(ValidationIssue(f"provenance_history[{index}].is_operational", "must be a boolean"))
    if item.record_hash is not None and (not isinstance(item.record_hash, str) or re.fullmatch(r"[0-9a-f]{64}", item.record_hash) is None):
        issues.append(ValidationIssue("record_hash", "must be a lowercase SHA-256 hexadecimal digest or null"))
    return issues


def _has_text(value: Any) -> bool:
    return _non_empty_string(value)


_GENERIC_PROVENANCE_IDENTIFIERS = frozenset({
    "unknown", "none", "missing", "null", "n/a", "na", "not_applicable",
    "not available", "unspecified",
})


def _has_stable_source_identity(item: models.EvidenceItem) -> bool:
    """Apply the contract's generic-placeholder rule to source identity."""
    return all(
        _has_text(value) and value.strip().casefold() not in _GENERIC_PROVENANCE_IDENTIFIERS
        for value in (item.source, item.source_id)
    )


def _has_successful_citation_verification(item: models.EvidenceItem) -> bool:
    """Return whether frozen provenance explicitly records a successful check."""
    return any(
        step.step_type == "citation_verification"
        and (step.details.get("success") is True or step.details.get("status") == "success")
        for step in item.provenance_history
    )


def _has_complete_manual_review(item: models.EvidenceItem) -> bool:
    """Return whether a review step retains all required manual-review audit data."""
    for step in item.provenance_history:
        if step.step_type != "manual_review":
            continue
        details = step.details
        if (
            _has_text(details.get("curator_id"))
            and _has_text(details.get("review_rationale"))
            and (
                _has_text(details.get("reviewed_source_material"))
                or _has_text(details.get("reviewed_computed_output"))
            )
        ):
            # The provenance step's recorded_at is the immutable review timestamp.
            return True
    return False


def _lineage_issues(
    item: models.EvidenceItem, context: SemanticValidationContext | None
) -> list[ValidationIssue]:
    if not item.derived_from:
        return []
    available = {} if context is None else dict(context.evidence_items)
    available[item.evidence_id] = item
    issues: list[ValidationIssue] = []
    for parent_id in item.derived_from:
        if parent_id not in available:
            issues.append(ValidationIssue("derived_from", f"parent '{parent_id}' does not resolve in validation context"))

    # Continue only over resolvable links, which keeps dangling-parent errors
    # deterministic and avoids treating unavailable records as scientific data.
    def visit(record_id: str, path: tuple[str, ...]) -> None:
        record = available.get(record_id)
        if record is None:
            return
        for parent_id in record.derived_from:
            if parent_id not in available:
                continue
            if parent_id in path:
                cycle = " -> ".join((*path, parent_id))
                issues.append(ValidationIssue("derived_from", f"derived-evidence graph contains cycle: {cycle}"))
                continue
            visit(parent_id, (*path, parent_id))

    visit(item.evidence_id, (item.evidence_id,))
    return issues


def validate_semantic(
    item: models.EvidenceItem,
    context: SemanticValidationContext | None = None,
) -> list[ValidationIssue]:
    """Validate deterministic cross-field evidence rules without mutation or I/O."""
    issues: list[ValidationIssue] = []
    computed_or_database = item.extraction_method in {"computed", "database_import"} or item.evidence_type == "database_assertion"
    literature = _has_text(item.publication_id) or item.validation_status == "citation_verified"

    if computed_or_database and not _has_text(item.computed_support):
        issues.append(ValidationIssue("computed_support", "must be non-empty for computed or database-derived evidence"))
    if literature and not _has_text(item.quoted_span):
        issues.append(ValidationIssue("quoted_span", "must be non-empty for literature evidence"))
    if not computed_or_database and not literature and not (_has_text(item.quoted_span) or _has_text(item.computed_support)):
        issues.append(ValidationIssue("quoted_span", "or computed_support must provide auditable support"))

    if item.validation_status == "citation_verified" and not _has_successful_citation_verification(item):
        issues.append(ValidationIssue("validation_status", "citation_verified requires successful citation_verification provenance"))
    if item.validation_status == "manually_curated":
        if not _has_stable_source_identity(item):
            issues.append(ValidationIssue("source_id", "manually_curated requires a stable non-generic source identity"))
        if not _has_complete_manual_review(item):
            issues.append(ValidationIssue("provenance_history", "manually_curated requires manual_review provenance with curator_id, review timestamp, review_rationale, and reviewed material or output"))
        if not (_has_text(item.quoted_span) or _has_text(item.computed_support)):
            issues.append(ValidationIssue("quoted_span", "or computed_support must provide auditable support for manually_curated evidence"))

    if item.independence_eligible:
        if not _has_text(item.evidence_family):
            issues.append(ValidationIssue("evidence_family", "must be non-null when independence_eligible is true"))
        if item.evidence_family_basis == "ineligible":
            issues.append(ValidationIssue("evidence_family_basis", "must not be 'ineligible' when independence_eligible is true"))
        if item.independence_ineligibility_reason is not None:
            issues.append(ValidationIssue("independence_ineligibility_reason", "must be null when independence_eligible is true"))
    else:
        # Intrinsic validation checks these too; retaining the semantic rule
        # makes this API independently useful to candidate finalizers.
        if item.evidence_family is not None:
            issues.append(ValidationIssue("evidence_family", "must be null when independence_eligible is false"))
        if item.evidence_family_basis != "ineligible":
            issues.append(ValidationIssue("evidence_family_basis", "must be 'ineligible' when independence_eligible is false"))
        if not _has_text(item.independence_ineligibility_reason):
            issues.append(ValidationIssue("independence_ineligibility_reason", "must be non-empty when independence_eligible is false"))

    if (item.effect_size is None) != (item.effect_size_metric is None):
        issues.append(ValidationIssue("effect_size_metric", "must be present exactly when effect_size is present"))
    # v0.2.0 defines no p-value field or uncertainty-metric vocabulary.  Its
    # only approved cross-field uncertainty rule is the paired value/metric
    # requirement below; positive sample_size is a field-local intrinsic rule.
    # Do not infer a p-value/sample-size relationship from free text.
    if (item.uncertainty is None) != (item.uncertainty_metric is None):
        issues.append(ValidationIssue("uncertainty_metric", "must be present exactly when uncertainty is present"))

    if item.evidence_type == "clinical_cohort" and not _has_text(item.patient_cohort_id):
        issues.append(ValidationIssue("patient_cohort_id", "is required for clinical_cohort evidence"))
    if item.model_system == "patient_tumor_biopsy" and not _has_text(item.patient_cohort_id):
        issues.append(ValidationIssue("patient_cohort_id", "is required for patient_tumor_biopsy evidence"))
    if item.evidence_type in {"in_vivo_model", "in_vitro_model", "functional_genomics"} and not _has_text(item.experiment_id):
        issues.append(ValidationIssue("experiment_id", "is required for experimental evidence"))
    if (_has_text(item.comparison) or _has_text(item.endpoint)) and not (_has_text(item.patient_cohort_id) or _has_text(item.experiment_id)):
        issues.append(ValidationIssue("comparison", "and endpoint require patient_cohort_id or experiment_id context"))

    if item.extraction_method == "mock" and item.interpretation is not None:
        issues.append(ValidationIssue("interpretation", "must be null for v0.2.0 mock extraction"))

    issues.extend(_lineage_issues(item, context))
    return issues


def validate_retrieval_attempt_intrinsic(attempt: models.RetrievalAttempt) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for field in ("retrieval_attempt_id", "target_identifier", "disease_context", "source", "query", "status"):
        _issue_if_not_string(issues, field, getattr(attempt, field))
    for field in ("treatment_context", "error_category", "source_release_or_api_version"):
        _issue_if_not_string(issues, field, getattr(attempt, field), nullable=True)
    if attempt.status not in models.RETRIEVAL_STATUSES:
        issues.append(ValidationIssue("status", "is not an allowed retrieval status"))
    if not _utc_datetime(attempt.timestamp):
        issues.append(ValidationIssue("timestamp", "must be a timezone-aware UTC datetime"))
    if attempt.result_count is not None and (not isinstance(attempt.result_count, int) or isinstance(attempt.result_count, bool) or attempt.result_count < 0):
        issues.append(ValidationIssue("result_count", "must be a non-negative integer or null"))
    if attempt.status == "success" and attempt.result_count is None:
        issues.append(ValidationIssue("result_count", "is required for success"))
    if attempt.status == "success_zero_results" and attempt.result_count != 0:
        issues.append(ValidationIssue("result_count", "must be 0 for success_zero_results"))
    if attempt.status in {"not_executed", "failed"} and attempt.result_count is not None:
        issues.append(ValidationIssue("result_count", "must be null for this status"))
    if attempt.status == "failed" and not _non_empty_string(attempt.error_category):
        issues.append(ValidationIssue("error_category", "must be non-empty for failed retrieval"))
    if attempt.status != "failed" and attempt.error_category is not None:
        issues.append(ValidationIssue("error_category", "must be null unless status is failed"))
    return issues


def require_valid(item: models.EvidenceItem) -> None:
    issues = validate_intrinsic(item)
    if issues:
        raise ValidationError(issues)


def require_semantically_valid(
    item: models.EvidenceItem,
    context: SemanticValidationContext | None = None,
) -> None:
    """Raise deterministic validation errors for semantic cross-field rules."""
    issues = validate_semantic(item, context)
    if issues:
        raise ValidationError(issues)


def require_finalizable(
    item: models.EvidenceItem,
    context: SemanticValidationContext | None = None,
) -> None:
    issues = validate_intrinsic(item)
    issues.extend(validate_semantic(item, context))
    if item.validation_status not in models.FINAL_VALIDATION_STATUSES:
        issues.append(ValidationIssue("validation_status", "must be finalized before hashing"))
    if item.evidence_family_algorithm_version != models.FAMILY_ALGORITHM_VERSION:
        issues.append(ValidationIssue("evidence_family_algorithm_version", "must be assigned before hashing"))
    if item.evidence_family_basis not in models.FAMILY_BASES:
        issues.append(ValidationIssue("evidence_family_basis", "must be assigned before hashing"))
    if issues:
        raise ValidationError(issues)


def require_valid_retrieval_attempt(attempt: models.RetrievalAttempt) -> None:
    issues = validate_retrieval_attempt_intrinsic(attempt)
    if issues:
        raise ValidationError(issues)
