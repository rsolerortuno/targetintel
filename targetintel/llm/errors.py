"""Provider-neutral error categories and safe error-message handling."""

from __future__ import annotations

from enum import Enum
import re


class ProviderErrorCategory(str, Enum):
    """Audit-facing error categories; never expose provider exception details."""

    INVALID_REQUEST = "invalid_request"
    NOT_CONFIGURED = "not_configured"
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_FAILURE = "authorization_failure"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION_FAILURE = "connection_failure"
    RETRYABLE_PROVIDER_FAILURE = "retryable_provider_failure"
    PERMANENT_PROVIDER_FAILURE = "permanent_provider_failure"
    MALFORMED_PROVIDER_RESPONSE = "malformed_provider_response"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    NOT_EXECUTED = "not_executed"


RETRYABLE_ERROR_CATEGORIES = frozenset({
    ProviderErrorCategory.RATE_LIMIT,
    ProviderErrorCategory.TIMEOUT,
    ProviderErrorCategory.CONNECTION_FAILURE,
    ProviderErrorCategory.RETRYABLE_PROVIDER_FAILURE,
})


def is_retryable_error(category: ProviderErrorCategory | None) -> bool:
    """Return the deterministic retry policy for an error category."""
    return category in RETRYABLE_ERROR_CATEGORIES


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_ -]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
)


def sanitize_error_message(message: str | None) -> str | None:
    """Return a short, serializable diagnostic without common credential values."""
    if message is None:
        return None
    if not isinstance(message, str):
        raise ValueError("error_message must be a string or null")
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    return sanitized[:500]
