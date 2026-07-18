"""Offline contract coverage for Issue 309 synthesis models."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from targetintel.llm.synthesis_models import (
    TARGET_SYNTHESIS_REQUEST_SCHEMA_ID,
    TARGET_SYNTHESIS_REQUEST_SCHEMA_VERSION,
    TargetSynthesisRequest,
)


def _values(**changes):
    values = {
        "snapshot_id": "snapshot-1", "snapshot_manifest_hash": "manifest-1",
        "target_identity": "B2M", "context": "melanoma",
        "synthesis_purpose": "target_evidence_summary",
        "requested_sections": ["limitations", "supported_observations"],
        "maximum_statement_count": 3, "maximum_words_per_statement": 40,
        "requesting_actor_id": "researcher", "language": "en",
    }
    values.update(changes)
    return values


def test_request_contract_is_immutable_canonical_and_timestamp_independent():
    first = TargetSynthesisRequest.create(**_values())
    second = TargetSynthesisRequest.create(**_values(requested_sections=["supported_observations", "limitations"], requested_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert first.request_schema_id == TARGET_SYNTHESIS_REQUEST_SCHEMA_ID
    assert first.request_schema_version == TARGET_SYNTHESIS_REQUEST_SCHEMA_VERSION
    assert first.request_id == second.request_id
    assert first.requested_sections == ("supported_observations", "limitations")
    assert first.canonical_json() == TargetSynthesisRequest.from_dict(first.to_dict()).canonical_json()
    with pytest.raises(FrozenInstanceError):
        first.target_identity = "OTHER"


@pytest.mark.parametrize("field,value", [
    ("snapshot_id", ""), ("snapshot_manifest_hash", ""), ("target_identity", ""),
    ("requesting_actor_id", ""), ("synthesis_purpose", "unknown"), ("language", "es"),
    ("requested_sections", ["clinical_treatment"]), ("requested_sections", ["score"]),
    ("requested_sections", ["ranking"]), ("requested_sections", ["limitations", "limitations"]),
    ("maximum_statement_count", 0), ("maximum_words_per_statement", 0),
])
def test_request_rejects_invalid_controlled_values(field, value):
    with pytest.raises(ValueError):
        TargetSynthesisRequest.create(**_values(**{field: value}))


@pytest.mark.parametrize("unsafe", [
    {"api_key": "x"}, {"nested": {"credential": "x"}},
    {"thinking": "hidden"}, {"reasoning": "hidden"},
])
def test_request_rejects_recursive_secrets_and_hidden_reasoning(unsafe):
    values = _values(**unsafe)
    with pytest.raises(ValueError):
        TargetSynthesisRequest.create(**values)


def test_request_from_dict_rejects_unknown_fields_and_bad_identity():
    request = TargetSynthesisRequest.create(**_values())
    payload = request.to_dict() | {"unexpected": "no"}
    with pytest.raises(ValueError):
        TargetSynthesisRequest.from_dict(payload)
    payload = request.to_dict() | {"request_id": "wrong"}
    with pytest.raises(ValueError):
        TargetSynthesisRequest.from_dict(payload)
