"""Pure parsing of LLM structured output into immutable grounded staging claims.

This module deliberately has no provider, retrieval, persistence, or evidence-layer
dependencies.  Candidate identity is scientific grounding only; provider and prompt
details are retained as provenance but are excluded from that identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import LLMRequest, LLMResponse, LLMResultStatus, _freeze, _thaw, canonical_json
from .grounded_schema import (
    GROUNDED_EXTRACTION_SCHEMA_ID, GROUNDED_EXTRACTION_SCHEMA_VERSION,
    _HIDDEN_REASONING_FIELDS, _RAW_LIST_FIELDS, _RAW_STRING_FIELDS,
)


EXTRACTION_FORMAT_VERSION = "grounded-extraction-result-v1"
_CLAIM_REQUIRED = frozenset({"claim_text", "quoted_span", "quote_start", "quote_end", "stance"})
_CLAIM_FIELDS = _CLAIM_REQUIRED | frozenset(_RAW_LIST_FIELDS) | frozenset(_RAW_STRING_FIELDS)
_TOP_FIELDS = frozenset({"schema_id", "schema_version", "source_document_id", "claims"})
_STANCES = frozenset({"supports", "contradicts", "contextual", "unclear"})


class GroundedExtractionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class GroundedRejectionReason(str, Enum):
    """Stable audit vocabulary; parser messages intentionally remain generic."""
    RESPONSE_NOT_SUCCESSFUL = "response_not_successful"
    STRUCTURED_OUTPUT_MISSING = "structured_output_missing"
    INVALID_TOP_LEVEL_SHAPE = "invalid_top_level_shape"
    SCHEMA_MISMATCH = "schema_mismatch"
    SOURCE_DOCUMENT_MISMATCH = "source_document_mismatch"
    CLAIMS_NOT_ARRAY = "claims_not_array"
    CLAIM_NOT_OBJECT = "claim_not_object"
    UNKNOWN_CLAIM_FIELD = "unknown_claim_field"
    EMPTY_CLAIM_TEXT = "empty_claim_text"
    EMPTY_QUOTE = "empty_quote"
    INVALID_OFFSET_TYPE = "invalid_offset_type"
    INVALID_OFFSET_RANGE = "invalid_offset_range"
    QUOTE_MISMATCH = "quote_mismatch"
    QUOTE_NOT_FOUND = "quote_not_found"
    AMBIGUOUS_QUOTE = "ambiguous_quote"
    INVALID_STANCE = "invalid_stance"
    HIDDEN_REASONING_FIELD = "hidden_reasoning_field"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    MALFORMED_OPTIONAL_FIELD = "malformed_optional_field"


@dataclass(frozen=True)
class RejectedGroundedClaim:
    index: int | None
    reason_code: str
    message: str
    fields: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.index is not None and (not isinstance(self.index, int) or self.index < 0):
            raise ValueError("index must be a non-negative integer or null")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise ValueError("reason_code must be non-empty")
        object.__setattr__(self, "fields", _freeze(self.fields))

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "reason_code": self.reason_code, "message": self.message, "fields": _thaw(self.fields)}


@dataclass(frozen=True)
class GroundedClaimCandidate:
    candidate_id: str
    source_document_id: str
    source_content_hash: str
    claim_text: str
    quoted_span: str
    quote_start: int
    quote_end: int
    stance: str
    raw_fields: Mapping[str, Any]
    request_identity: str
    response_identity: str
    provider_name: str
    requested_model: str | None
    returned_model: str
    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_fields", _freeze(self.raw_fields))

    def identity_payload(self) -> dict[str, Any]:
        return {"format_version": EXTRACTION_FORMAT_VERSION, "source_document_id": self.source_document_id,
                "source_content_hash": self.source_content_hash, "quote_start": self.quote_start,
                "quote_end": self.quote_end, "quoted_span": self.quoted_span, "claim_text": self.claim_text,
                "stance": self.stance, "raw_fields": _thaw(self.raw_fields)}

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["raw_fields"] = _thaw(self.raw_fields)
        return result

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class GroundedExtractionResult:
    result_id: str
    status: GroundedExtractionStatus
    accepted_candidates: tuple[GroundedClaimCandidate, ...] = ()
    rejected_claims: tuple[RejectedGroundedClaim, ...] = ()
    no_claims: bool = False
    request_identity: str = ""
    response_identity: str = ""
    source_content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"result_id": self.result_id, "status": self.status.value,
                "accepted_candidates": [item.to_dict() for item in self.accepted_candidates],
                "rejected_claims": [item.to_dict() for item in self.rejected_claims], "no_claims": self.no_claims,
                "request_identity": self.request_identity, "response_identity": self.response_identity,
                "source_content_hash": self.source_content_hash}

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def _source_text(request: LLMRequest) -> str:
    return request.source_text if request.source_text is not None else canonical_json(request.structured_source_content)


def _result(request: LLMRequest, response: LLMResponse, source_hash: str, status: GroundedExtractionStatus,
            accepted: list[GroundedClaimCandidate], rejected: list[RejectedGroundedClaim], no_claims: bool) -> GroundedExtractionResult:
    payload = {"format_version": EXTRACTION_FORMAT_VERSION, "request_identity": request.payload_identity(),
               "response_identity": response.payload_identity(), "source_content_hash": source_hash,
               "status": status.value, "accepted_candidate_ids": [item.candidate_id for item in accepted],
               "rejections": [{"reason_code": item.reason_code, "fields": _thaw(item.fields)} for item in rejected],
               "no_claims": no_claims}
    return GroundedExtractionResult(sha256(canonical_json(payload).encode("utf-8")).hexdigest(), status,
        tuple(accepted), tuple(rejected), no_claims, request.payload_identity(), response.payload_identity(), source_hash)


def _reject(index: int | None, code: str, message: str, **fields: Any) -> RejectedGroundedClaim:
    # Fields are explicitly selected metadata only: never quote, claim text, source text, or arbitrary model content.
    return RejectedGroundedClaim(index, code, message, fields)


def extract_grounded_candidates(request: LLMRequest, response: LLMResponse) -> GroundedExtractionResult:
    """Validate one completed response without invoking providers or mutating inputs."""
    if not isinstance(request, LLMRequest) or not isinstance(response, LLMResponse):
        raise TypeError("request and response must use provider-neutral LLM contracts")
    source = _source_text(request)
    source_hash = sha256(source.encode("utf-8")).hexdigest()
    if response.status is not LLMResultStatus.SUCCESS:
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "response_not_successful", "Response status is not successful", status=response.status.value)], False)
    if response.structured_output is None:
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "structured_output_missing", "Structured output is required")], False)
    output = response.structured_output
    if not isinstance(output, Mapping):
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "invalid_top_level_shape", "Top-level structured output must be an object")], False)
    if response.request_id != request.request_id:
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "source_document_mismatch", "Response does not belong to the supplied request")], False)
    if set(output).difference(_TOP_FIELDS) or not _TOP_FIELDS.issubset(output):
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "invalid_top_level_shape", "Top-level fields do not match grounded schema")], False)
    if output.get("schema_id") != GROUNDED_EXTRACTION_SCHEMA_ID or output.get("schema_version") != GROUNDED_EXTRACTION_SCHEMA_VERSION or request.response_schema_id != GROUNDED_EXTRACTION_SCHEMA_ID or request.response_schema_version != GROUNDED_EXTRACTION_SCHEMA_VERSION or response.response_schema_id != request.response_schema_id or response.response_schema_version != request.response_schema_version:
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "schema_mismatch", "Grounded schema identifier or version does not match")], False)
    if output.get("source_document_id") != request.source_document_id or response.source_document_id != request.source_document_id:
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "source_document_mismatch", "Source document identifier does not match")], False)
    claims = output["claims"]
    if not isinstance(claims, (list, tuple)):
        return _result(request, response, source_hash, GroundedExtractionStatus.FAILED, [], [_reject(None, "claims_not_array", "Claims must be an array")], False)
    accepted: list[GroundedClaimCandidate] = []
    rejected: list[RejectedGroundedClaim] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            rejected.append(_reject(index, "claim_not_object", "Claim must be an object")); continue
        keys = set(claim)
        hidden = keys.intersection(_HIDDEN_REASONING_FIELDS)
        if hidden:
            rejected.append(_reject(index, "hidden_reasoning_field", "Hidden reasoning fields are forbidden", field=sorted(hidden)[0])); continue
        unknown = keys.difference(_CLAIM_FIELDS)
        if unknown:
            rejected.append(_reject(index, "unknown_claim_field", "Unknown claim field", field=sorted(str(x) for x in unknown)[0])); continue
        if not _CLAIM_REQUIRED.issubset(claim):
            missing = _CLAIM_REQUIRED.difference(claim)
            code = "invalid_offset_type" if {"quote_start", "quote_end"}.intersection(missing) else "claim_not_object"
            rejected.append(_reject(index, code, "Claim is missing required fields")); continue
        text, quote = claim["claim_text"], claim["quoted_span"]
        if not isinstance(text, str) or not text.strip():
            rejected.append(_reject(index, "empty_claim_text", "Claim text must be non-empty")); continue
        if not isinstance(quote, str) or not quote:
            rejected.append(_reject(index, "empty_quote", "Quoted span must be non-empty")); continue
        start, end = claim["quote_start"], claim["quote_end"]
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            rejected.append(_reject(index, "invalid_offset_type", "Quote offsets must be integers")); continue
        if start < 0 or end <= start or end > len(source):
            rejected.append(_reject(index, "invalid_offset_range", "Quote offsets are outside the source range")); continue
        if source[start:end] != quote:
            rejected.append(_reject(index, "quote_mismatch", "Quoted span does not exactly match source offsets")); continue
        stance = claim["stance"]
        if not isinstance(stance, str) or stance not in _STANCES:
            rejected.append(_reject(index, "invalid_stance", "Stance is not in the controlled vocabulary")); continue
        raw: dict[str, Any] = {}
        malformed = False
        for name in _RAW_LIST_FIELDS:
            if name in claim:
                value = claim[name]
                if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value): malformed = True; break
                raw[name] = list(value)
        for name in _RAW_STRING_FIELDS:
            if name in claim:
                if not isinstance(claim[name], str): malformed = True; break
                raw[name] = claim[name]
        if malformed:
            rejected.append(_reject(index, "malformed_optional_field", "Optional raw field has an invalid shape")); continue
        identity_payload = {"format_version": EXTRACTION_FORMAT_VERSION, "source_document_id": request.source_document_id,
            "source_content_hash": source_hash, "quote_start": start, "quote_end": end, "quoted_span": quote,
            "claim_text": text, "stance": stance, "raw_fields": raw}
        candidate_id = sha256(canonical_json(identity_payload).encode("utf-8")).hexdigest()
        if candidate_id in seen:
            rejected.append(_reject(index, "duplicate_candidate", "Duplicate candidate in this response")); continue
        seen.add(candidate_id)
        accepted.append(GroundedClaimCandidate(candidate_id, request.source_document_id, source_hash, text, quote, start, end, stance,
            raw, request.payload_identity(), response.payload_identity(), response.provider_name,
            response.provenance.requested_model_name, response.model_name, request.prompt_id, request.prompt_version,
            GROUNDED_EXTRACTION_SCHEMA_ID, GROUNDED_EXTRACTION_SCHEMA_VERSION))
    return _result(request, response, source_hash, GroundedExtractionStatus.SUCCESS, accepted, rejected, not claims)
