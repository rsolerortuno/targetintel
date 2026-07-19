from dataclasses import FrozenInstanceError

import pytest

from targetintel.feasibility.opentargets_models import (
    OpenTargetsFetchRequest,
    OpenTargetsTargetResolution,
)


def test_request_is_immutable_and_target_universe_is_order_independent() -> None:
    first = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["braf", "CTLA4"]
    )
    second = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["CTLA4", "BRAF"]
    )
    assert first.target_universe == ("BRAF", "CTLA4")
    assert first.request_id == second.request_id
    with pytest.raises(FrozenInstanceError):
        first.page_size = 2


def test_universe_identity_keeps_identifier_types_and_members_distinct() -> None:
    symbols = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["BRAF"]
    )
    ensembl = OpenTargetsFetchRequest(
        query_type="directed_target_universe",
        target_identifier_type="ensembl_gene_id",
        target_universe=["ENSG00000157764"],
    )
    other = OpenTargetsFetchRequest(
        query_type="directed_target_universe", target_universe=["NRAS"]
    )
    assert symbols.target_universe_hash != ensembl.target_universe_hash
    assert symbols.target_universe_hash != other.target_universe_hash


def test_association_scope_is_rejected_until_a_versioned_query_supports_it() -> None:
    with pytest.raises(ValueError, match="association_scope"):
        OpenTargetsFetchRequest(
            query_type="association_ranked", disease_id="MONDO_0005105", association_scope="direct"
        )


@pytest.mark.parametrize("endpoint", ["http://api.platform.opentargets.org/api/v4/graphql", "https://user:pass@api.platform.opentargets.org/api/v4/graphql", "https://localhost/api/v4/graphql"])
def test_untrusted_endpoints_are_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105", endpoint_identity=endpoint)


def test_query_type_is_required() -> None:
    with pytest.raises(TypeError, match="query_type"):
        OpenTargetsFetchRequest(disease_id="MONDO_0005105")


def test_association_ranked_rejects_a_target_universe() -> None:
    with pytest.raises(ValueError, match="rejects target universe"):
        OpenTargetsFetchRequest(
            query_type="association_ranked",
            disease_id="MONDO_0005105",
            target_universe=["BRAF"],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("page_size", 0, "page_size"),
        ("page_size", 1001, "page_size"),
        ("max_pages", 0, "max_pages"),
        ("max_pages", 10001, "max_pages"),
        ("timeout_seconds", 0, "timeout_seconds"),
        ("timeout_seconds", 301, "timeout_seconds"),
    ],
)
def test_request_rejects_out_of_bounds_pagination_and_timeout(
    field: str, value: int, message: str
) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=message):
        OpenTargetsFetchRequest(
            query_type="association_ranked", disease_id="MONDO_0005105", **kwargs
        )


@pytest.mark.parametrize("forbidden_field", ["credentials", "reasoning"])
def test_request_rejects_credential_and_hidden_reasoning_fields(
    forbidden_field: str,
) -> None:
    with pytest.raises(TypeError, match=forbidden_field):
        OpenTargetsFetchRequest(
            query_type="association_ranked",
            disease_id="MONDO_0005105",
            **{forbidden_field: {"nested": {"credential": "not-accepted"}}},
        )


def test_invalid_ensembl_identifier_cannot_be_resolved() -> None:
    with pytest.raises(ValueError, match="invalid Ensembl identifier"):
        OpenTargetsTargetResolution(
            requested_identifier="ENSG123",
            requested_identifier_type="ensembl_gene_id",
            status="resolved_exact",
            ensembl_gene_id="ENSG123",
        )
