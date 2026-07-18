from __future__ import annotations

import pytest

from targetintel.evidence.snapshot_models import EvidenceSnapshotRequest
from targetintel.evidence.snapshots import create_reviewed_evidence_snapshot
from targetintel.llm.grounded_writer import build_target_evidence_inventory, generate_grounded_target_synthesis, render_grounded_synthesis_markdown
from targetintel.llm.providers.mock import MockProvider
from targetintel.llm.synthesis_models import TargetSynthesisRequest
from targetintel.llm.synthesis_prompt import build_target_synthesis_prompt
from targetintel.llm.contracts import LLMResultStatus, ProviderCapabilities
from tests.test_reviewed_evidence_snapshots import ReadOnlyFixtureStore, _item


def _snapshot():
    first = _item("ev-a", target_symbol="B2M", observation="B2M was associated with response.")
    second = _item("ev-b", target_symbol="B2M", source_id="other", evidence_direction="contradicts_target", observation="No significant difference was observed.")
    request = EvidenceSnapshotRequest.create(logical_store_id="reviewed-store", selection_mode="explicit_ids", selector={"evidence_item_ids": ["ev-a", "ev-b"]}, requesting_actor_id="reviewer", downstream_purpose="grounded_synthesis", empty_selection_policy="reject_empty")
    return create_reviewed_evidence_snapshot(request, ReadOnlyFixtureStore([first, second])).snapshot


def _request(snapshot):
    return TargetSynthesisRequest.create(snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, target_identity="B2M", context="melanoma", synthesis_purpose="target_evidence_summary", requested_sections=["limitations", "supported_observations"], maximum_statement_count=2, maximum_words_per_statement=30, requesting_actor_id="writer", language="en")


def _response(request, snapshot):
    from targetintel.llm.grounded_writer import build_target_evidence_inventory
    inventory = build_target_evidence_inventory(request, snapshot)
    return {"schema_id": "targetintel.grounded_target_synthesis", "schema_version": "1.0.0", "snapshot_id": snapshot.snapshot_id, "inventory_id": inventory.inventory_id, "target_identity": "B2M", "synthesis_purpose": request.synthesis_purpose, "sections": list(request.requested_sections), "statements": [{"local_statement_key": "s1", "section_identifier": "supported_observations", "statement_text": "The reviewed evidence reports an association.", "evidence_item_ids": ["ev-a"], "support_relation": "supported", "uncertainty_level": "moderate_uncertainty"}, {"local_statement_key": "s2", "section_identifier": "limitations", "statement_text": "A separate item reports no significant difference.", "evidence_item_ids": ["ev-b"], "support_relation": "contradicted", "uncertainty_level": "high_uncertainty", "limitation_text": "The observations conflict."}], "evidence_coverage": [{"evidence_item_id": "ev-a", "disposition": "cited"}, {"evidence_item_id": "ev-b", "disposition": "cited"}], "research_only": True, "non_clinical_use": True}


def test_mock_provider_generates_complete_immutable_snapshot_grounded_synthesis():
    snapshot = _snapshot(); request = _request(snapshot); response = _response(request, snapshot)
    llm_request = build_target_synthesis_prompt(request, build_target_evidence_inventory(request, snapshot))
    provider = MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})
    result = generate_grounded_target_synthesis(request, snapshot, provider)
    assert result.status == "generated" and result.synthesis is not None
    assert result.synthesis.cited_item_count == 2
    assert "[evidence:ev-a]" in render_grounded_synthesis_markdown(result.synthesis)
    assert len(provider.call_history) == 1


def test_unknown_reference_and_clinical_language_fail_closed():
    snapshot = _snapshot(); request = _request(snapshot); response = _response(request, snapshot)
    response["statements"][0]["evidence_item_ids"] = ["unknown"]
    inventory = build_target_evidence_inventory(request, snapshot)
    llm_request = build_target_synthesis_prompt(request, inventory)
    assert generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})).status == "unknown_evidence_reference"
    response = _response(request, snapshot); response["statements"][0]["statement_text"] = "Patients should receive this treatment."
    assert generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})).status == "unsafe_therapeutic_recommendation"


