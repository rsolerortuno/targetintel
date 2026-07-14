"""Issue 202 deterministic intrinsic validation tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from targetintel.evidence.models import RetrievalAttempt
from targetintel.evidence.validation import ValidationError, require_finalizable, require_valid, require_valid_retrieval_attempt, validate_intrinsic
from tests.test_evidence_models import UTC, evidence_item


@pytest.mark.parametrize(
    ("field", "value"),
    [("target_symbol", None), ("evidence_type", "not_a_type"), ("species", "dog"), ("sample_size", 0), ("extraction_confidence", 1.01)],
)
def test_required_type_enum_and_range_failures_are_deterministic(field: str, value: object) -> None:
    issues = validate_intrinsic(replace(evidence_item(), **{field: value}))

    assert any(issue.field == field for issue in issues)


def test_datetime_must_be_timezone_aware_utc() -> None:
    issues = validate_intrinsic(replace(evidence_item(), retrieved_at=datetime(2026, 7, 12)))

    assert any(issue.field == "retrieved_at" for issue in issues)


def test_ineligible_marker_fields_are_required_and_algorithm_is_fixed() -> None:
    item = replace(evidence_item(), evidence_family_basis="publication_id", independence_ineligibility_reason=None, evidence_family_algorithm_version="efam-v2")
    issues = validate_intrinsic(item)

    assert {issue.field for issue in issues} >= {"evidence_family_basis", "independence_ineligibility_reason", "evidence_family_algorithm_version"}


def test_hashing_requires_final_status_and_final_family_metadata() -> None:
    item = replace(evidence_item(), validation_status="extracted")

    with pytest.raises(ValidationError, match="finalized before hashing"):
        require_finalizable(item)


@pytest.mark.parametrize(
    ("status", "result_count", "error_category", "valid"),
    [("success", 2, None, True), ("success_zero_results", 0, None, True), ("not_executed", None, None, True), ("failed", None, "network", True), ("failed", None, "", False), ("success_zero_results", 1, None, False), ("not_executed", 0, None, False)],
)
def test_retrieval_status_combinations(status: str, result_count: int | None, error_category: str | None, valid: bool) -> None:
    attempt = RetrievalAttempt("ra", "MOCK1", "melanoma", None, "source", "query", UTC, status, result_count, error_category, None)

    if valid:
        require_valid_retrieval_attempt(attempt)
    else:
        with pytest.raises(ValidationError):
            require_valid_retrieval_attempt(attempt)


def test_valid_item_passes_intrinsic_validation() -> None:
    require_valid(evidence_item())
