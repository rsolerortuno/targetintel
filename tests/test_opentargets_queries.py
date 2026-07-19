from targetintel.feasibility.opentargets_models import OpenTargetsFetchRequest
from targetintel.feasibility.opentargets_queries import build_execution_query_plan, build_query_plan


def test_symbol_planning_stage_declares_only_the_source_independent_resolution() -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["BRAF"]
    )
    plan = build_query_plan(request)
    assert [operation["operation_id"] for operation in plan.operations] == ["resolve_BRAF"]
    assert plan.expected_operation_count == 1
    assert plan.plan_id == build_query_plan(request).plan_id


def test_execution_plan_records_candidate_operations_exactly() -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["BRAF"]
    )
    plan = build_execution_query_plan(request, [
        {"operation_id": "resolve_BRAF", "document": "resolution", "variables": {"query": "BRAF"}},
        {"operation_id": "target_candidate_BRAF_ENSG00000157764", "document": "target", "variables": {"ensemblId": "ENSG00000157764"}},
    ])
    assert plan.expected_operation_count == 2
    assert [operation["operation_id"] for operation in plan.operations] == [
        "resolve_BRAF", "target_candidate_BRAF_ENSG00000157764"
    ]
