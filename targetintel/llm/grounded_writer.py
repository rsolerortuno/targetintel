"""Pure orchestration for Issue 309 snapshot-grounded target synthesis."""
from __future__ import annotations
import json
import re
from hashlib import sha256
from typing import Any, Mapping

from targetintel.evidence.snapshot_models import ReviewedEvidenceSnapshot
from .claim_rules import CLINICAL_GUIDANCE_MARKERS, NEGATED_RECOMMENDATION_MARKERS, THERAPEUTIC_RECOMMENDATION_MARKERS, CAUSAL_MARKERS, ASSOCIATIVE_MARKERS, CLINICAL_EXTRAPOLATION_MARKERS
from .contracts import LLMProvider, LLMResultStatus, canonical_json
from .execution import execute_request
from .synthesis_models import (GROUNDED_STATEMENT_FORMAT_VERSION, GROUNDED_SYNTHESIS_FORMAT_VERSION, TargetSynthesisRequest, TargetEvidenceInventory, GroundedSynthesisStatement, GroundedTargetSynthesis, make_synthesis_result)
from .synthesis_prompt import TARGET_SYNTHESIS_PROMPT_ID, build_target_synthesis_prompt
from .synthesis_schema import parse_target_synthesis_response

def build_target_evidence_inventory(request: TargetSynthesisRequest, snapshot: ReviewedEvidenceSnapshot) -> TargetEvidenceInventory | None:
    """Select exact target and (when requested) exact ``disease_name`` matches."""
    if not isinstance(request, TargetSynthesisRequest) or not isinstance(snapshot, ReviewedEvidenceSnapshot): raise TypeError("only TargetSynthesisRequest and ReviewedEvidenceSnapshot are accepted")
    if snapshot.snapshot_id != request.snapshot_id or snapshot.manifest_hash != request.snapshot_manifest_hash or snapshot.snapshot_validation_state != "validated": return None
    entries = [entry for entry in snapshot.entries if entry.evidence_item.target_symbol == request.target_identity]
    if request.context is not None: entries = [entry for entry in entries if entry.evidence_item.disease_name == request.context]
    if not entries: return None
    entries.sort(key=lambda x: x.evidence_item_id)
    records = []
    for entry in entries:
        item = entry.evidence_item
        # This deliberately excludes source documents, quoted spans, paths, and operational timestamps.
        records.append({"evidence_item_id": item.evidence_id, "payload_hash": entry.canonical_payload_hash, "target_symbol": item.target_symbol, "target_id": item.target_id, "disease_name": item.disease_name, "disease_id": item.disease_id, "treatment_name": item.treatment_name, "evidence_type": item.evidence_type, "evidence_direction": item.evidence_direction, "observation": item.observation, "interpretation": item.interpretation, "species": item.species, "model_system": item.model_system, "sample_context": item.sample_context, "comparison": item.comparison, "endpoint": item.endpoint, "source": item.source, "source_id": item.source_id, "publication_id": item.publication_id, "source_dataset_id": item.source_dataset_id, "patient_cohort_id": item.patient_cohort_id, "experiment_id": item.experiment_id, "validation_status": item.validation_status, "provenance_references": entry.provenance_references})
    ids, hashes = tuple(x.evidence_item_id for x in entries), tuple(x.canonical_payload_hash for x in entries)
    payload = {"inventory_format_version": "targetintel.target_evidence_inventory.v1", "snapshot_id": snapshot.snapshot_id, "snapshot_manifest_hash": snapshot.manifest_hash, "target_identity": request.target_identity, "context": request.context, "ordered_evidence_item_ids": list(ids), "ordered_payload_hashes": list(hashes)}
    digest = sha256(canonical_json(payload).encode()).hexdigest()
    return TargetEvidenceInventory(inventory_format_version="targetintel.target_evidence_inventory.v1", inventory_id=digest, snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, target_identity=request.target_identity, context=request.context, ordered_evidence_item_ids=ids, ordered_payload_hashes=hashes, evidence_records=tuple(records), selected_item_count=len(ids), inventory_hash=digest)

def _result(request: TargetSynthesisRequest | None, status: str, code: str, **values: Any):
    return make_synthesis_result(status=status, request_id=None if request is None else request.request_id, snapshot_id=None if request is None else request.snapshot_id, inventory_id=values.get("inventory_id"), prompt_id=values.get("prompt_id"), llm_request_id=values.get("llm_request_id"), llm_response_id=values.get("llm_response_id"), synthesis_id=None, synthesis=None, codes=(code,))

def _positive_recommendation(text: str) -> bool:
    for clause in re.split(r"[.!?;]+", text.lower()):
        if any(marker in clause for marker in NEGATED_RECOMMENDATION_MARKERS): continue
        if any(marker in clause for marker in THERAPEUTIC_RECOMMENDATION_MARKERS): return True
    return False

