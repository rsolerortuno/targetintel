from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import pytest

from targetintel.llm import audit_grounded_claims, extract_grounded_candidates
from targetintel.llm.evidence_promotion import (EvidencePromotionRequest, promote_candidate_to_evidence,
    required_evidence_mapping_fields)
from targetintel.llm.human_review import WarningDisposition, build_human_review_packet, create_human_review_decision
from targetintel.llm.contracts import canonical_json
from tests.test_grounded_extraction import _SUCCESS, _request, _response
from tests.test_claim_audit import SOURCE, _claim, _extraction

def _mapping(source_id="doc-1"):
    return {"target_symbol":"B2M","target_id":None,"disease_name":"melanoma","disease_id":"MONDO:0005105","treatment_name":None,"treatment_id":None,"evidence_type":"genetic_association","evidence_direction":"supports_biomarker","observation":"B2M loss was observed.","interpretation":"Reviewer-recorded interpretation.","source":"local document","source_id":source_id,"document_location":None,"computed_support":None,"publication_id":None,"source_dataset_id":None,"patient_cohort_id":None,"experiment_id":None,"comparison":None,"endpoint":None,"data_modality":None,"species":"human","model_system":"other","sample_context":None,"effect_size":None,"effect_size_metric":None,"uncertainty":None,"uncertainty_metric":None,"sample_size":None,"extraction_method":"manual","extraction_confidence":None,"validation_status":"manually_curated","retrieved_at":datetime(2026,1,1,tzinfo=timezone.utc),"data_release":None,"derived_from":(),"evidence_family":None,"evidence_family_algorithm_version":"efam-v1","evidence_family_basis":"ineligible","independence_eligible":False,"independence_ineligibility_reason":"No evidence-family assignment is supplied."}

def test_reject_and_defer_never_construct_evidence():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit)
    candidate,card=extraction.accepted_candidates[0],audit.cards[0]
    for decision,status in (("reject","rejected_by_reviewer"),("defer","deferred_by_reviewer")):
        reviewed=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision=decision,decision_justification="Recorded decision.")
        request=EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,reviewed,candidate.candidate_id,{})
        result=promote_candidate_to_evidence(request)
        assert result.status == status and result.evidence_item is None and not result.persisted

def test_unknown_or_missing_mapping_fails_closed_before_construction():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit)
    candidate,card=extraction.accepted_candidates[0],audit.cards[0]
    mapping={"unknown":"field"}
    with pytest.raises(ValueError):
        create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=mapping)
    assert "target_symbol" in required_evidence_mapping_fields()

def test_explicit_valid_approval_constructs_one_in_memory_item():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit)
    candidate,card=extraction.accepted_candidates[0],audit.cards[0]
    mapping=_mapping()
    reviewed=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit review approval.",evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    result=promote_candidate_to_evidence(EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,reviewed,candidate.candidate_id,mapping))
    assert result.status == "promoted" and result.evidence_item is not None and not result.persisted
    assert result.evidence_item.observation == mapping["observation"] and result.evidence_item.interpretation == mapping["interpretation"]

def test_malformed_contracts_fail_closed_at_request_boundary_and_service_fallback():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit); candidate,card=extraction.accepted_candidates[0],audit.cards[0]
    reviewed=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="reject",decision_justification="Recorded decision.")
    with pytest.raises(ValueError): EvidencePromotionRequest(_request().source_text,"doc-1",extraction,None,packet,reviewed,candidate.candidate_id,{})
    request=EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,reviewed,candidate.candidate_id,{})
    object.__setattr__(request,"audit_result",None)
    result=promote_candidate_to_evidence(request)
    assert result.status == "invalid_input" and result.evidence_item is None and result.audit_result_id is None

