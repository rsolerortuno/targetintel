"""Immutable evidence-layer data contracts and canonical serialization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping


CANONICALIZATION_VERSION = "evidence-canonical-json-v1"
FAMILY_ALGORITHM_VERSION = "efam-v1"

EVIDENCE_TYPES = frozenset({"clinical_cohort", "in_vivo_model", "in_vitro_model", "genetic_association", "functional_genomics", "expression_profiling", "tractability", "safety_signal", "known_drug", "database_assertion"})
EVIDENCE_DIRECTIONS = frozenset({"supports_target", "supports_biomarker", "contradicts_target", "limits_target", "neutral"})
SPECIES = frozenset({"human", "mouse", "rat", "zebrafish", "non_human_primate", "other", "not_applicable", "unknown"})
MODEL_SYSTEMS = frozenset({"patient_tumor_biopsy", "patient_derived_xenograft", "cell_line", "organoid", "co_culture", "syngeneic_mouse_model", "in_silico", "database", "other", "unknown"})
EXTRACTION_METHODS = frozenset({"manual", "llm", "rule_based", "database_import", "computed", "mock"})
VALIDATION_STATUSES = frozenset({"extracted", "schema_verified", "semantic_verified", "citation_verified", "manually_curated", "citation_unverified", "rejected"})
FINAL_VALIDATION_STATUSES = frozenset({"citation_verified", "manually_curated", "citation_unverified", "rejected"})
FAMILY_BASES = frozenset({"patient_cohort_id", "source_dataset_id", "experiment_id", "publication_id", "stable_source_record", "composite", "ineligible"})
RETRIEVAL_STATUSES = frozenset({"not_executed", "success", "success_zero_results", "failed"})


def _isoformat(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 datetime") from exc
    return parsed


def _normalise_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


_HORIZONTAL_WHITESPACE = re.compile(r"[\t\f\v ]+")


def _canonical_value(value: Any, *, quoted_span: bool = False) -> Any:
    if isinstance(value, str):
        value = _normalise_line_endings(value)
        return value if quoted_span else _HORIZONTAL_WHITESPACE.sub(" ", value.strip())
    if isinstance(value, datetime):
        return _isoformat(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item, quoted_span=(str(key) == "quoted_span"))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic v0.2.0 canonical JSON for a JSON-compatible value."""
    return json.dumps(
        _canonical_value(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )


@dataclass(frozen=True)
class ProvenanceStep:
    """One append-only provenance event retained with an evidence observation."""

    step_type: str
    recorded_at: datetime
    details: Mapping[str, Any]
    is_operational: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self, *, include_operational_timestamp: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "step_type": self.step_type,
            "details": dict(self.details),
            "is_operational": self.is_operational,
        }
        if include_operational_timestamp or not self.is_operational:
            result["recorded_at"] = _isoformat(self.recorded_at)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProvenanceStep":
        return cls(
            step_type=data["step_type"], recorded_at=_parse_datetime(data["recorded_at"], "recorded_at"),
            details=data["details"], is_operational=data.get("is_operational", False),
        )


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    target_symbol: str
    target_id: str | None
    disease_name: str
    disease_id: str
    treatment_name: str | None
    treatment_id: str | None
    evidence_type: str
    evidence_direction: str
    observation: str
    interpretation: str | None
    source: str
    source_id: str
    document_location: str | None
    quoted_span: str | None
    computed_support: str | None
    publication_id: str | None
    source_dataset_id: str | None
    patient_cohort_id: str | None
    experiment_id: str | None
    comparison: str | None
    endpoint: str | None
    data_modality: str | None
    species: str
    model_system: str
    sample_context: str | None
    effect_size: float | int | None
    effect_size_metric: str | None
    uncertainty: float | int | None
    uncertainty_metric: str | None
    sample_size: int | None
    extraction_method: str
    extraction_confidence: float | int | None
    validation_status: str
    retrieved_at: datetime
    data_release: str | None
    derived_from: tuple[str, ...] | list[str]
    evidence_family: str | None
    evidence_family_algorithm_version: str
    evidence_family_basis: str
    independence_eligible: bool
    independence_ineligibility_reason: str | None
    record_hash: str | None
    provenance_history: tuple[ProvenanceStep, ...] | list[ProvenanceStep]

    def __post_init__(self) -> None:
        object.__setattr__(self, "derived_from", tuple(self.derived_from))
        object.__setattr__(self, "provenance_history", tuple(self.provenance_history))

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["retrieved_at"] = _isoformat(self.retrieved_at)
        result["derived_from"] = list(self.derived_from)
        result["provenance_history"] = [step.to_dict() for step in self.provenance_history]
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceItem":
        values = dict(data)
        values["retrieved_at"] = _parse_datetime(values["retrieved_at"], "retrieved_at")
        values["provenance_history"] = [ProvenanceStep.from_dict(step) for step in values["provenance_history"]]
        return cls(**values)

    def hash_payload(self) -> dict[str, Any]:
        """The complete hash-covered representation, excluding identity and hash."""
        payload = self.to_dict()
        del payload["evidence_id"]
        del payload["record_hash"]
        payload["derived_from"] = sorted(payload["derived_from"])
        payload["provenance_history"] = [
            step.to_dict(include_operational_timestamp=False)
            for step in self.provenance_history
        ]
        return payload

    def canonical_json(self) -> str:
        return canonical_json(self.hash_payload())

    def calculate_record_hash(self) -> str:
        from .validation import require_finalizable

        require_finalizable(self)
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def with_calculated_record_hash(self) -> "EvidenceItem":
        return replace(self, record_hash=self.calculate_record_hash())

    def has_exact_content(self, other: "EvidenceItem") -> bool:
        return self.calculate_record_hash() == other.calculate_record_hash()


@dataclass(frozen=True)
class RetrievalAttempt:
    retrieval_attempt_id: str
    target_identifier: str
    disease_context: str
    treatment_context: str | None
    source: str
    query: str
    timestamp: datetime
    status: str
    result_count: int | None
    error_category: str | None
    source_release_or_api_version: str | None

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["timestamp"] = _isoformat(self.timestamp)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RetrievalAttempt":
        values = dict(data)
        values["timestamp"] = _parse_datetime(values["timestamp"], "timestamp")
        return cls(**values)