def _safety_codes(text: str, records: tuple[Mapping[str, Any], ...], ids: tuple[str, ...]) -> tuple[str, ...]:
    lower = text.lower(); codes: set[str] = set()
    if _positive_recommendation(text): codes.add("unsupported_therapeutic_recommendation")
    if any(marker in lower for marker in CLINICAL_GUIDANCE_MARKERS): codes.add("clinical_guidance_language")
    cited = [x for x in records if x["evidence_item_id"] in ids]
    observations = " ".join(str(x["observation"]) for x in cited).lower()
    if any(x in lower for x in CAUSAL_MARKERS) and any(x in observations for x in ASSOCIATIVE_MARKERS): codes.add("association_presented_as_causation")
    if any(x["species"] != "human" or x["model_system"] in {"cell_line", "organoid", "syngeneic_mouse_model", "patient_derived_xenograft"} for x in cited) and any(x in lower for x in CLINICAL_EXTRAPOLATION_MARKERS): codes.add("preclinical_presented_as_clinical")
    return tuple(sorted(codes))

def generate_grounded_target_synthesis(request: TargetSynthesisRequest, snapshot: ReviewedEvidenceSnapshot, provider: LLMProvider):
    if not isinstance(request, TargetSynthesisRequest): return _result(None, "invalid_request", "invalid_request")
    if not isinstance(snapshot, ReviewedEvidenceSnapshot): return _result(request, "invalid_snapshot", "snapshot_type_invalid")
    if snapshot.snapshot_id != request.snapshot_id: return _result(request, "snapshot_identity_mismatch", "snapshot_id_mismatch")
    if snapshot.manifest_hash != request.snapshot_manifest_hash: return _result(request, "snapshot_manifest_mismatch", "snapshot_manifest_mismatch")
    if snapshot.snapshot_validation_state != "validated": return _result(request, "invalid_snapshot", "snapshot_not_validated")
    target_entries = [x for x in snapshot.entries if x.evidence_item.target_symbol == request.target_identity]
    if not target_entries: return _result(request, "target_not_present", "target_not_present")
    if request.context is not None and not [x for x in target_entries if x.evidence_item.disease_name == request.context]: return _result(request, "context_not_present", "context_not_present")
    inventory = build_target_evidence_inventory(request, snapshot)
    if inventory is None: return _result(request, "inventory_empty", "inventory_empty")
    if inventory.selected_item_count > request.maximum_statement_count * 1000: return _result(request, "item_limit_exceeded", "inventory_item_limit_exceeded", inventory_id=inventory.inventory_id)
    if not isinstance(provider, LLMProvider): return _result(request, "provider_error", "provider_contract_invalid", inventory_id=inventory.inventory_id)
    caps = provider.capabilities
    if caps.structured_output is not True or caps.json_schema is not True:
        return _result(request, "unsupported_provider_capability", "structured_output_required", inventory_id=inventory.inventory_id)
    llm_request = build_target_synthesis_prompt(request, inventory)
    try: execution = execute_request(llm_request, provider)
    except Exception: return _result(request, "provider_error", "provider_execution_failed", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id)
    response = execution.response
    response_id = response.payload_identity()
    if response.status is not LLMResultStatus.SUCCESS:
        code = "provider_timeout" if response.status is LLMResultStatus.TIMEOUT else "provider_unsuccessful"
        return _result(request, "provider_error", code, inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    raw: Any = response.structured_output
    if raw is None:
        try: raw = json.loads(response.raw_text or "")
        except (ValueError, TypeError): return _result(request, "response_schema_error", "malformed_response", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    try: data = parse_target_synthesis_response(raw)
    except ValueError: return _result(request, "response_schema_error", "response_schema_invalid", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    if data["snapshot_id"] != snapshot.snapshot_id or data["inventory_id"] != inventory.inventory_id or data["target_identity"] != request.target_identity or data["synthesis_purpose"] != request.synthesis_purpose:
        return _result(request, "response_identity_mismatch", "response_identity_mismatch", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    if tuple(data["sections"]) != request.requested_sections or any(x["section_identifier"] not in request.requested_sections for x in data["statements"]):
        return _result(request, "response_schema_error", "response_sections_mismatch", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    allowed = set(inventory.ordered_evidence_item_ids); hash_by_id = dict(zip(inventory.ordered_evidence_item_ids, inventory.ordered_payload_hashes)); statements = []
    for raw_statement in data["statements"]:
        ids = tuple(sorted(raw_statement["evidence_item_ids"]))
        if len(ids) != len(set(ids)): return _result(request, "unknown_evidence_reference", "duplicate_evidence_reference", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
        if set(ids) - allowed: return _result(request, "unknown_evidence_reference", "unknown_evidence_reference", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
        if len(raw_statement["statement_text"].split()) > request.maximum_words_per_statement: return _result(request, "invalid_synthesis", "statement_word_limit_exceeded", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
        safety = _safety_codes(raw_statement["statement_text"], inventory.evidence_records, ids)
        if "unsupported_therapeutic_recommendation" in safety: return _result(request, "unsafe_therapeutic_recommendation", "unsupported_therapeutic_recommendation", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
        if "clinical_guidance_language" in safety: return _result(request, "unsafe_clinical_language", "clinical_guidance_language", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
        identity = {"statement_format_version": GROUNDED_STATEMENT_FORMAT_VERSION, "local_statement_key": raw_statement["local_statement_key"], "section_identifier": raw_statement["section_identifier"], "statement_text": raw_statement["statement_text"], "evidence_item_ids": list(ids), "evidence_payload_hashes": [hash_by_id[x] for x in ids], "support_relation": raw_statement["support_relation"], "uncertainty_level": raw_statement["uncertainty_level"], "limitation_text": raw_statement.get("limitation_text"), "safety_codes": list(safety), "research_only": True}
        statements.append(GroundedSynthesisStatement(statement_id=sha256(canonical_json(identity).encode()).hexdigest(), **identity))
    if len(statements) > request.maximum_statement_count: return _result(request, "invalid_synthesis", "statement_limit_exceeded", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    coverage = tuple(sorted((dict(x) for x in data["evidence_coverage"]), key=lambda x: x["evidence_item_id"]))
    if {x["evidence_item_id"] for x in coverage} != allowed: return _result(request, "incomplete_evidence_coverage", "incomplete_evidence_coverage", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    cited = {item for statement in statements for item in statement.evidence_item_ids}
    if any(x["disposition"] == "cited" and x["evidence_item_id"] not in cited for x in coverage) or any(x["disposition"] == "unsynthesized" and x["evidence_item_id"] in cited for x in coverage): return _result(request, "incomplete_evidence_coverage", "coverage_disposition_mismatch", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    record_by_id = {x["evidence_item_id"]: x for x in inventory.evidence_records}
    for row in coverage:
        if row["disposition"] != "unsynthesized": continue
        record = record_by_id[row["evidence_item_id"]]
        null_marker = any(marker in record["observation"].lower() for marker in ("no significant difference", "not significant", "null finding", "no difference"))
        if record["evidence_direction"] in {"contradicts_target", "limits_target"} or null_marker:
            return _result(request, "incomplete_evidence_coverage", "contradictory_or_null_evidence_omitted", inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id)
    identity = {"synthesis_format_version": GROUNDED_SYNTHESIS_FORMAT_VERSION, "request_id": request.request_id, "snapshot_id": snapshot.snapshot_id, "snapshot_manifest_hash": snapshot.manifest_hash, "inventory_id": inventory.inventory_id, "prompt_id": TARGET_SYNTHESIS_PROMPT_ID, "llm_response_id": response_id, "target_identity": request.target_identity, "context": request.context, "synthesis_purpose": request.synthesis_purpose, "sections": list(request.requested_sections), "statement_ids": [x.statement_id for x in statements], "evidence_coverage": list(coverage), "research_only": True}
    synthesis = GroundedTargetSynthesis(synthesis_format_version=GROUNDED_SYNTHESIS_FORMAT_VERSION, synthesis_id=sha256(canonical_json(identity).encode()).hexdigest(), request_id=request.request_id, snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id, provider_name=response.provider_name, model_name=response.model_name, model_version=response.model_version, target_identity=request.target_identity, context=request.context, synthesis_purpose=request.synthesis_purpose, sections=request.requested_sections, statements=tuple(statements), evidence_coverage=coverage, selected_item_count=inventory.selected_item_count, cited_item_count=len(cited), unsynthesized_item_count=inventory.selected_item_count-len(cited), research_only=True, non_clinical_use=True, no_score_or_ranking_generated=True, no_file_written=True)
    return make_synthesis_result(status="generated", request_id=request.request_id, snapshot_id=snapshot.snapshot_id, inventory_id=inventory.inventory_id, prompt_id=TARGET_SYNTHESIS_PROMPT_ID, llm_request_id=llm_request.request_id, llm_response_id=response_id, synthesis_id=synthesis.synthesis_id, synthesis=synthesis, codes=())

def render_grounded_synthesis_markdown(synthesis: GroundedTargetSynthesis) -> str:
    if not isinstance(synthesis, GroundedTargetSynthesis): raise TypeError("synthesis must be GroundedTargetSynthesis")
    lines = [f"# Research-only synthesis: {synthesis.target_identity}", "", "This is a research communication artifact, not clinical guidance. No score or ranking was generated.", ""]
    for section in synthesis.sections:
        lines += [f"## {section.replace('_', ' ').title()}", ""]
        for statement in (x for x in synthesis.statements if x.section_identifier == section):
            text = statement.statement_text.replace("\n", " ").replace("<", "\\<").replace(">", "\\>")
            citations = " ".join(f"[evidence:{x}]" for x in statement.evidence_item_ids)
            lines.append(f"- {text} {citations} (uncertainty: {statement.uncertainty_level}; relation: {statement.support_relation})")
            if statement.limitation_text: lines.append(f"  - Limitation: {statement.limitation_text.replace(chr(10), ' ')}")
        lines.append("")
    lines += ["## Boundaries", "", "Research-only. Non-clinical use. No score or ranking was generated. No file was written."]
    return "\n".join(lines) + "\n"
