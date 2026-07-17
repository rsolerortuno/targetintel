"""Immutable packets and decisions for the mandatory human-review boundary."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping

from .claim_audit import ClaimBoundaryCard, ScientificClaimAuditResult
from .contracts import _freeze, _thaw, canonical_json
from .grounded_extraction import GroundedExtractionResult, GroundedExtractionStatus
from .review_schema import REVIEW_SCHEMA_ID, REVIEW_SCHEMA_VERSION, reject_unsafe
from targetintel.evidence.models import EvidenceItem

HUMAN_REVIEW_PACKET_FORMAT_VERSION = "human-review-packet-v1"
HUMAN_REVIEW_DECISION_FORMAT_VERSION = "human-review-decision-v1"
DECISIONS = frozenset({"approve", "reject", "defer"})
DISPOSITIONS = frozenset({"accepted_with_justification", "candidate_corrected_before_promotion", "not_applicable_with_justification", "reject_candidate", "defer_decision"})
_JUSTIFIED = frozenset({"accepted_with_justification", "candidate_corrected_before_promotion", "not_applicable_with_justification"})
_MAPPING_FIELDS = frozenset(EvidenceItem.__dataclass_fields__).difference({"evidence_id", "record_hash", "quoted_span", "provenance_history"})

def _id(payload: Mapping[str, Any]) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()

def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{name} must be non-empty")
    return value

@dataclass(frozen=True)
class WarningDisposition:
    rule_id: str
    disposition: str
    justification: str | None = None
    def __post_init__(self) -> None:
        _text(self.rule_id, "rule_id")
        if self.disposition not in DISPOSITIONS: raise ValueError("unknown finding disposition")
        if self.disposition in _JUSTIFIED and not isinstance(self.justification, str): raise ValueError("disposition justification is required")
        if self.justification is not None: _text(self.justification, "disposition justification")
        reject_unsafe({"justification": self.justification})
    def to_dict(self) -> dict[str, Any]: return {"rule_id": self.rule_id, "disposition": self.disposition, "justification": self.justification}

@dataclass(frozen=True)
class CandidateReviewEntry:
    candidate_id: str; card_id: str; claim_text: str; quoted_span: str; quote_start: int; quote_end: int; stance: str
    audit_decision: str; audit_findings: tuple[Mapping[str, Any], ...]; required_human_decision: bool; required_mapping_fields: tuple[str, ...]; eligibility_state: str
    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_findings", tuple(_freeze(x) for x in self.audit_findings))
    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id":self.candidate_id,"card_id":self.card_id,"claim_text":self.claim_text,"quoted_span":self.quoted_span,"quote_start":self.quote_start,"quote_end":self.quote_end,"stance":self.stance,"audit_decision":self.audit_decision,"audit_findings":[_thaw(x) for x in self.audit_findings],"required_human_decision":True,"required_mapping_fields":list(self.required_mapping_fields),"eligibility_state":self.eligibility_state}

def eligibility_for(card: ClaimBoundaryCard, extraction: GroundedExtractionResult, audit: ScientificClaimAuditResult) -> str:
    if extraction.status is not GroundedExtractionStatus.SUCCESS or not card.candidate_id: return "invalid_grounding"
    if not card.card_id or audit.extraction_result_id != extraction.result_id or card.source_document_id != audit.source_document_id or card.source_content_hash != audit.source_content_hash: return "invalid_audit"
    if card.release_decision == "block" or any(x.severity == "blocker" for x in card.findings): return "blocked"
    if card.release_decision == "review": return "requires_finding_disposition"
    return "eligible_for_review" if card.release_decision == "pass" else "invalid_audit"

@dataclass(frozen=True)
class HumanReviewPacket:
    packet_format_version: str; packet_id: str; source_document_id: str; source_content_hash: str; extraction_result_id: str; audit_result_id: str; entries: tuple[CandidateReviewEntry, ...]
    research_only: bool = True; not_clinical_validation: bool = True; created_at: datetime | None = None
    def __post_init__(self) -> None: object.__setattr__(self, "entries", tuple(self.entries))
    def identity_payload(self) -> dict[str, Any]: return {"packet_format_version":self.packet_format_version,"source_document_id":self.source_document_id,"source_content_hash":self.source_content_hash,"extraction_result_id":self.extraction_result_id,"audit_result_id":self.audit_result_id,"entries":[x.to_dict() for x in self.entries],"research_only":True,"not_clinical_validation":True}
    def to_dict(self) -> dict[str, Any]:
        d=self.identity_payload() | {"packet_id":self.packet_id}
        if self.created_at is not None: d["created_at"]=self.created_at.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        return d
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

def build_human_review_packet(extraction: GroundedExtractionResult, audit: ScientificClaimAuditResult, *, created_at: datetime | None = None, required_mapping_fields: tuple[str, ...] = ()) -> HumanReviewPacket:
    if not isinstance(extraction, GroundedExtractionResult) or not isinstance(audit, ScientificClaimAuditResult): raise ValueError("grounded extraction and audit result are required")
    cards={x.candidate_id:x for x in audit.cards}
    entries=[]
    for candidate in extraction.accepted_candidates:
        card=cards.get(candidate.candidate_id)
        if card is None: continue
        entries.append(CandidateReviewEntry(candidate.candidate_id,card.card_id,candidate.claim_text,candidate.quoted_span,candidate.quote_start,candidate.quote_end,candidate.stance,card.release_decision,tuple(x.to_dict() for x in card.findings),True,tuple(required_mapping_fields),eligibility_for(card, extraction, audit)))
    proto=HumanReviewPacket(HUMAN_REVIEW_PACKET_FORMAT_VERSION,"",audit.source_document_id,audit.source_content_hash,extraction.result_id,audit.audit_result_id,tuple(entries),created_at=created_at)
    return HumanReviewPacket(proto.packet_format_version,_id(proto.identity_payload()),proto.source_document_id,proto.source_content_hash,proto.extraction_result_id,proto.audit_result_id,proto.entries,created_at=created_at)

@dataclass(frozen=True)
class HumanReviewDecision:
    review_schema_id: str; review_schema_version: str; review_decision_id: str; packet_id: str; candidate_id: str; card_id: str; audit_result_id: str; reviewer_id: str; decision: str; decision_justification: str; warning_dispositions: tuple[WarningDisposition, ...] = (); evidence_mapping: Mapping[str, Any] | None = None; reviewed_at: datetime | None = None
    def __post_init__(self) -> None:
        if self.review_schema_id != REVIEW_SCHEMA_ID or self.review_schema_version != REVIEW_SCHEMA_VERSION: raise ValueError("unknown review schema")
        for n in ("packet_id","candidate_id","card_id","audit_result_id","reviewer_id","decision_justification"): _text(getattr(self,n),n)
        if self.decision not in DECISIONS: raise ValueError("unknown decision")
        if self.decision == "approve" and self.evidence_mapping is None: raise ValueError("approval requires explicit evidence mapping")
        if self.decision != "approve" and self.evidence_mapping is not None: raise ValueError("only approval may include evidence mapping")
        if self.evidence_mapping is not None and not isinstance(self.evidence_mapping, Mapping): raise ValueError("evidence mapping must be an object")
        if not all(isinstance(value, WarningDisposition) for value in self.warning_dispositions): raise ValueError("warning dispositions must use WarningDisposition")
        reject_unsafe({"decision_justification":self.decision_justification,"evidence_mapping":self.evidence_mapping})
        if self.evidence_mapping is not None and set(self.evidence_mapping).difference(_MAPPING_FIELDS): raise ValueError("unknown evidence mapping field")
        if self.reviewed_at is not None and (not isinstance(self.reviewed_at, datetime) or self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None): raise ValueError("reviewed_at must be timezone-aware")
        object.__setattr__(self,"warning_dispositions",tuple(self.warning_dispositions)); object.__setattr__(self,"evidence_mapping",None if self.evidence_mapping is None else _freeze(self.evidence_mapping))
    def identity_payload(self) -> dict[str, Any]: return {"review_schema_id":self.review_schema_id,"review_schema_version":self.review_schema_version,"packet_id":self.packet_id,"candidate_id":self.candidate_id,"card_id":self.card_id,"audit_result_id":self.audit_result_id,"reviewer_id":self.reviewer_id,"decision":self.decision,"decision_justification":self.decision_justification,"warning_dispositions":[x.to_dict() for x in self.warning_dispositions],"evidence_mapping":None if self.evidence_mapping is None else _thaw(self.evidence_mapping)}
    def to_dict(self) -> dict[str, Any]:
        d=self.identity_payload() | {"review_decision_id":self.review_decision_id}
        if self.reviewed_at is not None: d["reviewed_at"]=self.reviewed_at.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        return d
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

def create_human_review_decision(*, packet_id: str, candidate_id: str, card_id: str, audit_result_id: str, reviewer_id: str, decision: str, decision_justification: str, warning_dispositions: tuple[WarningDisposition, ...] = (), evidence_mapping: Mapping[str, Any] | None = None, reviewed_at: datetime | None = None) -> HumanReviewDecision:
    proto=HumanReviewDecision(REVIEW_SCHEMA_ID,REVIEW_SCHEMA_VERSION,"",packet_id,candidate_id,card_id,audit_result_id,reviewer_id,decision,decision_justification,warning_dispositions,evidence_mapping,reviewed_at)
    return HumanReviewDecision(proto.review_schema_id,proto.review_schema_version,_id(proto.identity_payload()),packet_id,candidate_id,card_id,audit_result_id,reviewer_id,decision,decision_justification,warning_dispositions,evidence_mapping,reviewed_at)

def parse_human_review_decision(data: Mapping[str, Any]) -> HumanReviewDecision:
    """Parse the fixed review schema; no unknown payload fields are tolerated."""
    # These names intentionally match ``HumanReviewDecision.to_dict`` so a
    # JSON-loaded serialized decision can be strictly parsed and verified.
    allowed=frozenset({"review_schema_id","review_schema_version","review_decision_id","packet_id","candidate_id","card_id","audit_result_id","reviewer_id","decision","decision_justification","warning_dispositions","evidence_mapping","reviewed_at"})
    required=allowed.difference({"review_decision_id","warning_dispositions","evidence_mapping","reviewed_at"})
    if not isinstance(data,Mapping) or set(data).difference(allowed) or required.difference(data): raise ValueError("review payload fields do not match schema")
    reject_unsafe(data)
    if data["review_schema_id"] != REVIEW_SCHEMA_ID or data["review_schema_version"] != REVIEW_SCHEMA_VERSION: raise ValueError("unknown review schema")
    dispositions=data.get("warning_dispositions",())
    if not isinstance(dispositions,(list,tuple)): raise ValueError("warning dispositions must be an array")
    values=[]
    for value in dispositions:
        if not isinstance(value,Mapping) or set(value).difference({"rule_id","disposition","justification"}) or {"rule_id","disposition"}.difference(value): raise ValueError("warning disposition fields do not match schema")
        values.append(WarningDisposition(value["rule_id"],value["disposition"],value.get("justification")))
    reviewed_at=data.get("reviewed_at")
    if isinstance(reviewed_at, str):
        try: reviewed_at=datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError as exc: raise ValueError("reviewed_at must be an ISO 8601 timestamp") from exc
    if reviewed_at is not None and not isinstance(reviewed_at,datetime): raise ValueError("reviewed_at must be an ISO 8601 timestamp")
    parsed=create_human_review_decision(packet_id=data["packet_id"],candidate_id=data["candidate_id"],card_id=data["card_id"],audit_result_id=data["audit_result_id"],reviewer_id=data["reviewer_id"],decision=data["decision"],decision_justification=data["decision_justification"],warning_dispositions=tuple(values),evidence_mapping=data.get("evidence_mapping"),reviewed_at=reviewed_at)
    if "review_decision_id" in data and data["review_decision_id"] != parsed.review_decision_id: raise ValueError("review decision identity does not match payload")
    return parsed
