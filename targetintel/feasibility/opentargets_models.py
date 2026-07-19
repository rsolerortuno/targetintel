"""Immutable, source-level contracts for the v0.4.0 Open Targets boundary.

These contracts deliberately contain observations and transport metadata only.
They do not import the deterministic pipeline or construct feasibility profiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

FETCH_REQUEST_SCHEMA_ID = "targetintel.opentargets-fetch-request"
FETCH_REQUEST_SCHEMA_VERSION = "v0.4.0"
CANONICALIZATION_VERSION = "v1"
QUERY_TYPES = frozenset({"association_ranked", "directed_target_universe"})
CACHE_POLICIES = frozenset({"disabled", "read_through", "refresh", "cache_only"})
RELEASE_VERIFICATION_STATES = frozenset({"verified", "declared_unverified", "not_reported", "mismatch"})
RESOLUTION_STATUSES = frozenset({"resolved_exact", "unresolved", "ambiguous", "invalid_identifier", "retrieval_failed"})
RESULT_STATUSES = frozenset({"completed", "completed_with_gaps", "truncated", "invalid_request", "invalid_plan", "release_mismatch", "resolution_failed", "transport_error", "response_error", "cache_error"})
OFFICIAL_GRAPHQL_ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"
_ENSEMBL = re.compile(r"^ENSG\d{11}$")

def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping): return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)): return tuple(_freeze(v) for v in value)
    return value
def thaw(value: Any) -> Any:
    if isinstance(value, (Mapping, MappingProxyType)): return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [thaw(v) for v in value]
    if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value
def canonical_json(value: Any) -> str: return json.dumps(thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
def identity(prefix: str, value: Any) -> str: return prefix + "_" + sha256(canonical_json(value).encode()).hexdigest()
def payload_hash(value: Any) -> str: return sha256(canonical_json(value).encode()).hexdigest()
def _timestamp(v: datetime | None) -> str | None: return None if v is None else thaw(v)
def _clean_errors(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    result = tuple(sorted(set(str(v) for v in values)))
    if any(not v or any(x in v.casefold() for x in ("traceback", "password", "token", "authorization", "secret")) for v in result): raise ValueError("errors must be sanitized codes")
    return result
def _validate_endpoint(endpoint: str) -> None:
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    if endpoint != OFFICIAL_GRAPHQL_ENDPOINT or parsed.scheme != "https" or parsed.username or parsed.password or parsed.hostname in {"localhost", "127.0.0.1", "::1"}: raise ValueError("endpoint is not an allowed official HTTPS Open Targets endpoint")
def canonical_targets(targets: tuple[str, ...] | list[str], identifier_type: str) -> tuple[str, ...]:
    if identifier_type not in {"gene_symbol", "ensembl_gene_id"}: raise ValueError("unknown target identifier type")
    normalized = []
    for target in targets:
        if not isinstance(target, str) or not target.strip(): raise ValueError("target identifiers must be non-empty strings")
        value = target.strip().upper() if identifier_type == "gene_symbol" else target.strip()
        normalized.append(value)
    return tuple(sorted(set(normalized)))
def universe_hash(targets: tuple[str, ...], identifier_type: str) -> str:
    return payload_hash({"canonicalization_version": CANONICALIZATION_VERSION, "target_identifier_type": identifier_type, "target_identifiers": list(targets)})

@dataclass(frozen=True)
class OpenTargetsFetchRequest:
    # Retrieval mode is deliberately required: callers must not obtain an
    # association query merely by omitting a mode selection.
    query_type: str
    request_schema_id: str = FETCH_REQUEST_SCHEMA_ID
    request_schema_version: str = FETCH_REQUEST_SCHEMA_VERSION
    endpoint_identity: str = OFFICIAL_GRAPHQL_ENDPOINT
    requested_source_release: str = "not_reported"
    release_verification_required: bool = False
    query_schema_version: str = "v1"
    disease_id: str | None = None
    association_scope: str | None = None
    target_identifier_type: str = "gene_symbol"
    target_universe: tuple[str, ...] | list[str] = ()
    page_size: int = 100
    max_pages: int = 1
    timeout_seconds: int = 60
    requesting_actor: str = "targetintel"
    cache_policy: str = "disabled"
    operational_timestamp: datetime | None = None
    def __post_init__(self) -> None:
        _validate_endpoint(self.endpoint_identity)
        if self.request_schema_id != FETCH_REQUEST_SCHEMA_ID or self.request_schema_version != FETCH_REQUEST_SCHEMA_VERSION: raise ValueError("unsupported fetch request schema")
        if self.query_type not in QUERY_TYPES or self.cache_policy not in CACHE_POLICIES: raise ValueError("unknown controlled vocabulary value")
        if not isinstance(self.requested_source_release, str) or not self.requested_source_release.strip() or not isinstance(self.query_schema_version, str) or not self.query_schema_version.strip() or not isinstance(self.requesting_actor, str) or not self.requesting_actor.strip(): raise ValueError("required request text missing")
        if not isinstance(self.page_size, int) or not 1 <= self.page_size <= 1000: raise ValueError("page_size must be 1..1000")
        if not isinstance(self.max_pages, int) or not 1 <= self.max_pages <= 10000: raise ValueError("max_pages must be 1..10000")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 300: raise ValueError("timeout_seconds must be 1..300")
        targets = canonical_targets(self.target_universe, self.target_identifier_type)
        object.__setattr__(self, "target_universe", targets)
        if self.query_type == "association_ranked":
            if not self.disease_id: raise ValueError("association_ranked requires disease_id")
            if targets: raise ValueError("association_ranked rejects target universe")
            # The current project-owned associatedTargets document has no
            # direct/indirect switch.  Rejecting a requested scope is more
            # honest than hashing metadata that the source never received.
            if self.association_scope is not None:
                raise ValueError("association_scope is not supported by this query version")
        else:
            if not targets: raise ValueError("directed_target_universe requires target universe")
            if self.disease_id is not None and not isinstance(self.disease_id, str): raise ValueError("invalid disease_id")
    @property
    def target_universe_hash(self) -> str: return universe_hash(self.target_universe, self.target_identifier_type)
    def identity_payload(self) -> dict[str, Any]: return {"request_schema_id":self.request_schema_id,"request_schema_version":self.request_schema_version,"query_type":self.query_type,"endpoint_identity":self.endpoint_identity,"requested_source_release":self.requested_source_release,"release_verification_required":self.release_verification_required,"query_schema_version":self.query_schema_version,"disease_id":self.disease_id,"association_scope":self.association_scope,"target_identifier_type":self.target_identifier_type,"target_universe":list(self.target_universe),"target_universe_hash":self.target_universe_hash,"page_size":self.page_size,"max_pages":self.max_pages,"timeout_seconds":self.timeout_seconds,"requesting_actor":self.requesting_actor,"cache_policy":self.cache_policy}
    @property
    def request_id(self) -> str: return identity("otfr", self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "request_id":self.request_id, "operational_timestamp":_timestamp(self.operational_timestamp)}

@dataclass(frozen=True)
class OpenTargetsTargetResolution:
    requested_identifier: str; requested_identifier_type: str; status: str
    approved_symbol: str | None = None; ensembl_gene_id: str | None = None; approved_name: str | None = None
    candidates: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (); source_release: str = "not_reported"; source_record_provenance: Mapping[str, Any] = None; error_codes: tuple[str, ...] | list[str] = ()
    resolution_format_version: str = "v1"
    def __post_init__(self) -> None:
        if self.status not in RESOLUTION_STATUSES: raise ValueError("unknown resolution status")
        if self.requested_identifier_type not in {"gene_symbol", "ensembl_gene_id"}: raise ValueError("invalid identifier type")
        if self.requested_identifier_type == "ensembl_gene_id" and not _ENSEMBL.fullmatch(self.requested_identifier):
            if self.status != "invalid_identifier": raise ValueError("invalid Ensembl identifier")
        object.__setattr__(self, "candidates", tuple(_freeze(v) for v in self.candidates)); object.__setattr__(self, "source_record_provenance", _freeze(self.source_record_provenance or {})); object.__setattr__(self, "error_codes", _clean_errors(self.error_codes))
        if self.status == "resolved_exact" and (not self.ensembl_gene_id or (self.requested_identifier_type == "gene_symbol" and not self.approved_symbol)): raise ValueError("resolved exact needs an Ensembl ID and an exact symbol when a symbol was requested")
        if self.status == "ambiguous" and not self.candidates: raise ValueError("ambiguous result needs candidates")
    def identity_payload(self) -> dict[str, Any]: return {"resolution_format_version":self.resolution_format_version,"requested_identifier":self.requested_identifier,"requested_identifier_type":self.requested_identifier_type,"status":self.status,"approved_symbol":self.approved_symbol,"ensembl_gene_id":self.ensembl_gene_id,"approved_name":self.approved_name,"candidates":thaw(self.candidates),"source_release":self.source_release,"source_record_provenance":thaw(self.source_record_provenance),"error_codes":list(self.error_codes)}
    @property
    def resolution_id(self) -> str: return identity("otres", self.identity_payload())

@dataclass(frozen=True)
class OpenTargetsTransportResponse:
    operation_id: str; status_code: int; payload: Mapping[str, Any]; source_release: str | None = None; error_codes: tuple[str, ...] | list[str] = (); retry_count: int = 0; retrieval_timestamp: datetime | None = None; response_format_version: str = "v1"
    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping): raise ValueError("malformed JSON payload")
        object.__setattr__(self, "payload", _freeze(self.payload)); object.__setattr__(self, "error_codes", _clean_errors(self.error_codes))
    @property
    def payload_sha256(self) -> str: return payload_hash(self.payload)
    @property
    def payload_id(self) -> str: return identity("otpayload", {"operation_id":self.operation_id,"payload_sha256":self.payload_sha256})

@dataclass(frozen=True)
class OpenTargetsTargetRecord:
    request_id: str; target_id: str | None; ensembl_gene_id: str | None; approved_symbol: str | None; approved_name: str | None; disease_id: str | None; association: Mapping[str, Any] | None; source_fields: Mapping[str, Any]; source_release: str; release_verification_state: str; source_query_id: str; raw_payload_id: str; availability_state: str = "observed"; limitations: tuple[str, ...] | list[str] = (); record_format_version: str = "v1"
    def __post_init__(self) -> None:
        if self.release_verification_state not in RELEASE_VERIFICATION_STATES: raise ValueError("invalid release verification state")
        object.__setattr__(self,"association",_freeze(self.association) if self.association is not None else None); object.__setattr__(self,"source_fields",_freeze(self.source_fields)); object.__setattr__(self,"limitations",tuple(self.limitations))
    def identity_payload(self) -> dict[str, Any]: return {"record_format_version":self.record_format_version,"request_id":self.request_id,"target_id":self.target_id,"ensembl_gene_id":self.ensembl_gene_id,"approved_symbol":self.approved_symbol,"approved_name":self.approved_name,"disease_id":self.disease_id,"association":thaw(self.association),"source_fields":thaw(self.source_fields),"source_release":self.source_release,"release_verification_state":self.release_verification_state,"source_query_id":self.source_query_id,"raw_payload_id":self.raw_payload_id,"availability_state":self.availability_state,"limitations":list(self.limitations)}
    @property
    def record_id(self) -> str: return identity("otrec", self.identity_payload())

@dataclass(frozen=True)
class OpenTargetsQueryPlan:
    request: OpenTargetsFetchRequest; operations: tuple[Mapping[str, Any], ...]; query_document_hash: str; expected_operation_count: int; plan_format_version: str = "v1"
    def __post_init__(self): object.__setattr__(self,"operations",tuple(_freeze(v) for v in self.operations))
    @property
    def plan_id(self) -> str: return identity("otplan", {"plan_format_version":self.plan_format_version,"request_id":self.request.request_id,"operations":thaw(self.operations),"query_document_hash":self.query_document_hash,"expected_operation_count":self.expected_operation_count,"no_score_or_ranking":True})

@dataclass(frozen=True)
class OpenTargetsCoverageReport:
    request_id: str; query_type: str; terminal_categories: Mapping[str, tuple[str, ...] | list[str]]; truncated: bool = False; coverage_format_version: str = "v1"
    def __post_init__(self):
        categories = {k: tuple(sorted(v)) for k,v in self.terminal_categories.items()}; object.__setattr__(self,"terminal_categories",_freeze(categories))
    def count(self, category: str) -> int: return len(self.terminal_categories.get(category, ()))
    @property
    def requested_target_count(self) -> int: return self.coverage_denominator
    @property
    def unique_requested_target_count(self) -> int: return self.coverage_denominator
    @property
    def resolved_target_count(self) -> int: return self.count("resolved_and_retrieved") + self.count("resolved_no_record")
    @property
    def unresolved_target_count(self) -> int: return self.count("unresolved")
    @property
    def ambiguous_target_count(self) -> int: return self.count("ambiguous")
    @property
    def retrieved_target_count(self) -> int: return self.count("resolved_and_retrieved")
    @property
    def no_record_target_count(self) -> int: return self.count("resolved_no_record")
    @property
    def failed_target_count(self) -> int: return self.count("retrieval_failed")
    @property
    def coverage_is_scientific_confidence(self) -> bool: return False
    @property
    def coverage_numerator(self) -> int: return self.count("resolved_and_retrieved") + self.count("resolved_no_record")
    @property
    def coverage_denominator(self) -> int: return sum(len(v) for v in self.terminal_categories.values())
    @property
    def coverage_ratio(self) -> tuple[int, int]:
        """Stable numerator/denominator representation; this is not confidence."""
        return (self.coverage_numerator, self.coverage_denominator)
    @property
    def coverage_fraction(self) -> str:
        """Zero-safe, deterministic rendering of :attr:`coverage_ratio`."""
        numerator, denominator = self.coverage_ratio
        return f"{numerator}/{denominator}"
    @property
    def coverage_id(self) -> str: return identity("otcov", {"coverage_format_version":self.coverage_format_version,"request_id":self.request_id,"query_type":self.query_type,"terminal_categories":thaw(self.terminal_categories),"truncated":self.truncated,"coverage_numerator":self.coverage_numerator,"coverage_denominator":self.coverage_denominator,"not_scientific_confidence":True})

@dataclass(frozen=True)
class OpenTargetsFetchResult:
    status: str; request: OpenTargetsFetchRequest; query_plan: OpenTargetsQueryPlan; cache_identity: str; release_verification_state: str; resolutions: tuple[OpenTargetsTargetResolution, ...] | list[OpenTargetsTargetResolution]; records: tuple[OpenTargetsTargetRecord, ...] | list[OpenTargetsTargetRecord]; coverage_report: OpenTargetsCoverageReport; error_codes: tuple[str, ...] | list[str] = (); cache_origin: str = "live_transport"; observed_source_release: str | None = None; operational_timestamp: datetime | None = None; result_format_version: str = "v1"
    def __post_init__(self):
        if self.status not in RESULT_STATUSES or self.release_verification_state not in RELEASE_VERIFICATION_STATES: raise ValueError("unknown result controlled value")
        object.__setattr__(self,"resolutions",tuple(sorted(self.resolutions,key=lambda x:x.resolution_id))); object.__setattr__(self,"records",tuple(sorted(self.records,key=lambda x:x.record_id))); object.__setattr__(self,"error_codes",_clean_errors(self.error_codes))
    @property
    def result_id(self) -> str: return identity("otresult", {"result_format_version":self.result_format_version,"status":self.status,"request_id":self.request.request_id,"plan_id":self.query_plan.plan_id,"cache_identity":self.cache_identity,"release_verification_state":self.release_verification_state,"observed_source_release":self.observed_source_release,"resolution_ids":[x.resolution_id for x in self.resolutions],"record_ids":[x.record_id for x in self.records],"coverage_id":self.coverage_report.coverage_id,"error_codes":list(self.error_codes),"no_score_or_ranking":True})
