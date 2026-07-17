"""Closed, versioned JSON Schema for grounded claim extraction."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import canonical_json


GROUNDED_EXTRACTION_SCHEMA_ID = "targetintel.grounded_extraction"
GROUNDED_EXTRACTION_SCHEMA_VERSION = "1.0.0"

_HIDDEN_REASONING_FIELDS = frozenset({"thinking", "reasoning", "chain_of_thought", "scratchpad", "analysis"})
_RAW_LIST_FIELDS = ("target_mentions", "disease_mentions", "species_mentions", "model_system_mentions")
_RAW_STRING_FIELDS = ("cohort_description", "effect_description", "limitations", "source_locator", "evidence_type_hint")


def _schema() -> dict[str, Any]:
    claim_properties: dict[str, Any] = {
        "claim_text": {"type": "string", "minLength": 1},
        "quoted_span": {"type": "string", "minLength": 1},
        "quote_start": {"type": "integer", "minimum": 0},
        "quote_end": {"type": "integer", "minimum": 1},
        "stance": {"type": "string", "enum": ["supports", "contradicts", "contextual", "unclear"]},
    }
    claim_properties.update({name: {"type": "array", "items": {"type": "string"}} for name in _RAW_LIST_FIELDS})
    claim_properties.update({name: {"type": "string"} for name in _RAW_STRING_FIELDS})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{GROUNDED_EXTRACTION_SCHEMA_ID}/{GROUNDED_EXTRACTION_SCHEMA_VERSION}",
        "title": "TargetIntel grounded extraction",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_id", "schema_version", "source_document_id", "claims"],
        "properties": {
            "schema_id": {"const": GROUNDED_EXTRACTION_SCHEMA_ID},
            "schema_version": {"const": GROUNDED_EXTRACTION_SCHEMA_VERSION},
            "source_document_id": {"type": "string", "minLength": 1},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim_text", "quoted_span", "quote_start", "quote_end", "stance"],
                    "properties": claim_properties,
                },
            },
        },
    }


_SCHEMA = _schema()


class GroundedSchemaRegistry:
    """Small in-memory resolver suitable for provider structured-output hooks."""

    def resolve(self, schema_id: str, schema_version: str) -> Mapping[str, Any]:
        if (schema_id, schema_version) != (GROUNDED_EXTRACTION_SCHEMA_ID, GROUNDED_EXTRACTION_SCHEMA_VERSION):
            raise ValueError("unknown grounded extraction schema identifier or version")
        return deepcopy(_SCHEMA)

    def __call__(self, schema_id: str, schema_version: str) -> Mapping[str, Any]:
        return self.resolve(schema_id, schema_version)


DEFAULT_GROUNDED_SCHEMA_REGISTRY = GroundedSchemaRegistry()


def grounded_extraction_schema() -> dict[str, Any]:
    """Return a defensive copy of the only supported grounded schema."""
    return deepcopy(_SCHEMA)


def grounded_schema_canonical_json() -> str:
    return canonical_json(_SCHEMA)
