import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path

import pytest

from targetintel.llm import LLMProvider, LLMRequest, LLMResultStatus, ProviderErrorCategory
from targetintel.llm.providers import HTTPResponse, OllamaConfig, OllamaProvider


FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def request(**changes):
    values = dict(request_id="request-1", task_type="grounded_extraction", source_document_id="document-1", prompt_id="extract", prompt_version="1", system_instruction="System instruction.", user_instruction="User instruction.", response_schema_id="candidate", response_schema_version="1", source_text="Exact supplied source\ntext.")
    values.update(changes)
    return LLMRequest(**values)


class FakeTransport:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def send(self, method, url, body, headers, timeout):
        self.calls.append((method, url, body, dict(headers), timeout))
        if self.error:
            raise self.error
        return self.result


def document(name):
    return json.loads((FIXTURES / name).read_text())


def response(payload):
    return HTTPResponse(200, {}, json.dumps(payload).encode())


def provider(transport, **kwargs):
    return OllamaProvider(OllamaConfig("configured-model", **kwargs), transport=transport)


def test_protocol_configuration_and_default_local_url_are_immutable():
    config = OllamaConfig(" model ")
    assert config.model_name == "model"
    assert config.base_url == "http://127.0.0.1:11434"
    assert "key" not in json.dumps(config.to_dict()).lower()
    with pytest.raises(FrozenInstanceError):
        config.timeout = 1
    assert isinstance(provider(FakeTransport(response(document("ollama_chat_success.json")))), LLMProvider)


@pytest.mark.parametrize("model, timeout, message", [(" ", 1, "model_name"), ("model", 0, "timeout"), ("model", float("inf"), "timeout")])
def test_invalid_config_rejected(model, timeout, message):
    with pytest.raises(ValueError, match=message):
        OllamaConfig(model, timeout=timeout)


@pytest.mark.parametrize("url", ["http://user:pass@localhost:11434", "http://localhost:11434/?x=1", "http://localhost:11434/#x"])
def test_credential_and_noncanonical_url_parts_rejected(url):
    with pytest.raises(ValueError, match="credentials, query strings, or fragments"):
        OllamaConfig("model", base_url=url)


def test_deterministic_payload_message_order_and_exact_source_preservation():
    transport = FakeTransport(response(document("ollama_chat_success.json")))
    client = provider(transport, base_url="http://localhost:11434/")
    assert client.generate(request()).status is LLMResultStatus.SUCCESS
    _, url, body, headers, timeout = transport.calls[0]
    payload = json.loads(body)
    assert url == "http://localhost:11434/api/chat"
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "System instruction."}
    assert payload["messages"][1]["content"].index("User instruction.") < payload["messages"][1]["content"].index("Exact supplied source\ntext.")
    assert "Exact supplied source\ntext." in payload["messages"][1]["content"]
    assert headers == {"Content-Type": "application/json", "Accept": "application/json"}
    assert timeout == 30.0
    again = FakeTransport(response(document("ollama_chat_success.json")))
    provider(again, base_url="http://localhost:11434/").generate(request())
    assert body == again.calls[0][2]


def test_structured_source_schema_and_structured_response_are_deterministic():
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    transport = FakeTransport(response(document("ollama_chat_structured_success.json")))
    client = OllamaProvider(OllamaConfig("configured-model"), transport=transport, schema_resolver={("candidate", "1"): schema})
    result = client.generate(request(source_text=None, structured_source_content={"z": 1, "a": ["x"]}))
    sent = json.loads(transport.calls[0][2])
    assert '{"a":["x"],"z":1}' in sent["messages"][1]["content"]
    assert sent["format"] == schema
    assert result.status is LLMResultStatus.SUCCESS
    assert result.raw_text == '{"answer":"offline"}'
    assert dict(result.structured_output) == {"answer": "offline"}


