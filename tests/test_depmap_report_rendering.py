"""Synthetic tests for read-only DepMap report presentation."""
from __future__ import annotations

import pandas as pd
import pytest

from targetintel.functional_dependency.presentation import (
    DependencyPresentationError,
    render_dependency_html,
    render_dependency_markdown,
)
from targetintel.hypothesis_cards import make_target_card, write_top_target_cards
from targetintel.html_reports import make_target_html_report, write_top_html_reports
from test_depmap_report_contract import available, unavailable
from test_feasibility_presentation import _annotation, _observation


def _row(symbol: str = "BRAF") -> pd.Series:
    return pd.Series({"target_symbol": symbol, "target_name": "B-Raf"})


def _ranked() -> pd.DataFrame:
    return pd.DataFrame([
        {**_row("BRAF").to_dict(), "antibody_io_rank": 1, "biomarker_rank": 1, "small_molecule_rank": 1},
        {**_row("NRAS").to_dict(), "antibody_io_rank": 2, "biomarker_rank": 2, "small_molecule_rank": 2},
    ])


def test_markdown_is_deterministic_and_retains_required_available_fields() -> None:
    evidence = available()
    rendered = render_dependency_markdown(evidence)
    assert rendered == render_dependency_markdown(evidence)
    for text in (
        "## Functional dependency — DepMap Public 26Q1", "### Coverage",
        "### Dependency profile", "### Integration", "### Release provenance",
        "### Limitations", "**Gene-effect summary:** {\"measured_model_count\":4,\"median\":0.0}",
        "**Dependency-probability summary:** {\"measured_model_count\":4,\"median\":null}",
        "**Context-versus-reference comparison:**", "**Selectivity:**",
        "**Dependency interpretation state:** valid", "**Baseline rank:** 7",
        "**Dependency-aware candidate rank:** 5", "**Rank delta:** -2",
        "dependency-aware candidate rank minus baseline rank", "Baseline preserved:** yes",
        "Production activation enabled:** disabled", "Approved authorization emitted:** not emitted",
        "Human review required:** required", evidence.evidence_id, "manifest",
        "configuration", "closure", "melanoma_anti_pd1:v1", "BRAF:673",
        "release_summary.json", "candidate_overlay.tsv",
    ):
        assert text in rendered
    assert "- **Gene-effect summary:**" in rendered
    assert "not reported" in rendered
    assert "0.0" in rendered
    assert "score" not in rendered.lower()
    assert "recommend" not in rendered.lower()


def test_unavailable_profile_is_calibrated_and_distinct_from_missing() -> None:
    rendered = render_dependency_markdown(unavailable())
    assert "**Profile available:** no" in rendered
    assert "**Total model count:** not available" in rendered
    assert "No validated DepMap profile is available" in rendered
    assert "No dependency conclusion is drawn." in rendered
    assert "Gene-effect summary" not in rendered


def test_html_is_deterministic_semantic_and_escapes_values() -> None:
    evidence = available(
        gene_effect={"text": "<tag>&\"'", "nested": {"x": 0}},
        provenance={"source_artifact_names": ["release_summary.json"]},
    )
    rendered = render_dependency_html(evidence)
    assert rendered == render_dependency_html(evidence)
    assert '<section class="card functional-dependency">' in rendered
    for heading in ("Coverage", "Dependency profile", "Integration", "Release provenance", "Limitations"):
        assert f"<h3>{heading}</h3>" in rendered
    assert "&amp;lt;tag&amp;gt;&amp;\\\\&quot;&#x27;" in rendered


def test_cards_and_html_attach_only_matching_evidence_and_preserve_legacy() -> None:
    row = _row()
    card, html = make_target_card(row), make_target_html_report(row)
    assert make_target_card(row, dependency_evidence=None) == card
    assert make_target_html_report(row, dependency_evidence=None) == html
    decorated_card = make_target_card(row, dependency_evidence=available())
    decorated_html = make_target_html_report(row, dependency_evidence=available())
    assert decorated_card.startswith(card.rstrip() + "\n")
    assert "Functional dependency — DepMap Public 26Q1" in decorated_card
    assert '<section class="card functional-dependency">' in decorated_html
    with pytest.raises(DependencyPresentationError, match="target_mismatch"):
        make_target_card(row, dependency_evidence=available(gene_symbol="NRAS"))
    with pytest.raises(DependencyPresentationError, match="target_mismatch"):
        make_target_html_report(row, dependency_evidence=available(gene_symbol="NRAS"))


def test_batch_writers_route_evidence_without_mutating_mapping(tmp_path) -> None:
    evidence_by_symbol = {"BRAF": available()}
    original = dict(evidence_by_symbol)
    cards = write_top_target_cards(_ranked(), tmp_path / "cards", top_n_per_mode=2,
                                   dependency_evidence_by_symbol=evidence_by_symbol)
    reports = write_top_html_reports(_ranked(), tmp_path / "html", top_n_per_mode=2,
                                     dependency_evidence_by_symbol=evidence_by_symbol)
    assert evidence_by_symbol == original
    assert "Functional dependency" in cards[0].read_text(encoding="utf-8")
    assert "Functional dependency" not in cards[1].read_text(encoding="utf-8")
    assert "Functional dependency" in (tmp_path / "html" / "BRAF.html").read_text(encoding="utf-8")
    assert "Functional dependency" not in (tmp_path / "html" / "NRAS.html").read_text(encoding="utf-8")
    assert reports[0].name == "index.html"


def test_renderer_rejects_non_contract_value() -> None:
    with pytest.raises(DependencyPresentationError, match="invalid_dependency_report_evidence"):
        render_dependency_markdown(object())  # type: ignore[arg-type]


def test_dependency_section_follows_feasibility_without_changing_card_content() -> None:
    card = make_target_card(
        _row(), dependency_evidence=available(),
        feasibility_annotations=(_annotation("antibody", (_observation("tractability", "antibody"),)),),
        feasibility_target_identifier_type="gene_symbol",
    )
    assert card.index("## Target feasibility — research-only") < card.index("## Functional dependency")


def test_pure_renderer_does_not_use_file_or_network_boundaries(monkeypatch) -> None:
    import builtins
    import socket

    def forbidden(*_args, **_kwargs):
        raise AssertionError("presentation attempted external access")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert "Functional dependency" in render_dependency_markdown(available())
