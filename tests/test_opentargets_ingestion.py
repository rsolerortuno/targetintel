"""Offline regression tests for the v0.4.0 source-ingestion boundary."""
from pathlib import Path
import pytest
from targetintel.feasibility.opentargets_cache import OpenTargetsCache, cache_identity
from targetintel.feasibility.opentargets_ingestion import fetch_opentargets
from targetintel.feasibility.opentargets_models import OpenTargetsFetchRequest, OpenTargetsTransportResponse
from targetintel.feasibility.opentargets_queries import build_query_plan
from targetintel.feasibility.opentargets_transport import FakeOpenTargetsTransport

def test_directed_fetch_keeps_low_ranked_and_unresolved_targets() -> None:
    request = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["LOW", "MISS"], cache_policy="disabled")
    transport = FakeOpenTargetsTransport({
        "resolve_LOW": OpenTargetsTransportResponse("resolve_LOW", 200, {"data":{"search":{"hits":[{"id":"ENSG00000000001","entity":"TARGET","name":"LOW"}]}}}),
        "resolve_MISS": OpenTargetsTransportResponse("resolve_MISS", 200, {"data":{"search":{"hits":[]}}}),
        "target_candidate_LOW_ENSG00000000001": OpenTargetsTransportResponse("target_candidate_LOW_ENSG00000000001", 200, {"data":{"target":{"id":"ENSG00000000001","approvedSymbol":"LOW","safetyLiabilities":[]}}}),
    })
    result = fetch_opentargets(request, transport)
    assert result.status == "completed_with_gaps"
    assert result.coverage_report.terminal_categories["resolved_and_retrieved"] == ("LOW",)
    assert result.coverage_report.terminal_categories["unresolved"] == ("MISS",)
    assert result.records[0].source_fields["safetyLiabilities"] == ()

def test_request_identity_is_order_independent_and_cache_is_explicit(tmp_path: Path) -> None:
    first = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["BRAF", "CTLA4"])
    second = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["CTLA4", "BRAF"])
    assert first.request_id == second.request_id
    assert cache_identity(first, build_query_plan(first)) == cache_identity(second, build_query_plan(second))
    cache = OpenTargetsCache(tmp_path)
    cache.write("entry", {"record": "value"})
    assert cache.read("entry") == {"record": "value"}

def test_invalid_request_modes_fail_closed() -> None:
    with pytest.raises(ValueError): OpenTargetsFetchRequest(query_type="unknown", disease_id="MONDO_0005105")
    with pytest.raises(ValueError): OpenTargetsFetchRequest(query_type="association_ranked")
    with pytest.raises(ValueError): OpenTargetsFetchRequest(query_type="directed_target_universe")


def test_invalid_ensembl_target_has_visible_invalid_terminal_outcome() -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe",
        target_identifier_type="ensembl_gene_id",
        target_universe=["ENSG123"],
    )

    result = fetch_opentargets(request, FakeOpenTargetsTransport({}))

    assert result.resolutions[0].status == "invalid_identifier"
    assert result.coverage_report.terminal_categories["invalid"] == ("ENSG123",)


def test_symbol_is_resolved_only_after_exact_approved_symbol_validation() -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["BRAF"]
    )
    transport = FakeOpenTargetsTransport({
        "resolve_BRAF": OpenTargetsTransportResponse("resolve_BRAF", 200, {"data": {"search": {"hits": [
            {"id": "ENSG00000157764", "entity": "TARGET", "name": "not-a-contract"}
        ]}}}),
        "target_candidate_BRAF_ENSG00000157764": OpenTargetsTransportResponse(
            "target_candidate_BRAF_ENSG00000157764", 200,
            {"data": {"target": {"id": "ENSG00000157764", "approvedSymbol": "BRAF"}}},
        ),
    })
    result = fetch_opentargets(request, transport)
    assert result.resolutions[0].status == "resolved_exact"
    assert result.records[0].approved_symbol == "BRAF"
    assert [call[0] for call in transport.calls] == [
        operation["operation_id"] for operation in result.query_plan.operations
    ]
    assert result.query_plan.expected_operation_count == len(transport.calls)


