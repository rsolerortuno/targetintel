"""Immutable, provider-neutral contracts for model-generation operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from .errors import ProviderErrorCategory, is_retryable_error, sanitize_error_message


CONTRACT_VERSION = "llm-provider-contract-v1"


class LLMResultStatus(str, Enum):
    SUCCESS = "success"
    MALFORMED_OUTPUT = "malformed_output"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    TIMEOUT = "timeout"
    NOT_EXECUTED = "not_executed"


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool, type(None))):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("NaN and infinity are not permitted")
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
    raise ValueError(f"unsupported contract value type: {type(value).__name__}")


def _reject_secret_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(term in normalized for term in ("api_key", "apikey", "authorization", "password", "secret", "access_token")):
                raise ValueError("secrets and credentials are not permitted in provider contracts")
            _reject_secret_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_keys(item)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value


def canonical_json(value: Any) -> str:
    """Serialize public contract data with stable ordering and finite numbers."""
    return json.dumps(_thaw(_freeze(value)), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProviderCapabilities:
    structured_output: bool | None = None
    json_schema: bool | None = None
    deterministic_seed: bool | None = None
    system_instruction: bool | None = None
    token_usage: bool | None = None
    model_version: bool | None = None
    local_execution: bool | None = None
    maximum_context_tokens: int | None = None
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _required(self.contract_version, "contract_version")
        if self.maximum_context_tokens is not None and (not isinstance(self.maximum_context_tokens, int) or self.maximum_context_tokens <= 0):
            raise ValueError("maximum_context_tokens must be a positive integer or null")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderCapabilities":
        return cls(**dict(data))


@dataclass(frozen=True)
class LLMRequest:
    request_id: str
    task_type: str
    source_document_id: str
    prompt_id: str
    prompt_version: str
    system_instruction: str
    user_instruction: str
    response_schema_id: str
    response_schema_version: str
    model_configuration: Mapping[str, Any] = field(default_factory=dict)
    source_text: str | None = None
    structured_source_content: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name in ("request_id", "task_type", "source_document_id", "prompt_id", "prompt_version", "system_instruction", "user_instruction", "response_schema_id", "response_schema_version", "contract_version"):
            _required(getattr(self, name), name)
        if self.source_text is None and self.structured_source_content is None:
            raise ValueError("source_text or structured_source_content is required")
        if self.source_text is not None and (not isinstance(self.source_text, str) or not self.source_text.strip()):
            raise ValueError("source_text must be a non-empty string or null")
        if self.structured_source_content is not None and not isinstance(self.structured_source_content, Mapping):
            raise ValueError("structured_source_content must be a mapping or null")
        if not isinstance(self.model_configuration, Mapping) or not isinstance(self.metadata, Mapping):
            raise ValueError("model_configuration and metadata must be mappings")
        _reject_secret_keys(self.model_configuration)
        if self.structured_source_content is not None:
            _reject_secret_keys(self.structured_source_content)
        _reject_secret_keys(self.metadata)
        object.__setattr__(self, "model_configuration", _freeze(self.model_configuration))
        object.__setattr__(self, "structured_source_content", None if self.structured_source_content is None else _freeze(self.structured_source_content))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {name: _thaw(getattr(self, name)) for name in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LLMRequest":
        return cls(**dict(data))

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def payload_identity(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderProvenance:
    request_id: str
    provider_name: str
    model_name: str
    model_version: str | None
    prompt_id: str
    prompt_version: str
    response_schema_id: str
    response_schema_version: str
    task_type: str
    source_document_id: str
    result_status: LLMResultStatus
    error_category: ProviderErrorCategory | None = None
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name in ("request_id", "provider_name", "model_name", "prompt_id", "prompt_version", "response_schema_id", "response_schema_version", "task_type", "source_document_id", "contract_version"):
            _required(getattr(self, name), name)
        if self.model_version is not None:
            _required(self.model_version, "model_version")

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["result_status"] = self.result_status.value
        result["error_category"] = None if self.error_category is None else self.error_category.value
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderProvenance":
        values = dict(data)
        values["result_status"] = LLMResultStatus(values["result_status"])
        if values.get("error_category") is not None:
            values["error_category"] = ProviderErrorCategory(values["error_category"])
        return cls(**values)


@dataclass(frozen=True)
class LLMResponse:
    provenance: ProviderProvenance
    raw_text: str | None = None
    structured_output: Mapping[str, Any] | None = None
    finish_reason: str | None = None
    token_usage: Mapping[str, int] | None = None
    latency_ms: int | float | None = None
    responded_at: datetime | None = None
    error_message: str | None = None
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        _required(self.contract_version, "contract_version")
        if not isinstance(self.provenance, ProviderProvenance):
            raise ValueError("provenance must be ProviderProvenance")
        if self.structured_output is not None:
            object.__setattr__(self, "structured_output", _freeze(self.structured_output))
        if self.token_usage is not None:
            frozen_usage = _freeze(self.token_usage)
            if not all(isinstance(value, int) and value >= 0 for value in frozen_usage.values()):
                raise ValueError("token_usage values must be non-negative integers")
            object.__setattr__(self, "token_usage", frozen_usage)
        if self.latency_ms is not None and (not isinstance(self.latency_ms, (int, float)) or not math.isfinite(self.latency_ms) or self.latency_ms < 0):
            raise ValueError("latency_ms must be a finite non-negative number or null")
        if self.responded_at is not None:
            object.__setattr__(self, "responded_at", _freeze(self.responded_at))
        object.__setattr__(self, "error_message", sanitize_error_message(self.error_message))
        status = self.provenance.result_status
        if status is LLMResultStatus.SUCCESS and self.provenance.error_category is not None:
            raise ValueError("successful responses cannot have an error category")
        if status is not LLMResultStatus.SUCCESS and self.provenance.error_category is None:
            raise ValueError("unsuccessful responses require an error category")
        if status is LLMResultStatus.SUCCESS and self.raw_text is None and self.structured_output is None:
            raise ValueError("successful responses require raw_text or structured_output")
        expected_categories = {
            LLMResultStatus.MALFORMED_OUTPUT: {ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE},
            LLMResultStatus.TIMEOUT: {ProviderErrorCategory.TIMEOUT},
            LLMResultStatus.NOT_EXECUTED: {ProviderErrorCategory.NOT_EXECUTED},
        }
        if status in expected_categories and self.error_category not in expected_categories[status]:
            raise ValueError("response status and error category are inconsistent")
        if status is LLMResultStatus.RETRYABLE_FAILURE and not is_retryable_error(self.error_category):
            raise ValueError("retryable failures require a retryable error category")
        if status is LLMResultStatus.PERMANENT_FAILURE and is_retryable_error(self.error_category):
            raise ValueError("permanent failures cannot have a retryable error category")

    @property
    def status(self) -> LLMResultStatus:
        return self.provenance.result_status

    @property
    def error_category(self) -> ProviderErrorCategory | None:
        return self.provenance.error_category

    @property
    def request_id(self) -> str:
        return self.provenance.request_id

    @property
    def provider_name(self) -> str:
        return self.provenance.provider_name

    @property
    def model_name(self) -> str:
        return self.provenance.model_name

    @property
    def model_version(self) -> str | None:
        return self.provenance.model_version

    @property
    def prompt_id(self) -> str:
        return self.provenance.prompt_id

    @property
    def prompt_version(self) -> str:
        return self.provenance.prompt_version

    @property
    def response_schema_id(self) -> str:
        return self.provenance.response_schema_id

    @property
    def response_schema_version(self) -> str:
        return self.provenance.response_schema_version

    @property
    def task_type(self) -> str:
        return self.provenance.task_type

    @property
    def source_document_id(self) -> str:
        return self.provenance.source_document_id

    @property
    def retryable(self) -> bool:
        return is_retryable_error(self.error_category)

    def to_dict(self, *, include_operational: bool = True) -> dict[str, Any]:
        result = {
            "contract_version": self.contract_version,
            "provenance": self.provenance.to_dict(),
            "raw_text": self.raw_text,
            "structured_output": _thaw(self.structured_output),
            "finish_reason": self.finish_reason,
            "token_usage": _thaw(self.token_usage),
            "error_message": self.error_message,
        }
        if include_operational:
            result["latency_ms"] = self.latency_ms
            result["responded_at"] = None if self.responded_at is None else _thaw(self.responded_at)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LLMResponse":
        values = dict(data)
        values["provenance"] = ProviderProvenance.from_dict(values.pop("provenance"))
        if values.get("responded_at") is not None:
            values["responded_at"] = _parse_timestamp(values["responded_at"], "responded_at")
        return cls(**values)

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict(include_operational=False))

    def payload_identity(self) -> str:
        return sha256(self.canonical_json().encode("utf-8")).hexdigest()


@runtime_checkable
class LLMProvider(Protocol):
    """Synchronous, side-effect-unconstrained only by implementations contract."""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def generate(self, request: LLMRequest) -> LLMResponse: ...
