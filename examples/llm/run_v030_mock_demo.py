"""Fully offline, synthetic v0.3.0 public-API demonstration."""
from __future__ import annotations
import argparse, json, tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from targetintel.evidence.persistence_models import EvidencePersistenceRequest
from targetintel.evidence.reviewed_persistence import persist_promoted_evidence
from targetintel.evidence.snapshot_models import EvidenceSnapshotRequest
from targetintel.evidence.snapshots import create_reviewed_evidence_snapshot
from targetintel.evidence.store import EvidenceStore
from targetintel.export import build_obsidian_export_plan, persist_obsidian_export
from targetintel.export.obsidian_models import ObsidianExportRequest
from targetintel.llm import (TargetSynthesisRequest, audit_grounded_claims,
    build_grounded_extraction_request, build_human_review_packet,
    build_target_evidence_inventory, create_human_review_decision,
    extract_grounded_candidates, generate_grounded_target_synthesis,
    promote_candidate_to_evidence, WarningDisposition)
from targetintel.llm.evidence_promotion import EvidencePromotionRequest
from targetintel.llm.execution import execute_request
from targetintel.llm.providers.mock import MockProvider
from targetintel.llm.synthesis_prompt import build_target_synthesis_prompt

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures" / "mock_source.json"
NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)

def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

def _mapping(source_id: str, observation: str, direction: str) -> dict:
    return {"target_symbol":"DEMO_TARGET", "target_id":None, "disease_name":"DEMO_DISEASE", "disease_id":"DEMO_DISEASE:001", "treatment_name":None, "treatment_id":None, "evidence_type":"genetic_association", "evidence_direction":direction, "observation":observation, "interpretation":"Synthetic reviewer-recorded interpretation.", "source":"DEMO_DATASET", "source_id":source_id, "document_location":None, "computed_support":None, "publication_id":None, "source_dataset_id":"DEMO_DATASET", "patient_cohort_id":"DEMO_COHORT", "experiment_id":None, "comparison":None, "endpoint":None, "data_modality":None, "species":"human", "model_system":"other", "sample_context":None, "effect_size":None, "effect_size_metric":None, "uncertainty":None, "uncertainty_metric":None, "sample_size":None, "extraction_method":"manual", "extraction_confidence":None, "validation_status":"manually_curated", "retrieved_at":NOW, "data_release":"synthetic-v1", "derived_from":(), "evidence_family":None, "evidence_family_algorithm_version":"efam-v1", "evidence_family_basis":"ineligible", "independence_eligible":False, "independence_ineligibility_reason":"No evidence-family assignment is supplied."}