def test_missing_schema_and_unsupported_option_fail_before_transport():
    transport = FakeTransport(response(document("ollama_chat_success.json")))
    no_schema = OllamaProvider(OllamaConfig("configured-model"), transport=transport, schema_resolver={})
    result = no_schema.generate(request())
    assert result.error_category is ProviderErrorCategory.INVALID_REQUEST
    assert not transport.calls
    result = provider(transport).generate(request(model_configuration={"unknown": 1}))
    assert result.error_category is ProviderErrorCategory.INVALID_REQUEST
    assert not transport.calls
    with pytest.raises(ValueError, match="unsupported generation option"):
        OllamaConfig("configured-model", generation_options={"unknown": 1})


def test_success_normalization_retains_model_mismatch_usage_duration_and_hides_thinking():
    result = provider(FakeTransport(response(document("ollama_chat_success.json")))).generate(request())
    assert result.status is LLMResultStatus.SUCCESS
    assert result.model_name == "llama3.2:latest"
    assert result.provenance.requested_model_name == "configured-model"
    assert dict(result.token_usage) == {"prompt_tokens": 11, "generated_tokens": 7}
    assert result.latency_ms == 2.5
    assert result.responded_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert "hidden" not in json.dumps(result.to_dict())
    changed_time = result.__class__(result.provenance, raw_text=result.raw_text, token_usage=result.token_usage, finish_reason=result.finish_reason, latency_ms=99, responded_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result.payload_identity() == changed_time.payload_identity()


@pytest.mark.parametrize("payload, expected", [
    (b"not json", LLMResultStatus.MALFORMED_OUTPUT),
    (b"", LLMResultStatus.MALFORMED_OUTPUT),
    (document("ollama_chat_errors.json")["missing_message"], LLMResultStatus.MALFORMED_OUTPUT),
    (document("ollama_chat_errors.json")["missing_content"], LLMResultStatus.MALFORMED_OUTPUT),
    (document("ollama_chat_errors.json")["incomplete"], LLMResultStatus.MALFORMED_OUTPUT),
    (document("ollama_chat_errors.json")["provider_error"], LLMResultStatus.PERMANENT_FAILURE),
])
def test_malformed_and_provider_error_responses(payload, expected):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    result = provider(FakeTransport(HTTPResponse(200, {}, body))).generate(request())
    assert result.status is expected
    assert result.error_category is ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE if expected is LLMResultStatus.MALFORMED_OUTPUT else ProviderErrorCategory.PERMANENT_PROVIDER_FAILURE


def test_malformed_structured_json_is_auditable():
    transport = FakeTransport(response({"model": "model", "message": {"role": "assistant", "content": "not-json"}, "done": True}))
    result = OllamaProvider(OllamaConfig("configured-model"), transport=transport, schema_resolver={("candidate", "1"): {"type": "object"}}).generate(request())
    assert result.status is LLMResultStatus.MALFORMED_OUTPUT
    assert result.raw_text == "not-json"


@pytest.mark.parametrize("code, category, status", [(400, ProviderErrorCategory.INVALID_REQUEST, LLMResultStatus.PERMANENT_FAILURE), (404, ProviderErrorCategory.NOT_CONFIGURED, LLMResultStatus.PERMANENT_FAILURE), (429, ProviderErrorCategory.RATE_LIMIT, LLMResultStatus.RETRYABLE_FAILURE), (500, ProviderErrorCategory.RETRYABLE_PROVIDER_FAILURE, LLMResultStatus.RETRYABLE_FAILURE)])
def test_http_error_mapping(code, category, status):
    result = provider(FakeTransport(HTTPResponse(code, {"Authorization": "Bearer private"}, b'{"error":"private"}'))).generate(request())
    assert (result.status, result.error_category) == (status, category)
    assert "private" not in result.error_message


@pytest.mark.parametrize("error, status, category", [(TimeoutError(), LLMResultStatus.TIMEOUT, ProviderErrorCategory.TIMEOUT), (ConnectionError("Authorization: Bearer private"), LLMResultStatus.RETRYABLE_FAILURE, ProviderErrorCategory.CONNECTION_FAILURE)])
def test_transport_failures_are_sanitized(error, status, category):
    result = provider(FakeTransport(error=error)).generate(request())
    assert (result.status, result.error_category) == (status, category)
    assert "private" not in (result.error_message or "")
