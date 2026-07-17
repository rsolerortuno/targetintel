"""Offline-testable adapter for Ollama's non-streaming ``/api/chat`` API.

This module deliberately uses only the standard library.  The transport is a
small injected boundary so exercising the provider never requires Ollama or a
network connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ..contracts import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResultStatus,
    ProviderCapabilities,
    ProviderProvenance,
    canonical_json,
    _freeze,
)
from ..errors import ProviderErrorCategory


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
_ALLOWED_OPTIONS = frozenset({"temperature", "seed", "top_p", "num_predict"})
_SAFE_HEADERS = MappingProxyType({"Content-Type": "application/json", "Accept": "application/json"})


@dataclass(frozen=True)
class HTTPResponse:
    """The complete, typed result returned by an :class:`HTTPTransport`."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.status_code, int) or not 100 <= self.status_code <= 599:
            raise ValueError("status_code must be an HTTP status code")
        if not isinstance(self.headers, Mapping):
            raise ValueError("headers must be a mapping")
        if not isinstance(self.body, bytes):
            raise ValueError("body must be bytes")
        object.__setattr__(self, "headers", _freeze(self.headers))


@runtime_checkable
class HTTPTransport(Protocol):
    def send(self, method: str, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> HTTPResponse: ...


class UrllibTransport:
    """Optional standard-library transport for an explicitly local Ollama."""

    def send(self, method: str, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated by configuration.
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as exc:
            return HTTPResponse(exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read())


SchemaResolver = Callable[[str, str], Mapping[str, Any] | None]
Clock = Callable[[], datetime]


def _validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty URL")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain credentials, query strings, or fragments")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _validate_options(options: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(options, Mapping):
        raise ValueError("generation_options must be a mapping")
    unknown = set(options).difference(_ALLOWED_OPTIONS)
    if unknown:
        raise ValueError("unsupported generation option: " + sorted(str(key) for key in unknown)[0])
    for key, value in options.items():
        if key == "seed" or key == "num_predict":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"generation option {key} must be an integer")
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"generation option {key} must be a finite number")
    return _freeze(options)


@dataclass(frozen=True)
class OllamaConfig:
    model_name: str
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    timeout: float = 30.0
    keep_alive: str | int | None = None
    generation_options: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            raise ValueError("model_name must be a non-empty string")
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool) or not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        if self.keep_alive is not None and (not isinstance(self.keep_alive, (str, int)) or isinstance(self.keep_alive, bool)):
            raise ValueError("keep_alive must be a string, integer, or null")
        object.__setattr__(self, "model_name", self.model_name.strip())
        object.__setattr__(self, "base_url", _validate_base_url(self.base_url))
        object.__setattr__(self, "timeout", float(self.timeout))
        object.__setattr__(self, "generation_options", _validate_options(self.generation_options or {}))

    def to_dict(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "base_url": self.base_url, "timeout": self.timeout, "keep_alive": self.keep_alive, "generation_options": dict(self.generation_options or {})}


def _parse_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