def run_demo(output_dir: str | Path | None = None) -> dict:
    """Run only public offline APIs; output is caller-selected or temporary."""
    out = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="targetintel-v030-demo-"))
    out.mkdir(parents=True, exist_ok=True); artifacts = out / "artifacts"
    source = json.loads(FIXTURE.read_text(encoding="utf-8")); text = source["source_text"]; doc = source["source_document_id"]
    quotes = [
        ("DEMO_TARGET was associated with the synthetic response observation.", "supports"),
        ("The DEMO_COHORT was small and the observation is uncertain.", "contextual"),
        ("A separate DEMO_COHORT comparison found no significant difference for DEMO_TARGET.", "contradicts"),
    ]
    claims = [{"claim_text": q, "quoted_span":q, "quote_start":text.index(q), "quote_end":text.index(q)+len(q), "stance":stance, "target_mentions":["DEMO_TARGET"], "disease_mentions":["DEMO_DISEASE"], "cohort_description":"DEMO_COHORT"} for q, stance in quotes]
    extraction_request = build_grounded_extraction_request(request_id="demo-extraction-request-v1", source_document_id=doc, source_text=text)
    provider = MockProvider({extraction_request.request_id: {"status":"success", "structured_output":{"schema_id":"targetintel.grounded_extraction", "schema_version":"1.0.0", "source_document_id":doc, "claims":claims}}})
    extraction_execution = execute_request(extraction_request, provider, clock=lambda: NOW)
    extraction = extract_grounded_candidates(extraction_request, extraction_execution.response)
    audit = audit_grounded_claims(extraction, doc, text); packet = build_human_review_packet(extraction, audit, created_at=NOW)
    _write(artifacts / "extraction.json", extraction.to_dict()); _write(artifacts / "audit.json", audit.to_dict())
    directions = ("supports_target", "limits_target", "contradicts_target")
    promotions=[]; decisions=[]; receipts=[]
    store_path = out / "artifacts" / "reviewed-evidence.duckdb"
    with EvidenceStore(store_path, logical_store_id="demo-reviewed-store") as store:
        for candidate, card, direction in zip(extraction.accepted_candidates, audit.cards, directions):
            mapping = _mapping(doc, candidate.claim_text, direction)
            dispositions = tuple(WarningDisposition(f.rule_id, "accepted_with_justification", "Synthetic reviewer recorded the warning.") for f in card.findings if f.severity == "warning")
            decision = create_human_review_decision(packet_id=packet.packet_id, candidate_id=candidate.candidate_id, card_id=card.card_id, audit_result_id=audit.audit_result_id, reviewer_id="DEMO_REVIEWER", decision="approve", decision_justification="Synthetic workflow approval; not scientific or clinical validation.", warning_dispositions=dispositions, evidence_mapping=mapping, reviewed_at=NOW)
            promotion = promote_candidate_to_evidence(EvidencePromotionRequest(text, doc, extraction, audit, packet, decision, candidate.candidate_id, mapping))
            if promotion.status != "promoted": raise RuntimeError(f"promotion failed: {promotion.status}")
            receipt = persist_promoted_evidence(EvidencePersistenceRequest.create(promotion_result=promotion, persistence_actor_id="DEMO_PERSISTENCE_ACTOR", logical_store_id="demo-reviewed-store", requested_at=NOW), store)
            if receipt.status not in {"persisted", "already_persisted"}: raise RuntimeError(f"persistence failed: {receipt.status}")
            promotions.append(promotion); decisions.append(decision); receipts.append(receipt)
        snapshot_request = EvidenceSnapshotRequest.create(logical_store_id="demo-reviewed-store", selection_mode="explicit_ids", selector={"evidence_item_ids":[x.evidence_item_id for x in promotions]}, requesting_actor_id="DEMO_SNAPSHOT_ACTOR", downstream_purpose="grounded_synthesis", empty_selection_policy="reject_empty", requested_at=NOW)
        snapshot_result = create_reviewed_evidence_snapshot(snapshot_request, store)
    if snapshot_result.status != "created" or snapshot_result.snapshot is None: raise RuntimeError("snapshot failed")
    snapshot = snapshot_result.snapshot
    _write(artifacts / "review.json", {"packet":packet.to_dict(), "decisions":[x.to_dict() for x in decisions]})
    _write(artifacts / "promotion.json", {"promotions":[x.to_dict() for x in promotions]})
    _write(artifacts / "persistence.json", {"receipts":[x.to_dict() for x in receipts]})
    _write(artifacts / "snapshot.json", snapshot_result.to_dict())
    synth_request = TargetSynthesisRequest.create(snapshot_id=snapshot.snapshot_id, snapshot_manifest_hash=snapshot.manifest_hash, target_identity="DEMO_TARGET", context="DEMO_DISEASE", synthesis_purpose="target_evidence_summary", requested_sections=["supported_observations","contradictory_evidence","limitations"], maximum_statement_count=3, maximum_words_per_statement=40, requesting_actor_id="DEMO_SYNTHESIS_ACTOR", language="en", requested_at=NOW)
    inventory = build_target_evidence_inventory(synth_request, snapshot)
    ids = inventory.ordered_evidence_item_ids
    evidence_id_by_direction = {
        promotion.evidence_item.evidence_direction: promotion.evidence_item_id
        for promotion in promotions
    }
    response = {"schema_id":"targetintel.grounded_target_synthesis", "schema_version":"1.0.0", "snapshot_id":snapshot.snapshot_id, "inventory_id":inventory.inventory_id, "target_identity":"DEMO_TARGET", "synthesis_purpose":"target_evidence_summary", "sections":list(synth_request.requested_sections), "statements":[{"local_statement_key":"support", "section_identifier":"supported_observations", "statement_text":"Synthetic reviewed evidence reports an association for DEMO_TARGET.", "evidence_item_ids":[evidence_id_by_direction["supports_target"]], "support_relation":"supported", "uncertainty_level":"moderate_uncertainty"}, {"local_statement_key":"contradiction", "section_identifier":"contradictory_evidence", "statement_text":"A synthetic reviewed comparison reports no significant difference for DEMO_TARGET.", "evidence_item_ids":[evidence_id_by_direction["contradicts_target"]], "support_relation":"contradicted", "uncertainty_level":"high_uncertainty"}, {"local_statement_key":"limit", "section_identifier":"limitations", "statement_text":"The synthetic cohort was small and the observation is uncertain.", "evidence_item_ids":[evidence_id_by_direction["limits_target"]], "support_relation":"limitation", "uncertainty_level":"high_uncertainty", "limitation_text":"Synthetic content is not experimentally or clinically validated."}], "evidence_coverage":[{"evidence_item_id":x,"disposition":"cited"} for x in ids], "research_only":True, "non_clinical_use":True}
    llm_request = build_target_synthesis_prompt(synth_request, inventory)
    synthesis_provider = MockProvider({llm_request.request_id:{"status":"success", "structured_output":response}})
    synthesis_result = generate_grounded_target_synthesis(synth_request, snapshot, synthesis_provider)
    if synthesis_result.status != "generated" or synthesis_result.synthesis is None: raise RuntimeError(f"synthesis failed: {synthesis_result.status}")
    synthesis=synthesis_result.synthesis; _write(artifacts / "synthesis.json", synthesis_result.to_dict())
    vault=out / "obsidian-vault"; vault.mkdir(exist_ok=True)
    export_request=ObsidianExportRequest.create(synthesis_id=synthesis.synthesis_id, vault_root=str(vault), relative_note_path="TargetIntel/DEMO_TARGET.md", requesting_actor_id="DEMO_EXPORT_ACTOR", collision_policy="idempotent_same_content", frontmatter_version="1.0.0", renderer_version="1.0.0", tags=["targetintel","synthetic-demo"])
    plan=build_obsidian_export_plan(export_request, synthesis); first=persist_obsidian_export(export_request, plan); second=persist_obsidian_export(export_request, plan)
    note=vault / "TargetIntel" / "DEMO_TARGET.md"
    if first.status not in {"written", "already_current"} or second.status != "already_current" or not note.exists() or sha256(note.read_bytes()).hexdigest() != plan.content_sha256: raise RuntimeError("export verification failed")
    _write(artifacts / "export_receipt.json", {"plan":plan.to_dict(), "first":first.to_dict(), "second":second.to_dict()})
    summary={"research_only":True, "synthetic_content":True, "provider":"MockProvider", "identities":{"extraction_request":extraction.request_identity,"extraction_response":extraction.response_identity,"grounded_candidates":[x.candidate_id for x in extraction.accepted_candidates],"audit":audit.audit_result_id,"review_packet":packet.packet_id,"review_decisions":[x.review_decision_id for x in decisions],"evidence_items":[x.evidence_item_id for x in promotions],"persistence_receipts":[x.persistence_receipt_id for x in receipts],"snapshot":snapshot.snapshot_id,"synthesis_request":synth_request.request_id,"synthesis":synthesis.synthesis_id,"export_plan":plan.plan_id,"export_receipts":[first.receipt_id,second.receipt_id],"note_content_sha256":plan.content_sha256},"artifacts":["artifacts/extraction.json","artifacts/audit.json","artifacts/review.json","artifacts/promotion.json","artifacts/persistence.json","artifacts/snapshot.json","artifacts/synthesis.json","artifacts/export_receipt.json","obsidian-vault/TargetIntel/DEMO_TARGET.md"]}
    _write(out / "demo_summary.json", summary); return summary

def main() -> int:
    parser=argparse.ArgumentParser(description="Run the fully offline synthetic v0.3.0 demo."); parser.add_argument("--output-dir", required=True); args=parser.parse_args()
    try: summary=run_demo(args.output_dir)
    except Exception as exc: print(f"Demo failed: {exc}"); return 1
    print("Synthetic research-only v0.3.0 demo completed."); print("Artifacts:"); print("\n".join(summary["artifacts"])); return 0
if __name__ == "__main__": raise SystemExit(main())
