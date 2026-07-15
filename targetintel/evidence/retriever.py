"""Deterministic, retrieval-only Europe PMC search support.

This module deliberately stops at source-document metadata.  It neither
interprets literature nor constructs :class:`~targetintel.evidence.models.EvidenceItem`
objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

import requests

from .models import RetrievalAttempt
from .store import EvidenceStore


EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
"""Europe PMC's documented REST search endpoint."""

EUROPE_PMC_API_IDENTIFIER = "Europe PMC REST search API"
"""Truthful identifier for the source API; no unverified release is inferred."""

REQUEST_TIMEOUT_SECONDS = 10
REQUEST_PARAMETERS = {"format": "json", "resultType": "core", "pageSize": 25}

_WHITESPACE = re.compile(r"\s+")


class _HttpClient(Protocol):
    def get(self, url: str, *, params: Mapping[str, str | int], timeout: int) -> Any: ...


@dataclass(frozen=True)
class EuropePMCDocument:
    """A small, non-interpretive normalized Europe PMC result record.

    ``source`` and ``source_id`` together retain the stable source identity.
    Optional fields remain ``None`` when the response did not return them.
    """

    source: str
    source_id: str
    title: str | None = None
    abstract_text: str | None = None
    journal_title: str | None = None
    publication_date: str | None = None
    author_string: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None

    @property
    def stable_source_identity(self) -> str:
        """Return the source-qualified, stable record identity."""
        return f"{self.source}:{self.source_id}"


# The longer name is useful to callers that do not need to know the source's
# response-specific naming.  It intentionally denotes the same immutable type.
RetrievedLiteratureRecord = EuropePMCDocument


@dataclass(frozen=True)
class EuropePMCRetrievalResult:
    """One requested retrieval outcome and any returned source documents."""

    attempt: RetrievalAttempt
    documents: tuple[EuropePMCDocument, ...]


def _normalise_context(value: str, field: str, *, required: bool) -> str | None:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    normalised = _WHITESPACE.sub(" ", value.strip())
    if not normalised:
        if required:
            raise ValueError(f"{field} must be non-empty")
        return None
    return normalised


