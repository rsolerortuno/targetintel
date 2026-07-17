"""Offline acceptance tests for immutable grounded-extraction staging."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from targetintel.llm import (
    LLMResponse,
    LLMResultStatus,
    ProviderErrorCategory,
    ProviderProvenance,
    extract_grounded_candidates,
)
from targetintel.llm.grounded_prompt import build_grounded_extraction_request
from targetintel.llm.grounded_schema import (
    GROUNDED_EXTRACTION_SCHEMA_ID,
    GROUNDED_EXTRACTION_SCHEMA_VERSION,
)


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "llm"
_SOURCE = (_FIXTURE_DIR / "grounded_extraction_source.txt").read_text(encoding="utf-8")
_SUCCESS = json.loads((_FIXTURE_DIR / "grounded_extraction_success.json").read_text(encoding="utf-8"))
_FAILURES = json.loads((_FIXTURE_DIR / "grounded_extraction_failures.json").read_text(encoding="utf-8"))


def _request():
    return build_grounded_extraction_request(
        request_id="request", source_document_id="doc-1", source_text=_SOURCE
    )


def _error_category(status):
    return {
        LLMResultStatus.MALFORMED_OUTPUT: ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE,
        LLMResultStatus.RETRYABLE_FAILURE: ProviderErrorCategory.RETRYABLE_PROVIDER_FAILURE,
        LLMResultStatus.PERMANENT_FAILURE: ProviderErrorCategory.PERMANENT_PROVIDER_FAILURE,
        LLMResultStatus.TIMEOUT: ProviderErrorCategory.TIMEOUT,
        LLMResultStatus.NOT_EXECUTED: ProviderErrorCategory.NOT_EXECUTED,
    }[status]


def _response(output, status=LLMResultStatus.SUCCESS, *, latency=1, responded_at=None,
              request_id="request", source_document_id="doc-1", schema_id=GROUNDED_EXTRACTION_SCHEMA_ID,
              schema_version=GROUNDED_EXTRACTION_SCHEMA_VERSION, raw_text=None):
    request = _request()
    category = None if status is LLMResultStatus.SUCCESS else _error_category(status)
    provenance = ProviderProvenance(
        request_id, "mock", "returned", None, request.prompt_id, request.prompt_version,
        schema_id, schema_version, request.task_type, source_document_id, status, category,
        requested_model_name="requested",
    )
    return LLMResponse(
        provenance, raw_text=raw_text, structured_output=output, latency_ms=latency,
        responded_at=responded_at,
    )


def _output(claims, **changes):
    output = {
        "schema_id": GROUNDED_EXTRACTION_SCHEMA_ID,
        "schema_version": GROUNDED_EXTRACTION_SCHEMA_VERSION,
        "source_document_id": "doc-1",
        "claims": claims,
    }
    output.update(changes)
    return output


def _claim(**changes):
    value = {
        "claim_text": "B2M loss was observed.",
        "quoted_span": "B2M loss was observed",
        "quote_start": 0,
        "quote_end": 21,
        "stance": "supports",
        "target_mentions": ["B2M"],
    }
    value.update(changes)
    return value


def _one_reason(output, **response_changes):
    result = extract_grounded_candidates(_request(), _response(output, **response_changes))
    assert len(result.rejected_claims) == 1
    return result.rejected_claims[0].reason_code


def test_fixture_successful_extraction_is_immutable_and_provenanced():
    result = extract_grounded_candidates(_request(), _response(_SUCCESS))
    assert result.status.value == "success" and len(result.accepted_candidates) == 1
    candidate = result.accepted_candidates[0]
    assert candidate.quoted_span == "B2M loss was observed"
    assert candidate.provider_name == "mock" and candidate.requested_model == "requested"
    assert isinstance(candidate.raw_fields, MappingProxyType)
    assert dict(candidate.raw_fields) == {}
    with pytest.raises(TypeError):
        candidate.raw_fields["target_mentions"] = ()
    with pytest.raises(AttributeError):
        candidate.claim_text = "changed"


def test_optional_fields_are_deeply_immutable_and_serialized_deterministically():
    claim = _claim(
        target_mentions=["B2M"], disease_mentions=["melanoma"],
        cohort_description="one cohort", limitations="observational",
    )
    first = extract_grounded_candidates(_request(), _response(_output([claim])))
    second = extract_grounded_candidates(_request(), _response(_output([claim])))
    candidate = first.accepted_candidates[0]
    assert candidate.raw_fields["target_mentions"] == ("B2M",)
    assert candidate.canonical_json() == second.accepted_candidates[0].canonical_json()
    assert candidate.candidate_id == second.accepted_candidates[0].candidate_id


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"quoted_span": "b2m loss was observed"}, "quote_mismatch"),
        ({"quoted_span": "B2M  loss was observed"}, "quote_mismatch"),
        ({"quoted_span": "B2M loss was observed."}, "quote_mismatch"),
        ({"quoted_span": ""}, "empty_quote"),
        ({"claim_text": "   "}, "empty_claim_text"),
        ({"quote_start": "0"}, "invalid_offset_type"),
        ({"quote_start": -1}, "invalid_offset_range"),
        ({"quote_start": 15, "quote_end": 14}, "invalid_offset_range"),
        ({"quote_end": len(_SOURCE) + 1}, "invalid_offset_range"),
    ],
)
def test_exact_quote_grounding_rejects_all_reviewed_edge_cases(changes, reason):
    assert _one_reason(_output([_claim(**changes)])) == reason


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ("not-an-array", "claims_not_array"),
        (["not-an-object"], "claim_not_object"),
        ([_claim(extra="x")], "unknown_claim_field"),
        ([_claim(thinking="private")], "hidden_reasoning_field"),
        ([_claim(reasoning="private")], "hidden_reasoning_field"),
        ([_claim(stance="maybe")], "invalid_stance"),
        ([_claim(target_mentions=["B2M", 2])], "malformed_optional_field"),
    ],
)
def test_claim_shape_and_safety_rejections_are_auditable(claims, reason):
    result = extract_grounded_candidates(_request(), _response(_output(claims)))
    assert [item.reason_code for item in result.rejected_claims] == [reason]
    assert "private" not in result.canonical_json()


def test_top_level_source_and_schema_failures_are_rejected_with_fixtures():
    assert _one_reason(_FAILURES) == "source_document_mismatch"
    missing_source = _output([])
    del missing_source["source_document_id"]
    assert _one_reason(missing_source) == "invalid_top_level_shape"
    assert _one_reason(_output([]), schema_id="other") == "schema_mismatch"
    assert _one_reason(_output([]), source_document_id="wrong") == "source_document_mismatch"
    assert _one_reason(_output([]), source_document_id="doc-1", request_id="other") == "source_document_mismatch"
    assert _one_reason(["not-an-object"]) == "invalid_top_level_shape"


def test_missing_structured_output_and_all_non_success_statuses_fail_closed():
    missing = extract_grounded_candidates(
        _request(), _response(None, raw_text="not structured"),
    )
    assert missing.status.value == "failed"
    assert missing.rejected_claims[0].reason_code == "structured_output_missing"
    for status in (
        LLMResultStatus.MALFORMED_OUTPUT,
        LLMResultStatus.RETRYABLE_FAILURE,
        LLMResultStatus.PERMANENT_FAILURE,
        LLMResultStatus.TIMEOUT,
        LLMResultStatus.NOT_EXECUTED,
    ):
        result = extract_grounded_candidates(_request(), _response(None, status))
        assert result.status.value == "failed"
        assert not result.accepted_candidates
        assert result.rejected_claims[0].reason_code == "response_not_successful"


def test_empty_duplicate_and_operational_identity_boundaries():
    empty = extract_grounded_candidates(_request(), _response(_output([])))
    assert empty.no_claims and not empty.accepted_candidates and not empty.rejected_claims
    first = extract_grounded_candidates(_request(), _response(_output([_claim(), _claim()])))
    assert len(first.accepted_candidates) == 1
    assert [item.reason_code for item in first.rejected_claims] == ["duplicate_candidate"]
    one = extract_grounded_candidates(
        _request(), _response(_output([_claim()]), latency=1, responded_at=datetime(2024, 1, 1, tzinfo=timezone.utc)),
    )
    two = extract_grounded_candidates(
        _request(), _response(_output([_claim()]), latency=99, responded_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
    )
    assert one.accepted_candidates[0].candidate_id == two.accepted_candidates[0].candidate_id
    assert one.result_id == two.result_id


def test_parser_does_not_mutate_request_or_response_and_rejections_are_sanitized():
    request = _request()
    response = _response(_output([_claim(reasoning="hidden document content")]))
    request_before, response_before = request.canonical_json(), response.canonical_json()
    result = extract_grounded_candidates(request, response)
    assert request.canonical_json() == request_before
    assert response.canonical_json() == response_before
    rejection = result.rejected_claims[0]
    assert rejection.index == 0 and rejection.fields == {"field": "reasoning"}
    assert _SOURCE not in result.canonical_json()
    assert "hidden document content" not in result.canonical_json()