def test_audit_review_block_and_grounding_gates_fail_closed():
    warning_extraction=_extraction(_claim("B2M causes response and proves benefit.")); warning_audit=audit_grounded_claims(warning_extraction,"audit-doc",SOURCE); warning_packet=build_human_review_packet(warning_extraction,warning_audit); candidate,card=warning_extraction.accepted_candidates[0],warning_audit.cards[0]; mapping=_mapping("audit-doc")
    approve=lambda dispositions: create_human_review_decision(packet_id=warning_packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=warning_audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",warning_dispositions=dispositions,evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    missing=promote_candidate_to_evidence(EvidencePromotionRequest(SOURCE,"audit-doc",warning_extraction,warning_audit,warning_packet,approve(()),candidate.candidate_id,mapping))
    assert card.release_decision == "review" and missing.status == "warning_disposition_required" and missing.evidence_item is None
    warnings=tuple(WarningDisposition(f.rule_id,"accepted_with_justification","Recorded disposition.") for f in card.findings if f.severity == "warning")
    duplicate=promote_candidate_to_evidence(EvidencePromotionRequest(SOURCE,"audit-doc",warning_extraction,warning_audit,warning_packet,approve(warnings + warnings[:1]),candidate.candidate_id,mapping))
    assert duplicate.status == "warning_disposition_required"
    block_extraction=_extraction(_claim("Patients should receive B2M therapy at a 10 mg dose.")); block_audit=audit_grounded_claims(block_extraction,"audit-doc",SOURCE); block_packet=build_human_review_packet(block_extraction,block_audit); blocked_candidate,blocked_card=block_extraction.accepted_candidates[0],block_audit.cards[0]
    blocked=create_human_review_decision(packet_id=block_packet.packet_id,candidate_id=blocked_candidate.candidate_id,card_id=blocked_card.card_id,audit_result_id=block_audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Cannot override blocker.",evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    result=promote_candidate_to_evidence(EvidencePromotionRequest(SOURCE,"audit-doc",block_extraction,block_audit,block_packet,blocked,blocked_candidate.candidate_id,mapping))
    assert blocked_card.release_decision == "block" and result.status == "blocked_by_audit" and result.evidence_item is None

def test_identity_grounding_mapping_and_validation_failures_are_not_promoted():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit); candidate,card=extraction.accepted_candidates[0],audit.cards[0]; mapping=_mapping()
    decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    base=EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,decision,candidate.candidate_id,mapping)
    assert promote_candidate_to_evidence(base).status == "promoted"
    bad_source=EvidencePromotionRequest(_request().source_text + " changed","doc-1",extraction,audit,packet,decision,candidate.candidate_id,mapping)
    assert promote_candidate_to_evidence(bad_source).status == "invalid_grounding"
    object.__setattr__(decision,"packet_id","wrong-packet")
    assert promote_candidate_to_evidence(base).status == "identity_mismatch"
    invalid_mapping=dict(mapping); invalid_mapping["observation"]=""
    invalid_decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=invalid_mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    validation=promote_candidate_to_evidence(EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,invalid_decision,candidate.candidate_id,invalid_mapping))
    assert validation.status == "evidence_validation_failed" and validation.evidence_item is None and "observation" in validation.validation_findings

def test_packet_source_identity_and_hash_must_match_all_promotion_inputs():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit); candidate,card=extraction.accepted_candidates[0],audit.cards[0]; mapping=_mapping()
    for changes in ({"source_document_id":"other-document"},{"source_content_hash":"not-the-source-hash"}):
        proto=replace(packet,packet_id="",**changes)
        tampered_packet=replace(proto,packet_id=sha256(canonical_json(proto.identity_payload()).encode("utf-8")).hexdigest())
        decision=create_human_review_decision(packet_id=tampered_packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
        result=promote_candidate_to_evidence(EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,tampered_packet,decision,candidate.candidate_id,mapping))
        assert result.status == "invalid_grounding" and result.evidence_item is None

def test_selection_mapping_and_result_identity_boundaries_are_deterministic_and_immutable():
    extraction=extract_grounded_candidates(_request(),_response(_SUCCESS)); audit=audit_grounded_claims(extraction,"doc-1",_request().source_text); packet=build_human_review_packet(extraction,audit); candidate,card=extraction.accepted_candidates[0],audit.cards[0]; mapping=_mapping()
    decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    request=EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,decision,candidate.candidate_id,mapping)
    first,second=promote_candidate_to_evidence(request),promote_candidate_to_evidence(request)
    assert first.status == "promoted" and first.promotion_result_id == second.promotion_result_id
    with pytest.raises(TypeError): request.evidence_mapping["observation"]="changed"
    unknown=EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,decision,"not-a-candidate",mapping)
    assert promote_candidate_to_evidence(unknown).status == "invalid_input"
    missing=dict(mapping); del missing["observation"]
    missing_decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",evidence_mapping=missing,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    assert promote_candidate_to_evidence(EvidencePromotionRequest(_request().source_text,"doc-1",extraction,audit,packet,missing_decision,candidate.candidate_id,missing)).status == "invalid_mapping"

def test_warning_disposition_identifiers_must_be_complete_and_known():
    extraction=_extraction(_claim("B2M causes response and proves benefit.")); audit=audit_grounded_claims(extraction,"audit-doc",SOURCE); packet=build_human_review_packet(extraction,audit); candidate,card=extraction.accepted_candidates[0],audit.cards[0]; mapping=_mapping("audit-doc")
    unknown=(WarningDisposition("not-a-card-rule","accepted_with_justification","Recorded disposition."),)
    decision=create_human_review_decision(packet_id=packet.packet_id,candidate_id=candidate.candidate_id,card_id=card.card_id,audit_result_id=audit.audit_result_id,reviewer_id="reviewer-001",decision="approve",decision_justification="Explicit approval.",warning_dispositions=unknown,evidence_mapping=mapping,reviewed_at=datetime(2026,1,2,tzinfo=timezone.utc))
    assert promote_candidate_to_evidence(EvidencePromotionRequest(SOURCE,"audit-doc",extraction,audit,packet,decision,candidate.candidate_id,mapping)).status == "warning_disposition_required"
