"""Pure, fail-closed in-memory promotion of one human-approved candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from targetintel.evidence.models import EvidenceItem, ProvenanceStep
from targetintel.evidence.validation import ValidationError, require_finalizable

from .claim_audit import ClaimBoundaryCard, ScientificClaimAuditResult
from .contracts import _freeze, _thaw, canonical_json
from .grounded_extraction import GroundedClaimCandidate, GroundedExtractionResult
from .human_review import (HumanReviewDecision, HumanReviewPacket, WarningDisposition,
                           eligibility_for)
from .review_schema import reject_unsafe

PROMOTION_FORMAT_VERSION = "evidence-promotion-result-v1"
PROMOTION_STATUSES = frozenset({"promoted","rejected_by_reviewer","deferred_by_reviewer","blocked_by_audit","warning_disposition_required","invalid_review","invalid_mapping","invalid_grounding","identity_mismatch","evidence_validation_failed","invalid_input"})
_ITEM_FIELDS = frozenset(EvidenceItem.__dataclass_fields__)
# Identity, grounded quote, and review-chain provenance are constructed only from
# immutable input contracts; all scientific/content fields remain explicit.
_MAPPING_FIELDS = _ITEM_FIELDS.difference({"evidence_id", "record_hash", "quoted_span", "provenance_history"})

def required_evidence_mapping_fields() -> tuple[str, ...]: return tuple(sorted(_MAPPING_FIELDS))
def _hash(value: Mapping[str, Any]) -> str: return sha256(canonical_json(value).encode("utf-8")).hexdigest()
def _findings(exc: ValidationError) -> tuple[str, ...]: return tuple(sorted({issue.field for issue in exc.issues}))

@dataclass(frozen=True)
class EvidencePromotionRequest:
    source_text: str; source_document_id: str; grounded_extraction: GroundedExtractionResult; audit_result: ScientificClaimAuditResult; review_packet: HumanReviewPacket; review_decision: HumanReviewDecision; selected_candidate_id: str; evidence_mapping: Mapping[str, Any]
    def __post_init__(self) -> None:
        if not isinstance(self.source_text,str) or not isinstance(self.source_document_id,str) or not self.source_document_id: raise ValueError("source view and source document identity are required")
        if not isinstance(self.grounded_extraction, GroundedExtractionResult): raise ValueError("grounded extraction must be GroundedExtractionResult")
        if not isinstance(self.audit_result, ScientificClaimAuditResult): raise ValueError("audit result must be ScientificClaimAuditResult")
        if not isinstance(self.review_packet, HumanReviewPacket): raise ValueError("review packet must be HumanReviewPacket")
        if not isinstance(self.review_decision, HumanReviewDecision): raise ValueError("review decision must be HumanReviewDecision")
        if not isinstance(self.selected_candidate_id, str) or not self.selected_candidate_id: raise ValueError("selected candidate identity is required")
        if not isinstance(self.evidence_mapping, Mapping): raise ValueError("evidence mapping must be an object")
        reject_unsafe(self.evidence_mapping); object.__setattr__(self,"evidence_mapping",_freeze(self.evidence_mapping))

@dataclass(frozen=True)
class EvidencePromotionResult:
    promotion_format_version: str; promotion_result_id: str; status: str; candidate_id: str; card_id: str | None; audit_result_id: str | None; packet_id: str | None; review_decision_id: str | None; reviewer_id: str | None; evidence_item_id: str | None; evidence_item: EvidenceItem | None; validation_findings: tuple[str, ...]; persisted: bool = False
    def __post_init__(self) -> None:
        if self.status not in PROMOTION_STATUSES: raise ValueError("unknown promotion status")
        if (self.status == "promoted") != (self.evidence_item is not None): raise ValueError("only promoted results may contain EvidenceItem")
        object.__setattr__(self,"validation_findings",tuple(self.validation_findings))
    def identity_payload(self) -> dict[str, Any]: return {"promotion_format_version":self.promotion_format_version,"status":self.status,"candidate_id":self.candidate_id,"card_id":self.card_id,"audit_result_id":self.audit_result_id,"packet_id":self.packet_id,"review_decision_id":self.review_decision_id,"reviewer_id":self.reviewer_id,"evidence_item_id":self.evidence_item_id,"validation_findings":list(self.validation_findings),"persisted":False}
    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload() | {"promotion_result_id":self.promotion_result_id,"evidence_item":None if self.evidence_item is None else self.evidence_item.to_dict()}
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

def _result(request: EvidencePromotionRequest, status: str, *, candidate_id: str | None = None, card: ClaimBoundaryCard | None = None, findings: tuple[str,...] = (), item: EvidenceItem | None = None) -> EvidencePromotionResult:
    # Keep the fail-closed fallback safe even when a caller bypasses the
    # dataclass constructor (for example through unsafe object mutation).
    decision=request.review_decision if isinstance(request.review_decision, HumanReviewDecision) else None
    audit=request.audit_result if isinstance(request.audit_result, ScientificClaimAuditResult) else None
    packet=request.review_packet if isinstance(request.review_packet, HumanReviewPacket) else None
    selected=request.selected_candidate_id if isinstance(request.selected_candidate_id, str) else ""
    proto=EvidencePromotionResult(PROMOTION_FORMAT_VERSION,"",status,candidate_id or selected, None if card is None else card.card_id, None if audit is None else audit.audit_result_id,None if packet is None else packet.packet_id,None if decision is None else decision.review_decision_id,None if decision is None else decision.reviewer_id,None if item is None else item.evidence_id,item,findings)
    return EvidencePromotionResult(proto.promotion_format_version,_hash(proto.identity_payload()),proto.status,proto.candidate_id,proto.card_id,proto.audit_result_id,proto.packet_id,proto.review_decision_id,proto.reviewer_id,proto.evidence_item_id,proto.evidence_item,proto.validation_findings)

def _mapping_error(mapping: Mapping[str, Any]) -> str | None:
    keys=set(mapping)
    if keys.difference(_MAPPING_FIELDS): return "unknown_mapping_field"
    if _MAPPING_FIELDS.difference(keys): return "missing_required_mapping_field"
    return None

def _card_identity(card: ClaimBoundaryCard, taxonomy_version: str) -> str:
    return _hash({"card_format_version": card.card_format_version, "taxonomy_version": taxonomy_version,
        "candidate_id": card.candidate_id, "findings": [x.to_dict() for x in card.findings],
        "release_decision": card.release_decision, "research_only": card.research_only,
        "not_clinical_guidance": card.not_clinical_guidance, "not_evidence_item": card.not_evidence_item})

def _audit_identity(audit: ScientificClaimAuditResult) -> str:
    return _hash({"audit_format_version": audit.audit_format_version, "taxonomy_version": audit.audit_taxonomy_version,
        "source_document_id": audit.source_document_id, "source_content_hash": audit.source_content_hash,
        "extraction_result_id": audit.extraction_result_id, "cards": [x.to_dict() for x in audit.cards],
        "cross_candidate_findings": [x.to_dict() for x in audit.cross_candidate_findings],
        "overall_decision": audit.overall_decision})

def _dispositions_valid(card: ClaimBoundaryCard, values: tuple[WarningDisposition,...]) -> bool:
    warnings=[x.rule_id for x in card.findings if x.severity == "warning"]
    blockers=[x.rule_id for x in card.findings if x.severity == "blocker"]
    ids=[x.rule_id for x in values]
    if len(ids)!=len(set(ids)) or any(x in blockers or x not in warnings for x in ids): return False
    return set(ids)==set(warnings)

def _build_item(request: EvidencePromotionRequest, candidate: GroundedClaimCandidate, card: ClaimBoundaryCard) -> EvidenceItem:
    mapping=dict(request.evidence_mapping); decision=request.review_decision
    # The item ID is deterministic but excludes operational review time.
    evidence_id=_hash({"candidate_id":candidate.candidate_id,"review_decision_id":decision.review_decision_id,"mapping":mapping})
    if decision.reviewed_at is None:
        raise ValueError("approval requires an operational review timestamp")
    review_at=decision.reviewed_at.astimezone(timezone.utc)
    details={"curator_id":decision.reviewer_id,"review_rationale":decision.decision_justification,"reviewed_source_material":candidate.quoted_span,"human_review_packet_id":request.review_packet.packet_id,"human_review_decision_id":decision.review_decision_id,"candidate_id":candidate.candidate_id,"card_id":card.card_id,"audit_result_id":request.audit_result.audit_result_id,"source_document_id":candidate.source_document_id,"source_content_hash":candidate.source_content_hash,"warning_dispositions":[x.to_dict() for x in decision.warning_dispositions]}
    # This is required evidence provenance, not a copy of any source document.
    mapping["evidence_id"]=evidence_id; mapping["record_hash"]=None; mapping["quoted_span"]=candidate.quoted_span
    mapping["provenance_history"]=(ProvenanceStep("manual_review",review_at,details,True),)
    return EvidenceItem(**mapping)

def promote_candidate_to_evidence(request: EvidencePromotionRequest) -> EvidencePromotionResult:
    """Validate and promote exactly one candidate without I/O, providers, or persistence."""
    if not isinstance(request,EvidencePromotionRequest): raise TypeError("request must be EvidencePromotionRequest")
    extraction,audit,packet,decision=request.grounded_extraction,request.audit_result,request.review_packet,request.review_decision
    if not isinstance(extraction,GroundedExtractionResult) or not isinstance(audit,ScientificClaimAuditResult) or not isinstance(packet,HumanReviewPacket) or not isinstance(decision,HumanReviewDecision): return _result(request,"invalid_input")
    source_hash=sha256(request.source_text.encode("utf-8")).hexdigest()
    candidates={x.candidate_id:x for x in extraction.accepted_candidates}; candidate=candidates.get(request.selected_candidate_id)
    cards={x.candidate_id:x for x in audit.cards}; card=cards.get(request.selected_candidate_id)
    if candidate is None or card is None: return _result(request,"invalid_input",findings=("candidate_or_audit_coverage_missing",))
    if candidate.candidate_id != _hash(candidate.identity_payload()) or card.card_id != _card_identity(card,audit.audit_taxonomy_version) or audit.audit_result_id != _audit_identity(audit):
        return _result(request,"identity_mismatch",card=card,findings=("candidate_card_or_audit_identity_mismatch",))
    if any((candidate.source_document_id!=request.source_document_id,candidate.source_document_id!=audit.source_document_id,candidate.source_content_hash!=source_hash,audit.source_content_hash!=source_hash,request.source_text[candidate.quote_start:candidate.quote_end] != candidate.quoted_span if isinstance(candidate.quote_start,int) and isinstance(candidate.quote_end,int) and candidate.quote_start>=0 and candidate.quote_end>=candidate.quote_start else True)): return _result(request,"invalid_grounding",card=card,findings=("source_or_quote_mismatch",))
    expected_packet=_hash(packet.identity_payload())
    if packet.packet_id!=expected_packet or packet.extraction_result_id!=extraction.result_id or packet.audit_result_id!=audit.audit_result_id: return _result(request,"identity_mismatch",card=card,findings=("packet_identity_mismatch",))
    if packet.source_document_id != request.source_document_id or packet.source_document_id != audit.source_document_id or packet.source_content_hash != source_hash or packet.source_content_hash != audit.source_content_hash: return _result(request,"invalid_grounding",card=card,findings=("packet_source_identity_or_hash_mismatch",))
    entries={x.candidate_id:x for x in packet.entries}; entry=entries.get(candidate.candidate_id)
    if entry is None or entry.card_id!=card.card_id or decision.packet_id!=packet.packet_id or decision.candidate_id!=candidate.candidate_id or decision.card_id!=card.card_id or decision.audit_result_id!=audit.audit_result_id or decision.review_decision_id!=_hash(decision.identity_payload()): return _result(request,"identity_mismatch",card=card,findings=("review_identity_mismatch",))
    state=eligibility_for(card,extraction,audit)
    if state in {"blocked","invalid_audit","invalid_grounding"}: return _result(request,"blocked_by_audit" if state=="blocked" else "invalid_grounding",card=card)
    if decision.decision=="reject": return _result(request,"rejected_by_reviewer",card=card)
    if decision.decision=="defer": return _result(request,"deferred_by_reviewer",card=card)
    if state=="requires_finding_disposition" and not _dispositions_valid(card,decision.warning_dispositions): return _result(request,"warning_disposition_required",card=card,findings=("warning_disposition_required",))
    if state=="eligible_for_review" and decision.warning_dispositions: return _result(request,"invalid_review",card=card,findings=("unexpected_warning_disposition",))
    if decision.evidence_mapping is None or _thaw(decision.evidence_mapping)!=_thaw(request.evidence_mapping): return _result(request,"invalid_mapping",card=card,findings=("explicit_mapping_mismatch",))
    error=_mapping_error(request.evidence_mapping)
    if error: return _result(request,"invalid_mapping",card=card,findings=(error,))
    try:
        item=_build_item(request,candidate,card); require_finalizable(item)
    except (TypeError,ValueError,ValidationError) as exc:
        return _result(request,"evidence_validation_failed",card=card,findings=_findings(exc) if isinstance(exc,ValidationError) else ("evidence_construction_failed",))
    return _result(request,"promoted",card=card,item=item)