class OllamaProvider:
    """Provider-neutral adapter which maps one request to Ollama ``/api/chat``."""

    def __init__(self, config: OllamaConfig, *, transport: HTTPTransport | None = None, schema_resolver: SchemaResolver | Mapping[tuple[str, str], Mapping[str, Any]] | None = None, clock: Clock | None = None) -> None:
        if not isinstance(config, OllamaConfig):
            raise ValueError("config must be an OllamaConfig")
        self._config = config
        self._transport = transport or UrllibTransport()
        if not isinstance(self._transport, HTTPTransport):
            raise ValueError("transport must implement HTTPTransport")
        if schema_resolver is not None and not callable(schema_resolver) and not isinstance(schema_resolver, Mapping):
            raise ValueError("schema_resolver must be callable, mapping, or null")
        self._schema_resolver = schema_resolver
        self._clock = clock
        self._capabilities = ProviderCapabilities(structured_output=True, json_schema=True, deterministic_seed=True, system_instruction=True, token_usage=True, model_version=None, local_execution=True)

    @property
    def config(self) -> OllamaConfig:
        return self._config

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _response(self, request: LLMRequest, status: LLMResultStatus, category: ProviderErrorCategory | None = None, *, model_name: str | None = None, model_version: str | None = None, raw_text: str | None = None, structured_output: Mapping[str, Any] | None = None, finish_reason: str | None = None, token_usage: Mapping[str, int] | None = None, latency_ms: float | None = None, responded_at: datetime | None = None, error_message: str | None = None) -> LLMResponse:
        provenance = ProviderProvenance(request.request_id, "ollama", model_name or self._config.model_name, model_version, request.prompt_id, request.prompt_version, request.response_schema_id, request.response_schema_version, request.task_type, request.source_document_id, status, category, requested_model_name=self._config.model_name)
        return LLMResponse(provenance, raw_text, structured_output, finish_reason, token_usage, latency_ms, responded_at, error_message)

    def _resolve_schema(self, request: LLMRequest) -> Mapping[str, Any] | None:
        resolver = self._schema_resolver
        if resolver is None:
            return None
        result = resolver(request.response_schema_id, request.response_schema_version) if callable(resolver) else resolver.get((request.response_schema_id, request.response_schema_version))
        if result is None:
            raise ValueError("requested response schema is not configured")
        if not isinstance(result, Mapping):
            raise ValueError("resolved response schema must be a mapping")
        return _freeze(result)

    def _payload(self, request: LLMRequest, schema: Mapping[str, Any] | None) -> bytes:
        unsupported = set(request.model_configuration).difference(_ALLOWED_OPTIONS)
        if unsupported:
            raise ValueError("unsupported model configuration key: " + sorted(str(key) for key in unsupported)[0])
        options = dict(self._config.generation_options or {})
        options.update(dict(request.model_configuration))
        _validate_options(options)
        source = request.source_text if request.source_text is not None else canonical_json(request.structured_source_content)
        user_content = f"{request.user_instruction}\n\n<source_document id={json.dumps(request.source_document_id, ensure_ascii=False)}>\n{source}\n</source_document>"
        payload: dict[str, Any] = {"model": self._config.model_name, "stream": False, "messages": [{"role": "system", "content": request.system_instruction}, {"role": "user", "content": user_content}], "options": options}
        if schema is not None:
            payload["format"] = schema
        if self._config.keep_alive is not None:
            payload["keep_alive"] = self._config.keep_alive
        return canonical_json(payload).encode("utf-8")

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not isinstance(request, LLMRequest):
            raise TypeError("request must be an LLMRequest")
        try:
            schema = self._resolve_schema(request)
            body = self._payload(request, schema)
        except ValueError as exc:
            return self._response(request, LLMResultStatus.PERMANENT_FAILURE, ProviderErrorCategory.INVALID_REQUEST, error_message=str(exc))
        try:
            result = self._transport.send("POST", self._config.base_url + "/api/chat", body, _SAFE_HEADERS, self._config.timeout)
        except TimeoutError:
            return self._response(request, LLMResultStatus.TIMEOUT, ProviderErrorCategory.TIMEOUT, error_message="Ollama request timed out")
        except (URLError, ConnectionError, OSError):
            return self._response(request, LLMResultStatus.RETRYABLE_FAILURE, ProviderErrorCategory.CONNECTION_FAILURE, error_message="Could not connect to Ollama")
        except Exception:
            return self._response(request, LLMResultStatus.PERMANENT_FAILURE, ProviderErrorCategory.PERMANENT_PROVIDER_FAILURE, error_message="Ollama transport failed")
        if not isinstance(result, HTTPResponse):
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama transport returned an invalid response")
        if result.status_code != 200:
            category, status, message = self._http_failure(result.status_code)
            return self._response(request, status, category, error_message=message)
        if not result.body:
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama returned an empty response")
        try:
            document = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama returned malformed JSON")
        return self._normalize(request, document, schema is not None)

    @staticmethod
    def _http_failure(status_code: int) -> tuple[ProviderErrorCategory, LLMResultStatus, str]:
        if status_code == 400:
            return ProviderErrorCategory.INVALID_REQUEST, LLMResultStatus.PERMANENT_FAILURE, "Ollama rejected the request"
        if status_code == 404:
            return ProviderErrorCategory.NOT_CONFIGURED, LLMResultStatus.PERMANENT_FAILURE, "Configured Ollama model was not found"
        if status_code == 429:
            return ProviderErrorCategory.RATE_LIMIT, LLMResultStatus.RETRYABLE_FAILURE, "Ollama rate limited the request"
        if 500 <= status_code <= 599:
            return ProviderErrorCategory.RETRYABLE_PROVIDER_FAILURE, LLMResultStatus.RETRYABLE_FAILURE, "Ollama server failure"
        return ProviderErrorCategory.PERMANENT_PROVIDER_FAILURE, LLMResultStatus.PERMANENT_FAILURE, "Ollama returned an unexpected HTTP status"

    def _normalize(self, request: LLMRequest, document: Any, structured: bool) -> LLMResponse:
        if not isinstance(document, Mapping):
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama response must be an object")
        if "error" in document:
            return self._response(request, LLMResultStatus.PERMANENT_FAILURE, ProviderErrorCategory.PERMANENT_PROVIDER_FAILURE, error_message="Ollama returned a provider error")
        if document.get("done") is not True:
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama response was incomplete")
        message = document.get("message")
        if not isinstance(message, Mapping):
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama response has no assistant message")
        if message.get("role") != "assistant":
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama response message is not from the assistant")
        raw_text = message.get("content")
        if not isinstance(raw_text, str):
            return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, error_message="Ollama assistant message has no content")
        returned_model = document.get("model") if isinstance(document.get("model"), str) and document["model"].strip() else self._config.model_name
        latency = document.get("total_duration")
        latency_ms = latency / 1_000_000 if isinstance(latency, int) and latency >= 0 else None
        usage: dict[str, int] = {}
        if isinstance(document.get("prompt_eval_count"), int) and document["prompt_eval_count"] >= 0:
            usage["prompt_tokens"] = document["prompt_eval_count"]
        if isinstance(document.get("eval_count"), int) and document["eval_count"] >= 0:
            usage["generated_tokens"] = document["eval_count"]
        parsed: Mapping[str, Any] | None = None
        if structured:
            try:
                candidate = json.loads(raw_text)
            except json.JSONDecodeError:
                return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, model_name=returned_model, raw_text=raw_text, error_message="Ollama structured output was not valid JSON")
            if not isinstance(candidate, Mapping):
                return self._response(request, LLMResultStatus.MALFORMED_OUTPUT, ProviderErrorCategory.MALFORMED_PROVIDER_RESPONSE, model_name=returned_model, raw_text=raw_text, error_message="Ollama structured output must be a JSON object")
            parsed = candidate
        responded_at = _parse_created_at(document.get("created_at"))
        if responded_at is None and self._clock is not None:
            try:
                candidate_time = self._clock()
                if isinstance(candidate_time, datetime) and candidate_time.tzinfo is not None and candidate_time.utcoffset() is not None:
                    responded_at = candidate_time.astimezone(timezone.utc)
            except Exception:
                pass
        finish_reason = document.get("done_reason") if isinstance(document.get("done_reason"), str) else None
        return self._response(request, LLMResultStatus.SUCCESS, model_name=returned_model, raw_text=raw_text, structured_output=parsed, finish_reason=finish_reason, token_usage=usage or None, latency_ms=latency_ms, responded_at=responded_at)


assert isinstance(OllamaProvider(OllamaConfig("offline-test-model"), transport=UrllibTransport()), LLMProvider)
