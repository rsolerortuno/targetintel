"""Offline, deterministic extraction of frozen evidence fixtures.

This module emits staging candidates only.  It deliberately has no retrieval,
provider, subprocess, or storage dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence

from .models import EvidenceItem, FAMILY_ALGORITHM_VERSION, ProvenanceStep
from .validation import require_valid


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _required_string(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string or null")
    return value


def _parse_utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 datetime")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 datetime") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return timestamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class SourceDocument:
    """Frozen source material and fixture-controlled extraction candidates.

    ``source_text`` is retained verbatim for literal literature quotations;
    ``structured_content`` is available for frozen computed/database fixtures.
    Candidate mappings are fixture data, never generated scientific content.
    """

    source: str
    source_id: str
    target_symbol: str
    target_id: str | None
    disease_name: str
    disease_id: str
    treatment_name: str | None
    treatment_id: str | None
    document_location: str | None
    source_text: str | None
    structured_content: Mapping[str, Any] | None
    publication_id: str | None
    source_dataset_id: str | None
    patient_cohort_id: str | None
    experiment_id: str | None
    retrieved_at: datetime | None
    data_release: str | None
    fixture_id: str
    candidates: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if self.source_text is None and self.structured_content is None:
            raise ValueError("source_text or structured_content is required")
        if self.source_text is not None and not isinstance(self.source_text, str):
            raise ValueError("source_text must be a string or null")
        if self.structured_content is not None:
            object.__setattr__(self, "structured_content", _freeze(self.structured_content))
        object.__setattr__(self, "candidates", tuple(_freeze(candidate) for candidate in self.candidates))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceDocument":
        if not isinstance(data, Mapping):
            raise ValueError("frozen source document must be a JSON object")
        source_text = data.get("source_text")
        if source_text is not None and not isinstance(source_text, str):
            raise ValueError("source_text must be a string or null")
        structured_content = data.get("structured_content")
        if structured_content is not None and not isinstance(structured_content, Mapping):
            raise ValueError("structured_content must be an object or null")
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("candidates must be a non-empty list")
        if not all(isinstance(candidate, Mapping) for candidate in candidates):
            raise ValueError("each candidate must be an object")
        retrieved_at = data.get("retrieved_at")
        return cls(
            source=_required_string(data, "source"),
            source_id=_required_string(data, "source_id"),
            target_symbol=_required_string(data, "target_symbol"),
            target_id=_optional_string(data, "target_id"),
            disease_name=_required_string(data, "disease_name"),
            disease_id=_required_string(data, "disease_id"),
            treatment_name=_optional_string(data, "treatment_name"),
            treatment_id=_optional_string(data, "treatment_id"),
            document_location=_optional_string(data, "document_location"),
            source_text=source_text,
            structured_content=structured_content,
            publication_id=_optional_string(data, "publication_id"),
            source_dataset_id=_optional_string(data, "source_dataset_id"),
            patient_cohort_id=_optional_string(data, "patient_cohort_id"),
            experiment_id=_optional_string(data, "experiment_id"),
            retrieved_at=None if retrieved_at is None else _parse_utc_datetime(retrieved_at, "retrieved_at"),
            data_release=_optional_string(data, "data_release"),
            fixture_id=_required_string(data, "fixture_id"),
            candidates=tuple(candidates),
        )


class Extractor(Protocol):
    """Provider-neutral, side-effect-free staging extractor interface."""

    def extract(self, document: SourceDocument) -> Sequence[EvidenceItem]: ...


CandidateIdFactory = Callable[[SourceDocument, Mapping[str, Any], int], str]
Clock = Callable[[], datetime]


def _default_candidate_id(
    document: SourceDocument, candidate: Mapping[str, Any], index: int
) -> str:
    return f"ev_mock_{_required_string(candidate, 'fixture_candidate_id')}"


def _clock_timestamp(clock: Clock) -> datetime:
    timestamp = clock()
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return timestamp.astimezone(timezone.utc)


class MockExtractor:
    """Extract fixture-controlled staging candidates without I/O or inference."""

    def __init__(
        self,
        *,
        evidence_id_factory: CandidateIdFactory = _default_candidate_id,
        clock: Clock | None = None,
    ) -> None:
        self._evidence_id_factory = evidence_id_factory
        self._clock = clock

    def extract(self, document: SourceDocument) -> tuple[EvidenceItem, ...]:
        if not isinstance(document, SourceDocument):
            raise TypeError("document must be a SourceDocument")
        ordered = sorted(document.candidates, key=lambda candidate: _required_string(candidate, "fixture_candidate_id"))
        items: list[EvidenceItem] = []
        for index, candidate in enumerate(ordered):
            items.append(self._extract_candidate(document, candidate, index))
        return tuple(items)

    def _extract_candidate(
        self, document: SourceDocument, candidate: Mapping[str, Any], index: int
    ) -> EvidenceItem:
        fixture_candidate_id = _required_string(candidate, "fixture_candidate_id")
        quoted_span = _optional_string(candidate, "quoted_span")
        if quoted_span is not None:
            if document.source_text is None or quoted_span not in document.source_text:
                raise ValueError("quoted_span must occur literally in source_text")
        computed_support = _optional_string(candidate, "computed_support")
        if quoted_span is None and computed_support is None:
            raise ValueError("candidate requires quoted_span or computed_support")
        retrieved_at = document.retrieved_at
        if retrieved_at is None:
            if self._clock is None:
                raise ValueError("retrieved_at is required unless an injected clock is provided")
            retrieved_at = _clock_timestamp(self._clock)
        evidence_id = self._evidence_id_factory(document, candidate, index)
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("evidence_id_factory must return a non-empty string")
        item = EvidenceItem(
            evidence_id=evidence_id,
            target_symbol=document.target_symbol,
            target_id=document.target_id,
            disease_name=document.disease_name,
            disease_id=document.disease_id,
            treatment_name=document.treatment_name,
            treatment_id=document.treatment_id,
            evidence_type=_required_string(candidate, "evidence_type"),
            evidence_direction=_required_string(candidate, "evidence_direction"),
            observation=_required_string(candidate, "observation"),
            interpretation=None,
            source=document.source,
            source_id=document.source_id,
            document_location=_optional_string(candidate, "document_location") or document.document_location,
            quoted_span=quoted_span,
            computed_support=computed_support,
            publication_id=_optional_string(candidate, "publication_id") or document.publication_id,
            source_dataset_id=_optional_string(candidate, "source_dataset_id") or document.source_dataset_id,
            patient_cohort_id=_optional_string(candidate, "patient_cohort_id") or document.patient_cohort_id,
            experiment_id=_optional_string(candidate, "experiment_id") or document.experiment_id,
            comparison=_optional_string(candidate, "comparison"),
            endpoint=_optional_string(candidate, "endpoint"),
            data_modality=_optional_string(candidate, "data_modality"),
            species=_required_string(candidate, "species"),
            model_system=_required_string(candidate, "model_system"),
            sample_context=_optional_string(candidate, "sample_context"),
            effect_size=candidate.get("effect_size"),
            effect_size_metric=_optional_string(candidate, "effect_size_metric"),
            uncertainty=candidate.get("uncertainty"),
            uncertainty_metric=_optional_string(candidate, "uncertainty_metric"),
            sample_size=candidate.get("sample_size"),
            extraction_method="mock",
            extraction_confidence=candidate.get("extraction_confidence", 1.0),
            validation_status="extracted",
            retrieved_at=retrieved_at,
            data_release=_optional_string(candidate, "data_release") or document.data_release,
            derived_from=tuple(candidate.get("derived_from", ())),
            evidence_family=None,
            evidence_family_algorithm_version=FAMILY_ALGORITHM_VERSION,
            evidence_family_basis="ineligible",
            independence_eligible=False,
            independence_ineligibility_reason="evidence-family assignment pending staging finalization",
            record_hash=None,
            provenance_history=(ProvenanceStep(
                "extraction",
                retrieved_at,
                {
                    "method": "mock",
                    "fixture_source": document.fixture_id,
                    "fixture_candidate_id": fixture_candidate_id,
                },
            ),),
        )
        require_valid(item)
        return item
