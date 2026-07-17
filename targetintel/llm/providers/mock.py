"""Deterministic, offline provider simulator for tests and development."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ..contracts import LLMProvider, LLMRequest, LLMResponse, LLMResultStatus, ProviderCapabilities, ProviderProvenance, _freeze
from ..errors import ProviderErrorCategory


Clock = Callable[[], datetime]


def _clock_time(clock: Clock | None) -> datetime | None:
    if clock is None:
        return None
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MockOutcome:
    status: LLMResultStatus
    raw_text: str | None = None
    structured_output: Mapping[str, Any] | None = None
    finish_reason: str | None = None
    token_usage: Mapping[str, int] | None = None
    latency_ms: int | float | None = None
    error_category: ProviderErrorCategory | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.structured_output is not None:
            object.__setattr__(self, "structured_output", _freeze(self.structured_output))
        if self.token_usage is not None:
            object.__setattr__(self, "token_usage", _freeze(self.token_usage))
        if self.status is LLMResultStatus.SUCCESS and self.error_category is not None:
            raise ValueError("successful mock outcomes cannot have an error category")
        if self.status is not LLMResultStatus.SUCCESS and self.error_category is None:
            raise ValueError("unsuccessful mock outcomes require an error category")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MockOutcome":
        values = dict(data)
        values["status"] = LLMResultStatus(values["status"])
        if values.get("error_category") is not None:
            values["error_category"] = ProviderErrorCategory(values["error_category"])
        return cls(**values)


@dataclass(frozen=True)
class MockCall:
    request: LLMRequest
    response: LLMResponse


class MockProvider:
    """Fixture-driven provider with no I/O, inference, secrets, or SDK dependency."""

    def __init__(
        self,
        script: Mapping[str, MockOutcome | Mapping[str, Any]],
        *,
        provider_name: str = "mock",
        model_name: str = "mock-model",
        model_version: str | None = "mock-v1",
        capabilities: ProviderCapabilities | None = None,
        clock: Clock | None = None,
    ) -> None:
        if not isinstance(script, Mapping):
            raise ValueError("script must map request IDs to outcomes")
        if not provider_name.strip() or not model_name.strip():
            raise ValueError("provider_name and model_name must be non-empty strings")
        self._script = MappingProxyType({str(key): value if isinstance(value, MockOutcome) else MockOutcome.from_dict(value) for key, value in script.items()})
        self._provider_name, self._model_name, self._model_version = provider_name, model_name, model_version
        self._capabilities = capabilities or ProviderCapabilities(structured_output=True, json_schema=True, deterministic_seed=True, system_instruction=True, token_usage=True, model_version=True, local_execution=True)
        self._clock = clock
        self._history: list[MockCall] = []

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    @property
    def call_history(self) -> tuple[MockCall, ...]:
        return tuple(self._history)

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not isinstance(request, LLMRequest):
            raise TypeError("request must be an LLMRequest")
        outcome = self._script.get(request.request_id)
        if outcome is None:
            outcome = MockOutcome(LLMResultStatus.NOT_EXECUTED, error_category=ProviderErrorCategory.NOT_EXECUTED, error_message="No scripted outcome for request")
        provenance = ProviderProvenance(request.request_id, self._provider_name, self._model_name, self._model_version, request.prompt_id, request.prompt_version, request.response_schema_id, request.response_schema_version, request.task_type, request.source_document_id, outcome.status, outcome.error_category)
        response = LLMResponse(provenance, outcome.raw_text, outcome.structured_output, outcome.finish_reason, outcome.token_usage, outcome.latency_ms, _clock_time(self._clock), outcome.error_message)
        self._history.append(MockCall(request, response))
        return response


assert isinstance(MockProvider({}), LLMProvider)
