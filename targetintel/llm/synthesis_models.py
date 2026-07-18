"""Immutable contracts for snapshot-grounded target synthesis (Issue 309)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import canonical_json, _freeze, _thaw

TARGET_SYNTHESIS_REQUEST_SCHEMA_ID = "targetintel.target_synthesis_request"
TARGET_SYNTHESIS_REQUEST_SCHEMA_VERSION = "1.0.0"
TARGET_INVENTORY_FORMAT_VERSION = "targetintel.target_evidence_inventory.v1"
GROUNDED_STATEMENT_FORMAT_VERSION = "targetintel.grounded_synthesis_statement.v1"
GROUNDED_SYNTHESIS_FORMAT_VERSION = "targetintel.grounded_target_synthesis.v1"
GROUNDED_SYNTHESIS_RESULT_FORMAT_VERSION = "targetintel.grounded_target_synthesis_result.v1"

SYNTHESIS_PURPOSES = frozenset({"target_evidence_summary", "mechanism_review", "biomarker_evidence_summary", "research_hypothesis_context"})
SECTION_ORDER = ("scope", "supported_observations", "contradictory_evidence", "limitations", "uncertainties", "open_research_questions", "provenance_summary")
SECTION_IDENTIFIERS = frozenset(SECTION_ORDER)
SCIENTIFIC_SECTIONS = frozenset(SECTION_ORDER) - {"scope", "provenance_summary"}
SUPPORT_RELATIONS = frozenset({"supported", "contradicted", "mixed", "contextual", "limitation", "uncertain", "open_question"})
UNCERTAINTY_LEVELS = frozenset({"low_uncertainty", "moderate_uncertainty", "high_uncertainty", "not_assessed"})
UNSYNTHESIZED_REASONS = frozenset({"insufficient_structured_content", "duplicate_scientific_observation", "outside_requested_context", "cannot_summarize_without_overinterpretation"})
RESULT_STATUSES = frozenset({"generated", "invalid_request", "invalid_snapshot", "snapshot_identity_mismatch", "snapshot_manifest_mismatch", "target_not_present", "context_not_present", "inventory_empty", "item_limit_exceeded", "provider_error", "unsupported_provider_capability", "response_schema_error", "response_identity_mismatch", "unknown_evidence_reference", "incomplete_evidence_coverage", "ungrounded_statement", "unsafe_clinical_language", "unsafe_therapeutic_recommendation", "invalid_synthesis"})
SUPPORTED_LANGUAGES = frozenset({"en"})

def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()

def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value

def _unsafe(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            text = str(key).casefold().replace("-", "_")
            if any(x in text for x in ("secret", "password", "credential", "api_key", "apikey", "token", "authorization", "thinking", "reasoning", "chain_of_thought", "scratchpad", "analysis")):
                raise ValueError("unsafe synthesis field")
            _unsafe(item)
    elif isinstance(value, (tuple, list)):
        for item in value: _unsafe(item)

def _utc(value: datetime | None, name: str) -> datetime | None:
    if value is None: return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)

@dataclass(frozen=True)
class TargetSynthesisRequest:
    request_schema_id: str; request_schema_version: str; request_id: str; snapshot_id: str; snapshot_manifest_hash: str
    target_identity: str; context: str | None; synthesis_purpose: str; requested_sections: tuple[str, ...]; maximum_statement_count: int; maximum_words_per_statement: int; requesting_actor_id: str; language: str; requested_at: datetime | None = None
    def __post_init__(self) -> None:
        if self.request_schema_id != TARGET_SYNTHESIS_REQUEST_SCHEMA_ID or self.request_schema_version != TARGET_SYNTHESIS_REQUEST_SCHEMA_VERSION: raise ValueError("unknown synthesis request schema")
        for name in ("request_id", "snapshot_id", "snapshot_manifest_hash", "target_identity", "requesting_actor_id", "language"): _nonempty(getattr(self, name), name)
        if self.context is not None: _nonempty(self.context, "context")
        if self.synthesis_purpose not in SYNTHESIS_PURPOSES or self.language not in SUPPORTED_LANGUAGES: raise ValueError("unknown synthesis request vocabulary")
        sections = tuple(self.requested_sections)
        if not sections or len(sections) != len(set(sections)) or set(sections) - SECTION_IDENTIFIERS or not set(sections) & SCIENTIFIC_SECTIONS: raise ValueError("invalid requested sections")
        if not isinstance(self.maximum_statement_count, int) or isinstance(self.maximum_statement_count, bool) or self.maximum_statement_count <= 0: raise ValueError("maximum_statement_count must be positive")
        if not isinstance(self.maximum_words_per_statement, int) or isinstance(self.maximum_words_per_statement, bool) or self.maximum_words_per_statement <= 0: raise ValueError("maximum_words_per_statement must be positive")
        object.__setattr__(self, "requested_sections", tuple(x for x in SECTION_ORDER if x in sections)); object.__setattr__(self, "requested_at", _utc(self.requested_at, "requested_at"))
        if self.request_id != _digest(self.identity_payload()): raise ValueError("synthesis request identity does not match payload")
    def identity_payload(self) -> dict[str, Any]:
        return {"request_schema_id": self.request_schema_id, "request_schema_version": self.request_schema_version, "snapshot_id": self.snapshot_id, "snapshot_manifest_hash": self.snapshot_manifest_hash, "target_identity": self.target_identity, "context": self.context, "synthesis_purpose": self.synthesis_purpose, "requested_sections": list(self.requested_sections), "maximum_statement_count": self.maximum_statement_count, "maximum_words_per_statement": self.maximum_words_per_statement, "requesting_actor_id": self.requesting_actor_id, "language": self.language}
    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload() | {"request_id": self.request_id}
        if self.requested_at: value["requested_at"] = self.requested_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value
    def canonical_json(self) -> str: return canonical_json(self.to_dict())
    @classmethod
    def create(cls, **values: Any) -> "TargetSynthesisRequest":
        values = dict(values); _unsafe(values); values.setdefault("request_schema_id", TARGET_SYNTHESIS_REQUEST_SCHEMA_ID); values.setdefault("request_schema_version", TARGET_SYNTHESIS_REQUEST_SCHEMA_VERSION)
        sections = values.get("requested_sections")
        if not isinstance(sections, (list, tuple)) or not sections or len(sections) != len(set(sections)) or set(sections) - SECTION_IDENTIFIERS or not set(sections) & SCIENTIFIC_SECTIONS:
            raise ValueError("invalid requested sections")
        values["requested_sections"] = tuple(x for x in SECTION_ORDER if x in sections)
        payload = {k: values.get(k) for k in ("request_schema_id", "request_schema_version", "snapshot_id", "snapshot_manifest_hash", "target_identity", "context", "synthesis_purpose", "requested_sections", "maximum_statement_count", "maximum_words_per_statement", "requesting_actor_id", "language")}
        payload["requested_sections"] = list(values["requested_sections"]); values["request_id"] = _digest(payload)
        return cls(**values)
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TargetSynthesisRequest":
        allowed = set(cls.__dataclass_fields__)
        required = allowed - {"context", "requested_at"}
        if not isinstance(data, Mapping) or set(data) - allowed or required - set(data): raise ValueError("invalid synthesis request fields")
        _unsafe(data); values = dict(data)
        if isinstance(values.get("requested_at"), str): values["requested_at"] = datetime.fromisoformat(values["requested_at"].replace("Z", "+00:00"))
        return cls(**values)

@dataclass(frozen=True)
class TargetEvidenceInventory:
    inventory_format_version: str; inventory_id: str; snapshot_id: str; snapshot_manifest_hash: str; target_identity: str; context: str | None; ordered_evidence_item_ids: tuple[str, ...]; ordered_payload_hashes: tuple[str, ...]; evidence_records: tuple[Mapping[str, Any], ...]; selected_item_count: int; inventory_hash: str
    def __post_init__(self) -> None:
        object.__setattr__(self, "ordered_evidence_item_ids", tuple(self.ordered_evidence_item_ids)); object.__setattr__(self, "ordered_payload_hashes", tuple(self.ordered_payload_hashes)); object.__setattr__(self, "evidence_records", tuple(_freeze(x) for x in self.evidence_records))
        if self.inventory_format_version != TARGET_INVENTORY_FORMAT_VERSION or not self.ordered_evidence_item_ids or self.ordered_evidence_item_ids != tuple(sorted(self.ordered_evidence_item_ids)) or len(set(self.ordered_evidence_item_ids)) != len(self.ordered_evidence_item_ids) or len(self.ordered_payload_hashes) != len(self.ordered_evidence_item_ids) or len(self.evidence_records) != len(self.ordered_evidence_item_ids) or self.selected_item_count != len(self.ordered_evidence_item_ids): raise ValueError("invalid target inventory")
        if self.inventory_hash != _digest(self.identity_payload()) or self.inventory_id != self.inventory_hash: raise ValueError("inventory identity mismatch")
    def identity_payload(self) -> dict[str, Any]: return {"inventory_format_version": self.inventory_format_version, "snapshot_id": self.snapshot_id, "snapshot_manifest_hash": self.snapshot_manifest_hash, "target_identity": self.target_identity, "context": self.context, "ordered_evidence_item_ids": list(self.ordered_evidence_item_ids), "ordered_payload_hashes": list(self.ordered_payload_hashes)}
    def to_dict(self) -> dict[str, Any]: return self.identity_payload() | {"inventory_id": self.inventory_id, "inventory_hash": self.inventory_hash, "evidence_records": _thaw(self.evidence_records), "selected_item_count": self.selected_item_count}
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

@dataclass(frozen=True)
class GroundedSynthesisStatement:
    statement_format_version: str; statement_id: str; local_statement_key: str; section_identifier: str; statement_text: str; evidence_item_ids: tuple[str, ...]; evidence_payload_hashes: tuple[str, ...]; support_relation: str; uncertainty_level: str; limitation_text: str | None; safety_codes: tuple[str, ...] = (); research_only: bool = True
    def __post_init__(self) -> None:
        for name in ("statement_id", "local_statement_key", "statement_text"): _nonempty(getattr(self, name), name)
        ids = tuple(self.evidence_item_ids)
        if self.statement_format_version != GROUNDED_STATEMENT_FORMAT_VERSION or self.section_identifier not in SECTION_IDENTIFIERS or not ids or len(ids) != len(set(ids)) or ids != tuple(sorted(ids)) or len(self.evidence_payload_hashes) != len(ids) or self.support_relation not in SUPPORT_RELATIONS or self.uncertainty_level not in UNCERTAINTY_LEVELS or not self.research_only: raise ValueError("invalid grounded statement")
        object.__setattr__(self, "evidence_item_ids", ids); object.__setattr__(self, "evidence_payload_hashes", tuple(self.evidence_payload_hashes)); object.__setattr__(self, "safety_codes", tuple(sorted(set(self.safety_codes))))
        if self.statement_id != _digest(self.identity_payload()): raise ValueError("statement identity mismatch")
    def identity_payload(self) -> dict[str, Any]: return {"statement_format_version": self.statement_format_version, "local_statement_key": self.local_statement_key, "section_identifier": self.section_identifier, "statement_text": self.statement_text, "evidence_item_ids": list(self.evidence_item_ids), "evidence_payload_hashes": list(self.evidence_payload_hashes), "support_relation": self.support_relation, "uncertainty_level": self.uncertainty_level, "limitation_text": self.limitation_text, "safety_codes": list(self.safety_codes), "research_only": self.research_only}
    def to_dict(self) -> dict[str, Any]: return self.identity_payload() | {"statement_id": self.statement_id}
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

@dataclass(frozen=True)
class GroundedTargetSynthesis:
    synthesis_format_version: str; synthesis_id: str; request_id: str; snapshot_id: str; snapshot_manifest_hash: str; inventory_id: str; prompt_id: str; llm_request_id: str; llm_response_id: str; provider_name: str; model_name: str; model_version: str | None; target_identity: str; context: str | None; synthesis_purpose: str; sections: tuple[str, ...]; statements: tuple[GroundedSynthesisStatement, ...]; evidence_coverage: tuple[Mapping[str, Any], ...]; selected_item_count: int; cited_item_count: int; unsynthesized_item_count: int; research_only: bool = True; non_clinical_use: bool = True; no_score_or_ranking_generated: bool = True; no_file_written: bool = True
    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections)); object.__setattr__(self, "statements", tuple(self.statements)); object.__setattr__(self, "evidence_coverage", tuple(_freeze(x) for x in self.evidence_coverage))
        if self.synthesis_format_version != GROUNDED_SYNTHESIS_FORMAT_VERSION or not all(isinstance(x, GroundedSynthesisStatement) for x in self.statements) or not self.research_only or not self.non_clinical_use or not self.no_score_or_ranking_generated or not self.no_file_written: raise ValueError("invalid grounded synthesis")
        if self.synthesis_id != _digest(self.identity_payload()): raise ValueError("synthesis identity mismatch")
    def identity_payload(self) -> dict[str, Any]: return {"synthesis_format_version": self.synthesis_format_version, "request_id": self.request_id, "snapshot_id": self.snapshot_id, "snapshot_manifest_hash": self.snapshot_manifest_hash, "inventory_id": self.inventory_id, "prompt_id": self.prompt_id, "llm_response_id": self.llm_response_id, "target_identity": self.target_identity, "context": self.context, "synthesis_purpose": self.synthesis_purpose, "sections": list(self.sections), "statement_ids": [x.statement_id for x in self.statements], "evidence_coverage": _thaw(self.evidence_coverage), "research_only": self.research_only}
    def to_dict(self) -> dict[str, Any]: return self.identity_payload() | {"synthesis_id": self.synthesis_id, "llm_request_id": self.llm_request_id, "provider_name": self.provider_name, "model_name": self.model_name, "model_version": self.model_version, "statements": [x.to_dict() for x in self.statements], "selected_item_count": self.selected_item_count, "cited_item_count": self.cited_item_count, "unsynthesized_item_count": self.unsynthesized_item_count, "non_clinical_use": self.non_clinical_use, "no_score_or_ranking_generated": self.no_score_or_ranking_generated, "no_file_written": self.no_file_written}
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

@dataclass(frozen=True)
class GroundedTargetSynthesisResult:
    result_format_version: str; result_id: str; status: str; request_id: str | None; snapshot_id: str | None; inventory_id: str | None; prompt_id: str | None; llm_request_id: str | None; llm_response_id: str | None; synthesis_id: str | None; synthesis: GroundedTargetSynthesis | None; codes: tuple[str, ...] = (); completed_at: datetime | None = None
    def __post_init__(self) -> None:
        object.__setattr__(self, "codes", tuple(sorted(set(self.codes)))); object.__setattr__(self, "completed_at", _utc(self.completed_at, "completed_at"))
        if self.result_format_version != GROUNDED_SYNTHESIS_RESULT_FORMAT_VERSION or self.status not in RESULT_STATUSES or (self.status == "generated") != (self.synthesis is not None) or (self.synthesis is not None and self.synthesis_id != self.synthesis.synthesis_id): raise ValueError("invalid synthesis result")
        if self.result_id != _digest(self.identity_payload()): raise ValueError("result identity mismatch")
    def identity_payload(self) -> dict[str, Any]: return {"result_format_version": self.result_format_version, "status": self.status, "request_id": self.request_id, "snapshot_id": self.snapshot_id, "inventory_id": self.inventory_id, "prompt_id": self.prompt_id, "llm_request_id": self.llm_request_id, "llm_response_id": self.llm_response_id, "synthesis_id": self.synthesis_id, "codes": list(self.codes)}
    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload() | {"result_id": self.result_id, "synthesis": None if self.synthesis is None else self.synthesis.to_dict()}
        if self.completed_at: value["completed_at"] = self.completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value
    def canonical_json(self) -> str: return canonical_json(self.to_dict())

def make_synthesis_result(**values: Any) -> GroundedTargetSynthesisResult:
    values.setdefault("result_format_version", GROUNDED_SYNTHESIS_RESULT_FORMAT_VERSION); values.setdefault("codes", ()); values["codes"] = tuple(sorted(set(values["codes"])))
    payload = {key: values.get(key) for key in ("result_format_version", "status", "request_id", "snapshot_id", "inventory_id", "prompt_id", "llm_request_id", "llm_response_id", "synthesis_id")}; payload["codes"] = list(values["codes"])
    return GroundedTargetSynthesisResult(result_id=_digest(payload), **values)
