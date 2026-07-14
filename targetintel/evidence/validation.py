"""Deterministic intrinsic validation for evidence-layer contracts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
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


def require_finalizable(item: models.EvidenceItem) -> None:
    issues = validate_intrinsic(item)
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
