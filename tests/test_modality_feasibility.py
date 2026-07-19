"""Offline regression coverage for the additive Issue 404 composition API."""

from dataclasses import FrozenInstanceError, replace
from types import MappingProxyType

import pytest

from targetintel.feasibility import FeasibilityObservation, TargetFeasibilityProfile, TargetFeasibilityRequest
from targetintel.feasibility.profiles import FeasibilityDimensionCoverage, TargetFeasibilityProfileBuildResult
from targetintel.feasibility.models import (
    OBSERVATION_FORMAT_VERSION,
    REQUEST_SCHEMA_ID,
    REQUEST_SCHEMA_VERSION,
)
from targetintel.modality import (
    ModalityFeasibilityCompositionError,
    assign_modality_fit,
    compose_modality_with_feasibility,
)


def _profile(observations=()):
    request = TargetFeasibilityRequest(
        REQUEST_SCHEMA_ID, REQUEST_SCHEMA_VERSION, "BRAF", "gene_symbol", "melanoma",
        ("clinical_precedence", "tractability", "doability", "safety"),
        ("antibody", "small_molecule", "protac", "other_clinical"),
        "Open Targets", "24.06", "test",
    )
    return TargetFeasibilityProfile.from_request(request, observations)


def _observation(dimension, modality, factor="factor", value=True, state="observed", value_type="boolean"):
    return FeasibilityObservation(
        OBSERVATION_FORMAT_VERSION, "BRAF", "gene_symbol", dimension, modality,
        factor, value, value_type, state, "Open Targets", "24.06", "record", dimension,
        {"release_verification_state": "verified"}, (),
    )


def test_composition_preserves_legacy_assessment_and_selects_exact_modality():
    legacy = assign_modality_fit("BRAF")
    profile = _profile((_observation("tractability", "small_molecule"), _observation("tractability", "antibody")))
    result = compose_modality_with_feasibility(
        legacy, profile, "small molecule", target_identifier="BRAF", target_identifier_type="gene_symbol"
    )
    assert result.original_assessment is legacy
    assert result.original_assessment == assign_modality_fit("BRAF")
    assert result.requested_modality == "small_molecule"
    small_molecule_id = next(item.observation_id for item in profile.observations if item.modality == "small_molecule")
    assert result.feasibility_annotation.modality_specific_observation_ids["tractability"] == (small_molecule_id,)
    assert result.feasibility_annotation.target_context_observation_ids["tractability"] == ()
    assert result.scores_unmodified and result.rankings_unmodified
    assert result.no_recommendation_generated


def test_annotation_is_immutable_and_deterministic_when_profile_order_changes():
    one = _observation("tractability", "protac", "one")
    two = _observation("tractability", "protac", "two")
    first = compose_modality_with_feasibility(assign_modality_fit("BRAF"), _profile((one, two)), "protac", target_identifier="BRAF", target_identifier_type="gene_symbol")
    second = compose_modality_with_feasibility(assign_modality_fit("BRAF"), _profile((two, one)), "protac", target_identifier="BRAF", target_identifier_type="gene_symbol")
    assert first.feasibility_annotation.annotation_id == second.feasibility_annotation.annotation_id
    assert first.to_dict() == second.to_dict()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        first.feasibility_annotation.requested_modality = "antibody"


@pytest.mark.parametrize("modality", ("IO-combination", "unknown", ""))
def test_unknown_or_ambiguous_legacy_modality_fails_closed(modality):
    with pytest.raises(ModalityFeasibilityCompositionError, match="unsupported_modality"):
        compose_modality_with_feasibility(assign_modality_fit("BRAF"), _profile(), modality, target_identifier="BRAF", target_identifier_type="gene_symbol")


def test_target_and_identifier_mismatches_fail_closed():
    with pytest.raises(ModalityFeasibilityCompositionError, match="target_mismatch"):
        compose_modality_with_feasibility(assign_modality_fit("BRAF"), _profile(), "antibody", target_identifier="NRAS", target_identifier_type="gene_symbol")
    with pytest.raises(ModalityFeasibilityCompositionError, match="identifier_type_mismatch"):
        compose_modality_with_feasibility(assign_modality_fit("BRAF"), _profile(), "antibody", target_identifier="BRAF", target_identifier_type="ensembl_gene_id")


def test_protac_is_not_inferred_from_small_molecule_or_contextual_safety():
    profile = _profile((_observation("tractability", "small_molecule"), _observation("safety", None)))
    result = compose_modality_with_feasibility(assign_modality_fit("BRAF"), profile, "protac", target_identifier="BRAF", target_identifier_type="gene_symbol")
    annotation = result.feasibility_annotation
    assert annotation.modality_specific_observation_ids["tractability"] == ()
    assert annotation.target_context_observation_ids["safety"]
    assert "requested_modality_tractability_not_available" in annotation.limitations
    assert not hasattr(annotation, "safe")


