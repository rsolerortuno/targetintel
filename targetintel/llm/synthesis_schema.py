"""Strict, dependency-free schema validation for grounded synthesis responses."""
from __future__ import annotations
import json
from typing import Any, Mapping

from .contracts import canonical_json
from .synthesis_models import SECTION_IDENTIFIERS, SUPPORT_RELATIONS, UNCERTAINTY_LEVELS, UNSYNTHESIZED_REASONS

TARGET_SYNTHESIS_SCHEMA_ID = "targetintel.grounded_target_synthesis"
TARGET_SYNTHESIS_SCHEMA_VERSION = "1.0.0"

def target_synthesis_schema() -> dict[str, Any]:
    statement = {"type": "object", "additionalProperties": False, "required": ["local_statement_key", "section_identifier", "statement_text", "evidence_item_ids", "support_relation", "uncertainty_level"], "properties": {"local_statement_key": {"type": "string", "minLength": 1}, "section_identifier": {"enum": sorted(SECTION_IDENTIFIERS)}, "statement_text": {"type": "string", "minLength": 1}, "evidence_item_ids": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}}, "support_relation": {"enum": sorted(SUPPORT_RELATIONS)}, "uncertainty_level": {"enum": sorted(UNCERTAINTY_LEVELS)}, "limitation_text": {"type": ["string", "null"]}}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{TARGET_SYNTHESIS_SCHEMA_ID}/{TARGET_SYNTHESIS_SCHEMA_VERSION}", "type": "object", "additionalProperties": False, "required": ["schema_id", "schema_version", "snapshot_id", "inventory_id", "target_identity", "synthesis_purpose", "sections", "statements", "evidence_coverage", "research_only", "non_clinical_use"], "properties": {"schema_id": {"const": TARGET_SYNTHESIS_SCHEMA_ID}, "schema_version": {"const": TARGET_SYNTHESIS_SCHEMA_VERSION}, "snapshot_id": {"type": "string", "minLength": 1}, "inventory_id": {"type": "string", "minLength": 1}, "target_identity": {"type": "string", "minLength": 1}, "synthesis_purpose": {"type": "string"}, "sections": {"type": "array", "items": {"enum": sorted(SECTION_IDENTIFIERS)}}, "statements": {"type": "array", "items": statement}, "evidence_coverage": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["evidence_item_id", "disposition"], "properties": {"evidence_item_id": {"type": "string", "minLength": 1}, "disposition": {"enum": ["cited", "unsynthesized"]}, "reason": {"enum": sorted(UNSYNTHESIZED_REASONS)}}}}, "research_only": {"const": True}, "non_clinical_use": {"const": True}}}

def parse_target_synthesis_response(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping): raise ValueError("response must be an object")
    data = json.loads(canonical_json(data))
    schema = target_synthesis_schema(); required = set(schema["required"]); allowed = set(schema["properties"])
    if set(data) - allowed or required - set(data): raise ValueError("response schema fields are invalid")
    if data["schema_id"] != TARGET_SYNTHESIS_SCHEMA_ID or data["schema_version"] != TARGET_SYNTHESIS_SCHEMA_VERSION: raise ValueError("response schema identifier mismatch")
    for name in ("snapshot_id", "inventory_id", "target_identity", "synthesis_purpose"):
        if not isinstance(data[name], str) or not data[name].strip(): raise ValueError("response identity field is invalid")
    if not isinstance(data["sections"], list) or len(data["sections"]) != len(set(data["sections"])) or set(data["sections"]) - SECTION_IDENTIFIERS: raise ValueError("response sections are invalid")
    if not isinstance(data["statements"], list) or not isinstance(data["evidence_coverage"], list) or data["research_only"] is not True or data["non_clinical_use"] is not True: raise ValueError("response boundary fields are invalid")
    seen_keys: set[str] = set()
    for value in data["statements"]:
        props = schema["properties"]["statements"]["items"]["properties"]; req = set(schema["properties"]["statements"]["items"]["required"])
        if not isinstance(value, Mapping) or set(value) - set(props) or req - set(value): raise ValueError("statement schema fields are invalid")
        if not isinstance(value["local_statement_key"], str) or not value["local_statement_key"].strip() or value["local_statement_key"] in seen_keys: raise ValueError("statement key is invalid")
        seen_keys.add(value["local_statement_key"])
        if value["section_identifier"] not in SECTION_IDENTIFIERS or not isinstance(value["statement_text"], str) or not value["statement_text"].strip() or not isinstance(value["evidence_item_ids"], list) or not value["evidence_item_ids"] or any(not isinstance(x, str) or not x for x in value["evidence_item_ids"]) or value["support_relation"] not in SUPPORT_RELATIONS or value["uncertainty_level"] not in UNCERTAINTY_LEVELS: raise ValueError("statement values are invalid")
        if "limitation_text" in value and value["limitation_text"] is not None and not isinstance(value["limitation_text"], str): raise ValueError("limitation text is invalid")
    seen_evidence: set[str] = set()
    for value in data["evidence_coverage"]:
        if not isinstance(value, Mapping) or set(value) - {"evidence_item_id", "disposition", "reason"} or {"evidence_item_id", "disposition"} - set(value) or not isinstance(value["evidence_item_id"], str) or not value["evidence_item_id"] or value["evidence_item_id"] in seen_evidence or value["disposition"] not in {"cited", "unsynthesized"}: raise ValueError("coverage record is invalid")
        seen_evidence.add(value["evidence_item_id"])
        if value["disposition"] == "unsynthesized" and value.get("reason") not in UNSYNTHESIZED_REASONS: raise ValueError("unsynthesized reason is invalid")
        if value["disposition"] == "cited" and "reason" in value: raise ValueError("cited evidence cannot have a reason")
    return data
