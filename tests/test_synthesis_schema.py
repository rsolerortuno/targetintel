"""Strict response-schema tests for Issue 309."""
from __future__ import annotations

import pytest

from targetintel.llm.synthesis_schema import (
    TARGET_SYNTHESIS_SCHEMA_ID, TARGET_SYNTHESIS_SCHEMA_VERSION,
    parse_target_synthesis_response, target_synthesis_schema,
)


def _response():
    return {"schema_id": TARGET_SYNTHESIS_SCHEMA_ID, "schema_version": TARGET_SYNTHESIS_SCHEMA_VERSION,
            "snapshot_id": "snapshot", "inventory_id": "inventory", "target_identity": "B2M",
            "synthesis_purpose": "target_evidence_summary", "sections": ["supported_observations"],
            "statements": [{"local_statement_key": "s1", "section_identifier": "supported_observations",
                            "statement_text": "An observation is reported.", "evidence_item_ids": ["ev1"],
                            "support_relation": "supported", "uncertainty_level": "not_assessed"}],
            "evidence_coverage": [{"evidence_item_id": "ev1", "disposition": "cited"}],
            "research_only": True, "non_clinical_use": True}


def test_schema_has_stable_identity_and_validates_a_minimal_response():
    schema = target_synthesis_schema()
    assert schema["$id"] == f"{TARGET_SYNTHESIS_SCHEMA_ID}/{TARGET_SYNTHESIS_SCHEMA_VERSION}"
    assert schema["additionalProperties"] is False
    assert parse_target_synthesis_response(_response())["target_identity"] == "B2M"


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(unexpected=True),
    lambda value: value.pop("schema_id"),
    lambda value: value.update(schema_version="9.9.9"),
    lambda value: value["statements"][0].update(extra="no"),
    lambda value: value["statements"][0].update(evidence_item_ids=[]),
    lambda value: value["statements"][0].update(support_relation="proof"),
    lambda value: value["statements"][0].update(uncertainty_level=0.9),
    lambda value: value["evidence_coverage"][0].update(reason="bad"),
])
def test_schema_fails_closed_for_unknown_or_invalid_fields(mutate):
    value = _response(); mutate(value)
    with pytest.raises(ValueError):
        parse_target_synthesis_response(value)


def test_schema_requires_controlled_unsynthesized_reason_and_unique_coverage():
    value = _response()
    value["evidence_coverage"] = [{"evidence_item_id": "ev1", "disposition": "unsynthesized", "reason": "unknown"}]
    with pytest.raises(ValueError):
        parse_target_synthesis_response(value)
    value["evidence_coverage"][0]["reason"] = "duplicate_scientific_observation"
    assert parse_target_synthesis_response(value)["evidence_coverage"][0]["reason"] == "duplicate_scientific_observation"