def test_symbol_resolution_fails_closed_when_any_candidate_validation_fails() -> None:
    """A surviving exact match cannot hide an unvalidated candidate."""
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["DUPLICATE"]
    )
    transport = FakeOpenTargetsTransport({
        "resolve_DUPLICATE": OpenTargetsTransportResponse(
            "resolve_DUPLICATE", 200, {"data": {"search": {"hits": [
                {"id": "ENSG00000111111", "entity": "TARGET"},
                {"id": "ENSG00000222222", "entity": "TARGET"},
            ]}}},
        ),
        "target_candidate_DUPLICATE_ENSG00000111111": OpenTargetsTransportResponse(
            "target_candidate_DUPLICATE_ENSG00000111111", 200,
            {"data": {"target": {"id": "ENSG00000111111", "approvedSymbol": "DUPLICATE"}}},
        ),
        "target_candidate_DUPLICATE_ENSG00000222222": RuntimeError("unavailable"),
    })

    result = fetch_opentargets(request, transport)

    assert result.status == "completed_with_gaps"
    assert result.resolutions[0].status == "retrieval_failed"
    assert result.coverage_report.terminal_categories["retrieval_failed"] == ("DUPLICATE",)
    assert result.records == ()
    assert [call[0] for call in transport.calls] == [
        operation["operation_id"] for operation in result.query_plan.operations
    ]
    assert result.query_plan.expected_operation_count == len(transport.calls)


def test_duplicate_association_target_fails_closed() -> None:
    request = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105", max_pages=2)
    row = {"score": 0.1, "target": {"id": "ENSG00000157764", "approvedSymbol": "BRAF"}}
    page = lambda operation: OpenTargetsTransportResponse(operation, 200, {"data": {"disease": {
        "id": "MONDO_0005105", "associatedTargets": {"count": 2, "rows": [row]}
    }}})
    result = fetch_opentargets(request, FakeOpenTargetsTransport({
        "association_page_0": page("association_page_0"),
        "association_page_1": page("association_page_1"),
    }))
    assert result.status == "response_error"
    assert result.error_codes == ("duplicate_source_record",)


def test_cache_manifest_retains_audit_identities(tmp_path: Path) -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["MISS"], cache_policy="read_through"
    )
    cache = OpenTargetsCache(tmp_path)
    transport = FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse("resolve_MISS", 200, {"data": {"search": {"hits": []}}})
    })
    result = fetch_opentargets(request, transport, cache)
    manifest = cache.read(result.cache_identity)
    assert manifest["query_plan_id"] == result.query_plan.plan_id
    assert manifest["request_identity"] == request.request_id
    assert manifest["target_universe_hash"] == request.target_universe_hash
    assert manifest["result_id"] == result.result_id


def test_valid_cache_hit_avoids_transport_and_preserves_request_identity(tmp_path: Path) -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["MISS"], cache_policy="read_through",
        requested_source_release="24.01",
    )
    cache = OpenTargetsCache(tmp_path)
    first = fetch_opentargets(request, FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse("resolve_MISS", 200, {"data": {"search": {"hits": []}}}, source_release="24.01")
    }), cache)
    second_transport = FakeOpenTargetsTransport({})
    second = fetch_opentargets(request, second_transport, cache)
    assert first.request.request_id == second.request.request_id == request.request_id
    assert second.cache_origin == "valid_cache_hit"
    assert second_transport.calls == []


def test_unpinned_observed_release_cache_entry_is_found_without_guessing_state(tmp_path: Path) -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["MISS"], cache_policy="read_through"
    )
    cache = OpenTargetsCache(tmp_path)
    first = fetch_opentargets(request, FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse(
            "resolve_MISS", 200, {"data": {"search": {"hits": []}}}, source_release="24.01"
        )
    }), cache)
    second_transport = FakeOpenTargetsTransport({})
    second = fetch_opentargets(request, second_transport, cache)

    assert first.release_verification_state == "declared_unverified"
    assert second.cache_origin == "valid_cache_hit"
    assert second_transport.calls == []


def test_pinned_unreported_release_cache_entry_is_found_without_guessing_state(tmp_path: Path) -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["MISS"], cache_policy="read_through",
        requested_source_release="24.01",
    )
    cache = OpenTargetsCache(tmp_path)
    first = fetch_opentargets(request, FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse("resolve_MISS", 200, {"data": {"search": {"hits": []}}})
    }), cache)
    second_transport = FakeOpenTargetsTransport({})
    second = fetch_opentargets(request, second_transport, cache)

    assert first.release_verification_state == "declared_unverified"
    assert second.cache_origin == "valid_cache_hit"
    assert second_transport.calls == []


