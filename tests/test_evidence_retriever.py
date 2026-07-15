from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from targetintel.evidence.retriever import (
    EUROPE_PMC_API_IDENTIFIER,
    EUROPE_PMC_SEARCH_URL,
    REQUEST_PARAMETERS,
    REQUEST_TIMEOUT_SECONDS,
    EuropePMCRetriever,
    build_europe_pmc_query,
)
from targetintel.evidence.store import EvidenceStore


UTC = datetime(2026, 7, 15, 12, 13, 14, 123456, tzinfo=timezone.utc)


class Response:
    def __init__(self, status_code: int, payload: object = None, error: Exception | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self._error = error

    def json(self) -> object:
        if self._error is not None:
            raise self._error
        return self._payload


class Client:
    def __init__(self, response: Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, object, int]] = []

    def get(self, url: str, *, params: object, timeout: int) -> Response:
        self.calls.append((url, params, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def retriever(client: Client, store: EvidenceStore | None = None) -> EuropePMCRetriever:
    return EuropePMCRetriever(
        evidence_store=store,
        http_client=client,
        clock=lambda: UTC,
        retrieval_attempt_id_factory=lambda: "attempt-1",
    )


def test_query_has_fixed_target_disease_and_optional_treatment_order() -> None:
    assert build_europe_pmc_query("B2M", "melanoma") == '"B2M" AND "melanoma"'
    assert build_europe_pmc_query("B2M", "melanoma", "anti-PD-1") == (
        '"B2M" AND "melanoma" AND "anti-PD-1"'
    )


def test_query_normalises_whitespace_and_escapes_terms() -> None:
    assert build_europe_pmc_query('  B2M\\"x  ', "\tcutaneous\nmelanoma ") == (
        '"B2M\\\\\\"x" AND "cutaneous melanoma"'
    )


@pytest.mark.parametrize("target,disease", [("", "melanoma"), ("  ", "melanoma"), ("B2M", "\t")])
def test_query_rejects_missing_required_context(target: str, disease: str) -> None:
    with pytest.raises(ValueError):
        build_europe_pmc_query(target, disease)


def test_success_normalises_documents_and_persists_one_attempt(tmp_path: Path) -> None:
    client = Client(Response(200, {"resultList": {"result": [{
        "source": "MED", "id": "123", "title": "A title", "abstractText": "An abstract",
        "journalTitle": "A journal", "firstPublicationDate": "2025-01-01", "pmid": "123",
    }]}}))
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        result = retriever(client, store).search(" B2M ", " melanoma ")
        assert result.attempt.status == "success"
        assert result.attempt.result_count == 1
        assert result.documents[0].stable_source_identity == "MED:123"
        assert result.documents[0].doi is None
        assert store.list_items() == []
        assert store.list_retrieval_attempts() == [result.attempt]
    assert client.calls == [(
        EUROPE_PMC_SEARCH_URL,
        {"query": '"B2M" AND "melanoma"', **REQUEST_PARAMETERS},
        REQUEST_TIMEOUT_SECONDS,
    )]


@pytest.mark.parametrize(
    ("response", "expected_status", "category"),
    [
        (Response(200, {"resultList": {"result": []}}), "success_zero_results", None),
        (requests.Timeout(), "failed", "timeout"),
        (requests.ConnectionError(), "failed", "network"),
        (Response(503), "failed", "http"),
        (Response(200, error=ValueError("not json")), "failed", "invalid_response"),
    ],
)
def test_outcomes_persist_exactly_one_attempt_and_never_create_evidence(
    tmp_path: Path, response: Response | Exception, expected_status: str, category: str | None,
) -> None:
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        result = retriever(Client(response), store).search("B2M", "melanoma")
        assert result.attempt.status == expected_status
        assert result.attempt.error_category == category
        assert result.attempt.timestamp == UTC
        assert result.attempt.source_release_or_api_version == EUROPE_PMC_API_IDENTIFIER
        assert result.attempt.query == '"B2M" AND "melanoma"'
        assert store.list_retrieval_attempts() == [result.attempt]
        assert store.list_items() == []


def test_explicit_not_executed_is_persisted_without_http_or_evidence(tmp_path: Path) -> None:
    client = Client(Response(200, {"resultList": {"result": []}}))
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        result = retriever(client, store).search("B2M", "melanoma", execute=False)
        assert result.attempt.status == "not_executed"
        assert result.attempt.result_count is None
        assert result.documents == ()
        assert client.calls == []
        assert store.list_retrieval_attempts() == [result.attempt]
        assert store.list_items() == []


def test_all_statuses_survive_duckdb_round_trip(tmp_path: Path) -> None:
    responses: list[Response | Exception | None] = [
        Response(200, {"resultList": {"result": [{"source": "MED", "id": "1"}]}}),
        Response(200, {"resultList": {"result": []}}),
        requests.Timeout(),
        None,
    ]
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        for index, response in enumerate(responses):
            client = Client(Response(200) if response is None else response)
            EuropePMCRetriever(
                evidence_store=store, http_client=client, clock=lambda: UTC,
                retrieval_attempt_id_factory=lambda index=index: f"attempt-{index}",
            ).search("B2M", "melanoma", execute=response is not None)
        assert [attempt.status for attempt in store.list_retrieval_attempts()] == [
            "success", "success_zero_results", "failed", "not_executed",
        ]


def test_repeated_mocked_response_has_reproducible_normalised_output() -> None:
    payload = {"resultList": {"result": [{"source": "PMC", "id": "PMC1", "title": "Same"}]}}
    first = retriever(Client(Response(200, payload))).search(" B2M", "melanoma ")
    second = retriever(Client(Response(200, payload))).search(" B2M", "melanoma ")
    assert first == second
