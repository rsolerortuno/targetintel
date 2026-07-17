import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from targetintel.llm import LLMProvider, LLMRequest, LLMResultStatus
from targetintel.llm.providers import MockProvider


FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def request(identifier):
    return LLMRequest(identifier, "grounded_extraction", "document-1", "extract", "1", "system", "user", "candidate", "1", source_text="fixed source")


def script():
    return json.loads((FIXTURES / "mock_provider_success.json").read_text()) | json.loads((FIXTURES / "mock_provider_failures.json").read_text())


def test_mock_provider_implements_protocol_and_success_is_fixture_controlled():
    provider = MockProvider(script())
    assert isinstance(provider, LLMProvider)
    response = provider.generate(request("request-success"))
    assert response.status is LLMResultStatus.SUCCESS
    assert response.structured_output["fixture"] == "success"
    assert response.provenance.source_document_id == "document-1"
    assert response.provenance.prompt_id == "extract"


@pytest.mark.parametrize("identifier,status", [("request-malformed", LLMResultStatus.MALFORMED_OUTPUT), ("request-retry", LLMResultStatus.RETRYABLE_FAILURE), ("request-permanent", LLMResultStatus.PERMANENT_FAILURE), ("request-timeout", LLMResultStatus.TIMEOUT), ("request-not-executed", LLMResultStatus.NOT_EXECUTED), ("missing", LLMResultStatus.NOT_EXECUTED)])
def test_scripted_failure_statuses(identifier, status):
    response = MockProvider(script()).generate(request(identifier))
    assert response.status is status
    assert response.error_category is not None
    assert response.retryable is (status in {LLMResultStatus.RETRYABLE_FAILURE, LLMResultStatus.TIMEOUT})


def test_history_and_clock_are_deterministic_and_immutable():
    provider = MockProvider(script(), clock=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
    one = provider.generate(request("request-success"))
    two = provider.generate(request("request-success"))
    assert one.payload_identity() == two.payload_identity()
    assert one.responded_at == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert len(provider.call_history) == 2
    with pytest.raises(ValueError, match="timezone-aware"):
        MockProvider(script(), clock=lambda: datetime(2024, 1, 1)).generate(request("request-success"))
