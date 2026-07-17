"""Strict, offline input boundary for recorded human review decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

REVIEW_SCHEMA_ID = "targetintel-human-review-decision"
REVIEW_SCHEMA_VERSION = "v1"
HIDDEN_REASONING_FIELDS = frozenset({"thinking", "reasoning", "chain_of_thought", "scratchpad", "analysis"})
SECRET_TERMS = ("api_key", "apikey", "authorization", "password", "secret", "access_token", "token")


def reject_unsafe(value: Any) -> None:
    """Reject secrets, hidden reasoning, and values outside JSON primitives."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("review object keys must be strings")
            normalized = key.lower().replace("-", "_")
            if normalized in HIDDEN_REASONING_FIELDS:
                raise ValueError("hidden reasoning fields are forbidden")
            if any(term in normalized for term in SECRET_TERMS):
                raise ValueError("secrets and credentials are forbidden")
            reject_unsafe(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_unsafe(item)
    elif not isinstance(value, (str, int, float, bool, type(None), datetime)):
        raise ValueError("review values must be JSON primitives")


def require_exact_fields(data: Mapping[str, Any], allowed: frozenset[str], required: frozenset[str], label: str) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{label} must be an object")
    reject_unsafe(data)
    unknown, missing = set(data).difference(allowed), required.difference(data)
    if unknown:
        raise ValueError(f"unknown {label} field")
    if missing:
        raise ValueError(f"missing required {label} field")