def test_observed_source_release_changes_physical_cache_identity(tmp_path: Path) -> None:
    request = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["MISS"], cache_policy="refresh"
    )
    cache = OpenTargetsCache(tmp_path)
    first = fetch_opentargets(request, FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse(
            "resolve_MISS", 200, {"data": {"search": {"hits": []}}}, source_release="24.01"
        )
    }), cache)
    second_transport = FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse(
            "resolve_MISS", 200, {"data": {"search": {"hits": []}}}, source_release="24.02"
        )
    })
    second = fetch_opentargets(request, second_transport, cache)

    assert first.cache_identity != second.cache_identity
    assert second_transport.calls
    assert (tmp_path / f"{first.cache_identity}.json").exists()
    assert (tmp_path / f"{second.cache_identity}.json").exists()


def test_required_release_mismatch_fails_closed() -> None:
    request = OpenTargetsFetchRequest(
        query_type="association_ranked", disease_id="MONDO_0005105", requested_source_release="24.01",
        release_verification_required=True,
    )
    response = OpenTargetsTransportResponse("association_page_0", 200, {
        "data": {"disease": {"id": "MONDO_0005105", "associatedTargets": {"count": 0, "rows": []}}}
    }, source_release="24.02")
    result = fetch_opentargets(request, FakeOpenTargetsTransport({"association_page_0": response}))
    assert result.status == "release_mismatch"
    assert result.release_verification_state == "mismatch"


def test_association_empty_page_completes_and_page_limit_is_truncated() -> None:
    complete_request = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105", max_pages=2)
    empty = OpenTargetsTransportResponse("association_page_0", 200, {
        "data": {"disease": {"id": "MONDO_0005105", "associatedTargets": {"count": 4, "rows": []}}}
    })
    complete = fetch_opentargets(complete_request, FakeOpenTargetsTransport({"association_page_0": empty}))
    assert complete.status == "completed"

    row = {"score": 0.1, "target": {"id": "ENSG00000157764", "approvedSymbol": "BRAF"}}
    pages = {
        f"association_page_{index}": OpenTargetsTransportResponse(f"association_page_{index}", 200, {
            "data": {"disease": {"id": "MONDO_0005105", "associatedTargets": {"count": 9, "rows": [
                {**row, "target": {**row["target"], "id": f"ENSG0000015776{index}"}}
            ]}}}
        }) for index in range(2)
    }
    truncated = fetch_opentargets(complete_request, FakeOpenTargetsTransport(pages))
    assert truncated.status == "truncated"
    assert truncated.coverage_report.truncated is True


def test_association_transport_error_is_not_an_end_of_results() -> None:
    request = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105")
    result = fetch_opentargets(request, FakeOpenTargetsTransport({
        "association_page_0": RuntimeError("network unavailable")
    }))
    assert result.status == "transport_error"


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"data": {"disease": {"id": "MONDO_0005105", "associatedTargets": None}}}, "malformed_associated_targets"),
        ({"data": {"search": None}}, "malformed_resolution_search"),
    ],
)
def test_null_graphql_subfields_fail_closed_without_crashing(payload: dict, error_code: str) -> None:
    if "disease" in payload["data"]:
        request = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105")
        transport = FakeOpenTargetsTransport({
            "association_page_0": OpenTargetsTransportResponse("association_page_0", 200, payload)
        })
        result = fetch_opentargets(request, transport)
        assert result.status == "response_error"
        assert result.error_codes == (error_code,)
    else:
        request = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["BRAF"])
        transport = FakeOpenTargetsTransport({
            "resolve_BRAF": OpenTargetsTransportResponse("resolve_BRAF", 200, payload)
        })
        result = fetch_opentargets(request, transport)
        assert result.status == "completed_with_gaps"
        assert result.coverage_report.terminal_categories["retrieval_failed"] == ("BRAF",)
        assert result.resolutions[0].error_codes == (error_code,)


def test_result_retains_observed_release_without_records() -> None:
    request = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["MISS"])
    result = fetch_opentargets(request, FakeOpenTargetsTransport({
        "resolve_MISS": OpenTargetsTransportResponse(
            "resolve_MISS", 200, {"data": {"search": {"hits": []}}}, source_release="24.01"
        )
    }))
    assert result.records == ()
    assert result.observed_source_release == "24.01"


def test_coverage_fraction_is_zero_safe_and_not_confidence() -> None:
    request = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105")
    result = fetch_opentargets(request, FakeOpenTargetsTransport({
        "association_page_0": OpenTargetsTransportResponse(
            "association_page_0", 200,
            {"data": {"disease": {"id": "MONDO_0005105", "associatedTargets": {"count": 0, "rows": []}}}},
        )
    }))
    assert result.coverage_report.coverage_ratio == (0, 0)
    assert result.coverage_report.coverage_fraction == "0/0"
    assert result.coverage_report.coverage_is_scientific_confidence is False