def test_inventory_is_exact_ordered_immutable_and_preserves_null_and_limiting_data():
    snapshot = _snapshot(); request = _request(snapshot)
    inventory = build_target_evidence_inventory(request, snapshot)
    assert inventory.ordered_evidence_item_ids == ("ev-a", "ev-b")
    assert inventory.selected_item_count == 2
    assert inventory.evidence_records[0]["observation"] == "B2M was associated with response."
    assert inventory.evidence_records[1]["observation"] == "No significant difference was observed."
    assert inventory.evidence_records[1]["evidence_direction"] == "contradicts_target"
    with pytest.raises(TypeError):
        inventory.evidence_records[0]["observation"] = "changed"
    assert build_target_evidence_inventory(request, snapshot).inventory_id == inventory.inventory_id
    lower_target = TargetSynthesisRequest.create(snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, target_identity="b2m", context="melanoma", synthesis_purpose="target_evidence_summary", requested_sections=["limitations", "supported_observations"], maximum_statement_count=2, maximum_words_per_statement=30, requesting_actor_id="writer", language="en")
    other_context = TargetSynthesisRequest.create(snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, target_identity="B2M", context="other", synthesis_purpose="target_evidence_summary", requested_sections=["limitations", "supported_observations"], maximum_statement_count=2, maximum_words_per_statement=30, requesting_actor_id="writer", language="en")
    assert generate_grounded_target_synthesis(lower_target, snapshot, MockProvider({})).status == "target_not_present"
    assert generate_grounded_target_synthesis(other_context, snapshot, MockProvider({})).status == "context_not_present"


@pytest.mark.parametrize("outcome,expected", [
    ({"status": "timeout", "error_category": "timeout"}, "provider_error"),
    ({"status": "malformed_output", "error_category": "malformed_provider_response"}, "provider_error"),
    ({"status": "success", "raw_text": "not-json"}, "response_schema_error"),
])
def test_provider_and_malformed_response_fail_closed_without_retry(outcome, expected):
    snapshot = _snapshot(); request = _request(snapshot)
    llm_request = build_target_synthesis_prompt(request, build_target_evidence_inventory(request, snapshot))
    provider = MockProvider({llm_request.request_id: outcome})
    result = generate_grounded_target_synthesis(request, snapshot, provider)
    assert result.status == expected and result.synthesis is None
    assert len(provider.call_history) == 1
    assert "traceback" not in result.canonical_json().lower()


def test_unsupported_provider_capability_does_not_execute_provider():
    snapshot = _snapshot(); request = _request(snapshot)
    provider = MockProvider({}, capabilities=ProviderCapabilities(structured_output=False, json_schema=False))
    result = generate_grounded_target_synthesis(request, snapshot, provider)
    assert result.status == "unsupported_provider_capability"
    assert not provider.call_history


def test_coverage_omission_and_unknown_reason_fail_closed():
    snapshot = _snapshot(); request = _request(snapshot); response = _response(request, snapshot)
    response["evidence_coverage"] = [{"evidence_item_id": "ev-a", "disposition": "cited"}]
    llm_request = build_target_synthesis_prompt(request, build_target_evidence_inventory(request, snapshot))
    assert generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})).status == "incomplete_evidence_coverage"
    response = _response(request, snapshot)
    response["statements"] = response["statements"][:1]
    response["evidence_coverage"][1] = {"evidence_item_id": "ev-b", "disposition": "unsynthesized", "reason": "duplicate_scientific_observation"}
    assert generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})).status == "incomplete_evidence_coverage"
    response = _response(request, snapshot)
    response["evidence_coverage"][1] = {"evidence_item_id": "ev-b", "disposition": "unsynthesized", "reason": "not_allowed"}
    assert generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}})).status == "response_schema_error"


def test_markdown_is_deterministic_and_renders_all_required_boundaries():
    snapshot = _snapshot(); request = _request(snapshot); response = _response(request, snapshot)
    llm_request = build_target_synthesis_prompt(request, build_target_evidence_inventory(request, snapshot))
    result = generate_grounded_target_synthesis(request, snapshot, MockProvider({llm_request.request_id: {"status": "success", "structured_output": response}}))
    rendered = render_grounded_synthesis_markdown(result.synthesis)
    assert rendered == render_grounded_synthesis_markdown(result.synthesis)
    for expected in ("[evidence:ev-a]", "[evidence:ev-b]", "Limitation:", "high_uncertainty", "Research-only", "Non-clinical use", "No score or ranking was generated", "No file was written"):
        assert expected in rendered
    assert result.synthesis.no_score_or_ranking_generated and result.synthesis.no_file_written
