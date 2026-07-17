from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from targetintel.llm import audit_grounded_claims, extract_grounded_candidates
from targetintel.llm.human_review import (WarningDisposition, build_human_review_packet,
    create_human_review_decision, parse_human_review_decision)
from targetintel.llm.review_schema import REVIEW_SCHEMA_ID, REVIEW_SCHEMA_VERSION
from tests.test_grounded_extraction import _SUCCESS, _request, _response


def _objects():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS))
    audit=audit_grounded_claims(extraction,"doc-1",_request().source_text)
    return extraction,audit

def test_packet_is_deterministic_immutable_and_requires_human_review():
    extraction,audit=_objects()
    first=build_human_review_packet(extraction,audit,created_at=datetime(2024,1,1,tzinfo=timezone.utc))
    second=build_human_review_packet(extraction,audit,created_at=datetime(2025,1,1,tzinfo=timezone.utc))
    assert first.packet_id == second.packet_id
    assert first.entries[0].required_human_decision and first.research_only and first.not_clinical_validation
    assert isinstance(first.entries[0].audit_findings[0] if first.entries[0].audit_findings else {}, (MappingProxyType,dict))
    assert _request().source_text not in first.canonical_json()

def test_decision_is_strict_and_operational_time_is_not_identity():
    extraction,audit=_objects(); packet=build_human_review_packet(extraction,audit); card=audit.cards[0]
    kwargs=dict(packet_id=packet.packet_id,candidate_id=card.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="reject",decision_justification="Not promoted.")
    assert REVIEW_SCHEMA_ID and REVIEW_SCHEMA_VERSION
    assert create_human_review_decision(**kwargs,reviewed_at=datetime(2024,1,1,tzinfo=timezone.utc)).review_decision_id == create_human_review_decision(**kwargs,reviewed_at=datetime(2025,1,1,tzinfo=timezone.utc)).review_decision_id
    with pytest.raises(ValueError): create_human_review_decision(**(kwargs | {"reviewer_id":""}))
    with pytest.raises(ValueError): WarningDisposition("x","accepted_with_justification",None)

def test_strict_parser_round_trips_serialized_json_and_rejects_tampering():
    extraction,audit=_objects(); packet=build_human_review_packet(extraction,audit); card=audit.cards[0]
    decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=card.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="reject",decision_justification="No promotion.",reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    assert parse_human_review_decision(decision.to_dict()).to_dict() == decision.to_dict()
    for update in ({"thinking":"hidden"}, {"review_decision_id":"not-the-calculated-id"}):
        with pytest.raises(ValueError): parse_human_review_decision(decision.to_dict() | update)
