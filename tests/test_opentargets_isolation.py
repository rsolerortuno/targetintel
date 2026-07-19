import inspect

import pandas as pd

from targetintel.feasibility import opentargets_ingestion, opentargets_models
from targetintel.feasibility.opentargets_ingestion import fetch_opentargets
from targetintel.feasibility.opentargets_models import OpenTargetsFetchRequest, OpenTargetsTransportResponse
from targetintel.feasibility.opentargets_transport import FakeOpenTargetsTransport
from targetintel.intent_ranking import add_intent_ranks
from targetintel.role_classifier import classify_gene


def test_ingestion_boundary_does_not_import_or_construct_interpretation_layers() -> None:
    source = inspect.getsource(opentargets_ingestion) + inspect.getsource(opentargets_models)
    forbidden = (
        "targetintel.scoring", "targetintel.intent_ranking", "targetintel.role_classifier",
        "targetintel.modality", "targetintel.llm", "GroundedTargetSynthesis",
        "TargetFeasibilityProfile",
    )
    assert not any(name in source for name in forbidden)


def test_ingestion_does_not_invoke_pipeline_layers_or_mutate_baseline_outputs(monkeypatch) -> None:
    """Fixture ingestion is runtime-isolated from the deterministic pipeline."""
    import targetintel.intent_ranking as intent_ranking
    import targetintel.llm.execution as llm_execution
    import targetintel.modality as modality
    import targetintel.role_classifier as role_classifier
    import targetintel.scoring as scoring
    from targetintel.feasibility import models as feasibility_models
    from targetintel.llm import synthesis_models

    features = pd.DataFrame({
        "target_symbol": ["BRAF", "LAG3"], "opentargets_score": [0.9, 0.8],
        "antibody_io_final_score": [0.1, 0.9], "biomarker_final_score": [0.2, 0.3],
        "small_molecule_final_score": [0.9, 0.1],
    })
    ranked = add_intent_ranks(features)
    roles = [classify_gene("BRAF"), classify_gene("LAG3")]
    before = (features.to_json(orient="split", index=False), ranked.to_json(orient="split", index=False), repr(roles))

    def forbidden(*args, **kwargs):
        raise AssertionError("Open Targets ingestion invoked an isolated system")

    monkeypatch.setattr(scoring, "score_all_profiles", forbidden)
    monkeypatch.setattr(intent_ranking, "add_intent_ranks", forbidden)
    monkeypatch.setattr(role_classifier, "classify_gene", forbidden)
    monkeypatch.setattr(modality, "assign_modality_fit", forbidden)
    monkeypatch.setattr(llm_execution, "execute_request", forbidden)
    monkeypatch.setattr(feasibility_models, "TargetFeasibilityProfile", forbidden)
    monkeypatch.setattr(synthesis_models, "GroundedTargetSynthesis", forbidden)

    request = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["BRAF"])
    transport = FakeOpenTargetsTransport({
        "resolve_BRAF": OpenTargetsTransportResponse("resolve_BRAF", 200, {"data": {"search": {"hits": [
            {"id": "ENSG00000157764", "entity": "TARGET"}
        ]}}}),
        "target_candidate_BRAF_ENSG00000157764": OpenTargetsTransportResponse(
            "target_candidate_BRAF_ENSG00000157764", 200,
            {"data": {"target": {"id": "ENSG00000157764", "approvedSymbol": "BRAF"}}},
        ),
    })
    result = fetch_opentargets(request, transport)

    assert result.status == "completed"
    assert before == (features.to_json(orient="split", index=False), ranked.to_json(orient="split", index=False), repr(roles))
