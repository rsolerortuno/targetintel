"""Offline isolation regressions for profile-aware modality decoration."""

import ast
import builtins
import socket
import subprocess
from pathlib import Path

import pytest

from targetintel.feasibility import FeasibilityObservation, TargetFeasibilityProfile, TargetFeasibilityRequest
from targetintel.feasibility.models import OBSERVATION_FORMAT_VERSION, REQUEST_SCHEMA_ID, REQUEST_SCHEMA_VERSION
from targetintel.modality import assign_modality_fit, compose_modality_with_feasibility


def _profile():
    request = TargetFeasibilityRequest(
        REQUEST_SCHEMA_ID, REQUEST_SCHEMA_VERSION, "BRAF", "gene_symbol", "melanoma",
        ("tractability",), ("antibody",), "Open Targets", "24.06", "test",
    )
    observation = FeasibilityObservation(
        OBSERVATION_FORMAT_VERSION, "BRAF", "gene_symbol", "tractability", "antibody", "factor",
        True, "boolean", "observed", "Open Targets", "24.06", "record", "tractability", {}, (),
    )
    return TargetFeasibilityProfile.from_request(request, (observation,))


def test_composition_has_no_forbidden_runtime_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden side effect invoked")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), _profile(), "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    )
    assert result.original_assessment_unmodified
    assert result.scores_unmodified
    assert result.rankings_unmodified


def test_modality_module_import_boundary_excludes_forbidden_implementations():
    source = Path(__file__).parents[1] / "targetintel" / "modality.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {
        "scoring", "ranking", "role_classifier", "llm", "opentargets_ingestion",
        "opentargets_transport", "cache", "evidence", "reports", "subprocess", "importlib",
    }
    assert not any(part in name for name in imported for part in forbidden)


def test_composition_does_not_construct_or_rebuild_feasibility_contracts(monkeypatch):
    import targetintel.feasibility.profiles as profiles

    def forbidden(*args, **kwargs):
        raise AssertionError("profile construction invoked")

    monkeypatch.setattr(profiles, "build_target_feasibility_profile", forbidden)
    result = compose_modality_with_feasibility(
        assign_modality_fit("BRAF"), _profile(), "antibody",
        target_identifier="BRAF", target_identifier_type="gene_symbol",
    )
    assert result.feasibility_annotation.feasibility_profile_id == _profile().profile_id