def test_all_dimensions_keep_explicit_modality_evidence_separate_from_target_context():
    observations = []
    for modality in ("antibody", "small_molecule", "protac", "other_clinical"):
        for dimension in ("tractability", "clinical_precedence", "doability", "safety"):
            observations.append(_observation(dimension, modality, factor=f"{dimension}_{modality}"))
    for dimension in ("clinical_precedence", "doability", "safety"):
        observations.append(_observation(dimension, None, factor=f"{dimension}_context"))
    profile = _profile(tuple(observations))

    for modality in ("antibody", "small_molecule", "protac", "other_clinical"):
        annotation = compose_modality_with_feasibility(
            assign_modality_fit("BRAF"), profile, modality,
            target_identifier="BRAF", target_identifier_type="gene_symbol",
        ).feasibility_annotation
        for dimension in ("tractability", "clinical_precedence", "doability", "safety"):
            assert len(annotation.modality_specific_observation_ids[dimension]) == 1
        assert annotation.target_context_observation_ids["tractability"] == ()
        for dimension in ("clinical_precedence", "doability", "safety"):
            assert len(annotation.target_context_observation_ids[dimension]) == 1


def test_missing_and_empty_safety_are_not_reinterpreted_as_safety():
    missing = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), _profile(), "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    ).feasibility_annotation
    empty_profile = _profile((_observation("safety", None, factor="retrieved_empty", value=None, state="not_observed", value_type="null"),))
    empty = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), empty_profile, "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    ).feasibility_annotation
    assert missing.target_context_safety_observation_ids == ()
    assert len(empty.target_context_safety_observation_ids) == 1
    assert not hasattr(empty, "safe")
    assert "safe" not in empty.to_dict()


def test_contradictions_remain_visible_without_selecting_a_winner():
    positive = _observation("tractability", "antibody", factor="same", value=True)
    negative = _observation("tractability", "antibody", factor="same", value=False)
    result = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), _profile((positive, negative)), "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    )
    assert set(result.feasibility_annotation.contradiction_observation_ids) == {
        positive.observation_id, negative.observation_id,
    }
    serialized = result.to_dict()
    assert "best_modality" not in serialized
    assert "recommended_modality" not in serialized
    assert "aggregate_feasibility_score" not in serialized


def test_annotation_and_result_are_deeply_immutable_and_retain_contract_identity():
    observation = _observation("tractability", "antibody", factor="nested")
    profile = _profile((observation,))
    result = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), profile, "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    )
    annotation = result.feasibility_annotation
    assert annotation.feasibility_profile_id == profile.profile_id
    assert annotation.source_release == "24.06"
    assert annotation.target_identifier == "BRAF"
    assert annotation.requested_modality == "antibody"
    assert isinstance(annotation.modality_specific_observation_ids, MappingProxyType)
    with pytest.raises(TypeError):
        annotation.modality_specific_observation_ids["tractability"] = ()
    with pytest.raises(FrozenInstanceError):
        result.requested_modality = "protac"
    assert result.result_id == compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), profile, "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    ).result_id
    assert result.to_dict()["original_assessment_id"] == result.original_assessment_id


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (None, "missing_profile"),
        (object(), "invalid_feasibility_profile"),
        (replace(_profile(), profile_format_version="v0.0.0"), "unsupported_profile_version"),
        (replace(_profile(), target_identifier_type="not_an_identifier"), "invalid_feasibility_profile"),
    ],
)
def test_invalid_profile_inputs_fail_closed(value, error):
    with pytest.raises(ModalityFeasibilityCompositionError, match=error):
        compose_modality_with_feasibility(
            assign_modality_fit("BRAF"), value, "antibody",
            target_identifier="BRAF", target_identifier_type="gene_symbol",
        )


def test_failed_build_result_and_malformed_coverage_fail_closed():
    failed = TargetFeasibilityProfileBuildResult(
        "v0.4.0", "invalid_fetch_result", "request", "fetch", None, None, None, None, (), error_codes=("invalid_fetch_result",),
    )
    with pytest.raises(ModalityFeasibilityCompositionError, match="failed_profile_build_result"):
        compose_modality_with_feasibility(assign_modality_fit("BRAF"), failed, "antibody", target_identifier="BRAF", target_identifier_type="gene_symbol")

    malformed = TargetFeasibilityProfileBuildResult(
        "v0.4.0", "built", "request", "fetch", None, None, None, _profile(),
        (FeasibilityDimensionCoverage("v0.4.0", "NRAS", "gene_symbol", "tractability", "antibody", 0, 0, 0, 0, 0, 0, 0, "not_available"),),
    )
    with pytest.raises(ModalityFeasibilityCompositionError, match="malformed_coverage"):
        compose_modality_with_feasibility(assign_modality_fit("BRAF"), malformed, "antibody", target_identifier="BRAF", target_identifier_type="gene_symbol")


def test_legacy_output_is_canonically_unchanged_by_composition():
    before = assign_modality_fit("BRAF", "tumor-intrinsic driver", "inhibit", "tumor_intrinsic_driver")
    before_dict = dict(before.__dict__)
    profile = _profile()
    profile_dict = profile.to_dict()
    result = compose_modality_with_feasibility(
        before, profile, "small-molecule", target_identifier="BRAF", target_identifier_type="gene_symbol",
    )
    assert dict(before.__dict__) == before_dict
    assert profile.to_dict() == profile_dict
    assert result.original_assessment is before
    assert result.original_assessment.small_molecule_fit == before_dict["small_molecule_fit"]
    assert result.original_assessment.best_modality == before_dict["best_modality"]
