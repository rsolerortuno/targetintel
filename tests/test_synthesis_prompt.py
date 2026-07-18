"""Prompt boundary and deterministic identity coverage for Issue 309."""
from __future__ import annotations

from datetime import datetime, timezone

from targetintel.llm.grounded_writer import build_target_evidence_inventory
from targetintel.llm.synthesis_prompt import (
    TARGET_SYNTHESIS_PROMPT_ID, TARGET_SYNTHESIS_PROMPT_VERSION,
    build_target_synthesis_prompt, prompt_identity,
)
from targetintel.llm.synthesis_models import TargetSynthesisRequest
from tests.test_grounded_writer import _snapshot


def _request(snapshot, requested_at=None):
    return TargetSynthesisRequest.create(snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash,
        target_identity="B2M", context="melanoma", synthesis_purpose="target_evidence_summary",
        requested_sections=["supported_observations", "limitations"], maximum_statement_count=3,
        maximum_words_per_statement=40, requesting_actor_id="writer", language="en", requested_at=requested_at)


def test_prompt_is_versioned_deterministic_and_treats_inventory_as_untrusted_data():
    snapshot = _snapshot(); request = _request(snapshot); inventory = build_target_evidence_inventory(request, snapshot)
    prompt = build_target_synthesis_prompt(request, inventory)
    later = _request(snapshot, datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert prompt.prompt_id == TARGET_SYNTHESIS_PROMPT_ID
    assert prompt.prompt_version == TARGET_SYNTHESIS_PROMPT_VERSION
    assert prompt_identity(request, inventory) == prompt_identity(later, inventory)
    text = f"{prompt.system_instruction} {prompt.user_instruction}".lower()
    for required in ("untrusted", "external knowledge", "invented citations", "hidden reasoning", "clinical guidance", "evidenceitem ids"):
        assert required in text
    assert prompt.source_text is None
    assert "quoted_span" not in str(prompt.structured_source_content)