def _quote_term(value: str) -> str:
    """Return a Europe PMC phrase term with deterministic escaping."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_europe_pmc_query(
    target_identifier: str,
    disease_context: str,
    treatment_context: str | None = None,
) -> str:
    """Build a fixed-order, phrase-only Europe PMC query.

    Inputs undergo only whitespace collapsing.  The resulting terms appear in
    the documented order target, disease, then optional treatment; no synonym,
    identifier, case, or ontology interpretation is applied.
    """
    target = _normalise_context(target_identifier, "target_identifier", required=True)
    disease = _normalise_context(disease_context, "disease_context", required=True)
    if treatment_context is not None and not isinstance(treatment_context, str):
        raise ValueError("treatment_context must be a string or null")
    treatment = (
        None if treatment_context is None
        else _normalise_context(treatment_context, "treatment_context", required=False)
    )
    terms = [_quote_term(target), _quote_term(disease)]
    if treatment is not None:
        terms.append(_quote_term(treatment))
    return " AND ".join(terms)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_timestamp(clock: Callable[[], datetime]) -> datetime:
    timestamp = clock()
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return timestamp.astimezone(timezone.utc)


def _optional_string(record: Mapping[str, Any], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Europe PMC result field {field!r} must be a string when present")
    return value


def _normalise_documents(payload: Any) -> tuple[EuropePMCDocument, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("Europe PMC response must be a JSON object")
    result_list = payload.get("resultList")
    if not isinstance(result_list, Mapping):
        raise ValueError("Europe PMC response must contain resultList")
    records = result_list.get("result")
    if not isinstance(records, list):
        raise ValueError("Europe PMC response must contain a result list")
    documents: list[EuropePMCDocument] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("Europe PMC result must be a JSON object")
        source = _optional_string(record, "source")
        source_id = _optional_string(record, "id")
        if not source or not source_id:
            raise ValueError("Europe PMC result must contain non-empty source and id")
        documents.append(EuropePMCDocument(
            source=source,
            source_id=source_id,
            title=_optional_string(record, "title"),
            abstract_text=_optional_string(record, "abstractText"),
            journal_title=_optional_string(record, "journalTitle"),
            publication_date=_optional_string(record, "firstPublicationDate"),
            author_string=_optional_string(record, "authorString"),
            doi=_optional_string(record, "doi"),
            pmid=_optional_string(record, "pmid"),
            pmcid=_optional_string(record, "pmcid"),
        ))
    return tuple(documents)


class EuropePMCRetriever:
    """Small injectable Europe PMC client that always records one outcome."""

    def __init__(
        self,
        *,
        evidence_store: EvidenceStore | None = None,
        http_client: _HttpClient | None = None,
        session: _HttpClient | None = None,
        clock: Callable[[], datetime] = _utc_now,
        retrieval_attempt_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if http_client is not None and session is not None:
            raise ValueError("provide either http_client or session, not both")
        self._evidence_store = evidence_store
        self._http_client = (
            requests.Session()
            if http_client is None and session is None
            else (http_client or session)
        )
        self._clock = clock
        self._retrieval_attempt_id_factory = retrieval_attempt_id_factory or (lambda: str(uuid4()))

    def search(
        self,
        target_identifier: str,
        disease_context: str,
        treatment_context: str | None = None,
        *,
        execute: bool = True,
    ) -> EuropePMCRetrievalResult:
        """Execute (or explicitly skip) one deterministic Europe PMC search."""
        target = _normalise_context(target_identifier, "target_identifier", required=True)
        disease = _normalise_context(disease_context, "disease_context", required=True)
        treatment = (
            None
            if treatment_context is None
            else _normalise_context(treatment_context, "treatment_context", required=False)
        )
        query = build_europe_pmc_query(target, disease, treatment)
        attempt_id = self._retrieval_attempt_id_factory()
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValueError("retrieval_attempt_id_factory must return a non-empty string")

        status = "not_executed"
        result_count: int | None = None
        error_category: str | None = None
        documents: tuple[EuropePMCDocument, ...] = ()
        if execute:
            try:
                response = self._http_client.get(
                    EUROPE_PMC_SEARCH_URL,
                    params={"query": query, **REQUEST_PARAMETERS},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                status_code = getattr(response, "status_code", None)
                if not isinstance(status_code, int) or not 200 <= status_code < 300:
                    raise _HttpFailure()
                documents = _normalise_documents(response.json())
                result_count = len(documents)
                status = "success" if documents else "success_zero_results"
            except requests.Timeout:
                status, error_category = "failed", "timeout"
            except requests.HTTPError:
                status, error_category = "failed", "http"
            except requests.RequestException:
                status, error_category = "failed", "network"
            except OSError:
                status, error_category = "failed", "network"
            except _HttpFailure:
                status, error_category = "failed", "http"
            except (ValueError, TypeError, AttributeError):
                status, error_category = "failed", "invalid_response"

        attempt = RetrievalAttempt(
            retrieval_attempt_id=attempt_id,
            target_identifier=target,
            disease_context=disease,
            treatment_context=treatment,
            source="Europe PMC",
            query=query,
            timestamp=_utc_timestamp(self._clock),
            status=status,
            result_count=result_count,
            error_category=error_category,
            source_release_or_api_version=EUROPE_PMC_API_IDENTIFIER,
        )
        if self._evidence_store is not None:
            self._evidence_store.record_retrieval_attempt(attempt)
        return EuropePMCRetrievalResult(attempt=attempt, documents=documents)


class _HttpFailure(Exception):
    """Internal sentinel that prevents HTTP failures becoming response parsing."""
