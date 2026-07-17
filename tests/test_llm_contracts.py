from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from targetintel.llm import LLMProvider, LLMRequest, LLMResponse, LLMResultStatus, ProviderCapabilities, ProviderErrorCategory, ProviderProvenance


def request(**changes):
    values = dict(request_id="request-1", task_type="grounded_extraction", source_document_id="document-1", prompt_id="extract", prompt_version="1", system_instruction="Return fixture output.", user_instruction="Inspect supplied content.", response_schema_id="candidate", response_schema_version="1", source_text="source", model_configuration={"temperature": 0}, metadata={"trace": ["fixture"]})
    values.update(changes)
    return LLMRequest(**values)


def test_request_is_deeply_immutable_and_deterministic():
    mutable = {"nested": ["value"]}
    value = request(model_configuration=mutable)
    mutable["nested"].append("changed")
    assert value.model_configuration["nested"] == ("value",)
    with pytest.raises(TypeError):
        value.model_configuration["x"] = 1
    assert value.payload_identity() == LLMRequest.from_dict(value.to_dict()).payload_identity()


@pytest.mark.parametrize("field", ["request_id", "task_type", "source_document_id", "prompt_id", "prompt_version", "system_instruction", "user_instruction", "response_schema_id", "response_schema_version"])
def test_empty_required_request_fields_fail(field):
    with pytest.raises(ValueError, match=field):
        request(**{field: " "})


def test_request_requires_source_and_rejects_credentials():
    with pytest.raises(ValueError, match="source_text"):
        request(source_text=None)
    with pytest.raises(ValueError, match="secrets"):
        request(model_configuration={"api_key": "do-not-store"})
    with pytest.raises(ValueError, match="secrets"):
        request(source_text=None, structured_source_content={"nested": {"api_key": "do-not-store"}})
    with pytest.raises(ValueError, match="secrets"):
        request(metadata={"trace": [{"api_key": "do-not-store"}]})


def test_capabilities_are_immutable_and_unknown_is_representable():
    caps = ProviderCapabilities()
    assert caps.structured_output is None
    with pytest.raises(FrozenInstanceError):
        caps.local_execution = True


def test_response_identity_excludes_operational_time_and_round_trips():
    provenance = ProviderProvenance("request-1", "mock", "model", "v1", "extract", "1", "candidate", "1", "task", "document", LLMResultStatus.SUCCESS)
    first = LLMResponse(provenance, raw_text="ok", responded_at=datetime(2024, 1, 1, tzinfo=timezone.utc), latency_ms=1)
    second = LLMResponse(provenance, raw_text="ok", responded_at=datetime(2025, 1, 1, tzinfo=timezone.utc), latency_ms=99)
    assert first.payload_identity() == second.payload_identity()
    assert LLMResponse.from_dict(first.to_dict()).to_dict() == first.to_dict()
    with pytest.raises(FrozenInstanceError):
        first.raw_text = "no"


def test_response_requires_visible_failure_and_sanitizes_secret():
    provenance = ProviderProvenance("request-1", "mock", "model", None, "extract", "1", "candidate", "1", "task", "document", LLMResultStatus.TIMEOUT, ProviderErrorCategory.TIMEOUT)
    response = LLMResponse(provenance, error_message="Authorization: Bearer private-token")
    assert "private-token" not in response.error_message
    assert response.retryable
    with pytest.raises(ValueError, match="require an error category"):
        LLMResponse(ProviderProvenance("r", "p", "m", None, "p", "1", "s", "1", "t", "d", LLMResultStatus.PERMANENT_FAILURE))


def test_protocol_is_runtime_checkable():
    assert not isinstance(object(), LLMProvider)
