"""Pure, read-only presentation of portable DepMap dependency evidence.

This module consumes only :class:`DependencyReportEvidence`.  It does not load
snapshots, profiles, matrices, or upstream workflow state.
"""
from __future__ import annotations

from html import escape as html_escape
import json
import math
import re
from typing import Any, Mapping

from .report_contract import DependencyReportEvidence


class DependencyPresentationError(ValueError):
    """Raised when a report-evidence boundary is unsuitable for rendering."""


_FIXED_LIMITATIONS = (
    "DepMap cell-line dependency is not clinical anti-PD-1 response evidence.",
    "Absence of tumor-cell dependency does not invalidate an immune target.",
    "Broad dependency may reflect general essentiality.",
    "Cell lines do not reproduce the complete tumor microenvironment.",
    "Candidate activation requires explicit human review.",
)


def _evidence(value: Any) -> DependencyReportEvidence:
    if not isinstance(value, DependencyReportEvidence):
        raise DependencyPresentationError("invalid_dependency_report_evidence")
    if (value.baseline_preserved is not True
            or value.production_activation_enabled is not False
            or value.approved_authorization_emitted is not False
            or value.human_review_required is not True):
        raise DependencyPresentationError("invalid_dependency_activation_state")
    return value


def _release_name(identifier: str) -> str:
    """Convert a machine identifier to the deliberately small display form."""
    return identifier.replace("_", " ")


def _markdown_text(value: Any) -> str:
    """Keep untrusted text to one Markdown line and out of Markdown syntax."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    return (text.replace("\\", "\\\\").replace("`", "\\`")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _json(value: Any) -> str:
    """Produce a stable representation of contract-approved structured values."""
    try:
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DependencyPresentationError("unsupported_structured_value") from exc


def _plain(value: Any) -> Any:
    """Convert immutable contract containers to JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _number(value: int | float | None, *, unavailable: bool = False) -> str:
    if value is None:
        return "not available" if unavailable else "not reported"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DependencyPresentationError("unsupported_structured_value")
    if isinstance(value, float) and not math.isfinite(value):
        raise DependencyPresentationError("unsupported_structured_value")
    return _json(value)


def _text(value: str | None, *, unavailable: bool = False) -> str:
    if value is None:
        return "not available" if unavailable else "not reported"
    return _markdown_text(value)


def _markdown_mapping(value: Mapping[str, Any] | None) -> str:
    return "not reported" if value is None else _markdown_text(_json(value))


def _limitations(evidence: DependencyReportEvidence) -> tuple[str, ...]:
    retained = tuple(sorted(evidence.limitations))
    return retained + tuple(item for item in _FIXED_LIMITATIONS if item not in retained)


def render_dependency_markdown(evidence: DependencyReportEvidence) -> str:
    """Render deterministic Markdown without modifying or deriving evidence."""
    evidence = _evidence(evidence)
    unavailable = not evidence.profile_available
    title = _release_name(evidence.release_identifier)
    lines = [
        f"## Functional dependency — {_markdown_text(title)}", "",
        "### Coverage", "",
        f"- **Profile available:** {'yes' if evidence.profile_available else 'no'}",
        f"- **Coverage status:** {_markdown_text(evidence.coverage_status)}",
        f"- **Total model count:** {_number(evidence.model_count, unavailable=unavailable)}",
        f"- **Context model count:** {_number(evidence.context_model_count, unavailable=unavailable)}",
        f"- **Reference model count:** {_number(evidence.reference_model_count, unavailable=unavailable)}",
        f"- **Available context observations:** {_number(evidence.available_context_observations, unavailable=unavailable)}",
        f"- **Available reference observations:** {_number(evidence.available_reference_observations, unavailable=unavailable)}",
        f"- **Coverage fraction:** {_number(evidence.coverage_fraction, unavailable=unavailable)}",
        f"- **Missing-value state:** {_text(evidence.missing_value_state, unavailable=unavailable)}",
        f"- **Unavailable reason:** {_text(evidence.unavailable_reason, unavailable=unavailable)}",
        "", "### Dependency profile", "",
    ]
    if unavailable:
        lines.extend([
            "No validated DepMap profile is available for this target in the portable evidence bundle. "
            "No dependency conclusion is drawn.",
        ])
    else:
        lines.extend([
            f"- **Gene-effect summary:** {_markdown_mapping(evidence.gene_effect)}",
            f"- **Dependency-probability summary:** {_markdown_mapping(evidence.dependency_probability)}",
            f"- **Context-versus-reference comparison:** {_markdown_mapping(evidence.context_reference_comparison)}",
            f"- **Selectivity:** {_markdown_mapping(evidence.selectivity)}",
            f"- **Dependency interpretation state:** {_text(evidence.dependency_interpretation_state)}",
        ])
    lines.extend([
        "", "### Integration", "",
        f"- **Baseline rank:** {_number(evidence.baseline_rank)}",
        f"- **Dependency-aware candidate rank:** {_number(evidence.dependency_aware_candidate_rank)}",
        f"- **Rank delta:** {_number(evidence.rank_delta)}",
        "- **Rank-delta convention:** dependency-aware candidate rank minus baseline rank.",
        "- **Negative rank delta:** movement toward a lower numerical rank.",
        f"- **Integration state:** {_text(evidence.integration_state)}",
        "- **Baseline preserved:** yes",
        "- **Production activation enabled:** disabled",
        "- **Approved authorization emitted:** not emitted",
        f"- **Candidate activation readiness:** {_text(evidence.candidate_activation_readiness)}",
        "- **Human review required:** required",
        "", "### Release provenance", "",
        f"- **Evidence ID:** `{_markdown_text(evidence.evidence_id)}`",
        f"- **Release identifier:** `{_markdown_text(evidence.release_identifier)}`",
        f"- **Release manifest ID:** `{_markdown_text(evidence.release_manifest_id)}`",
        f"- **Configuration ID:** `{_markdown_text(evidence.configuration_id)}`",
        f"- **Scientific closure identity:** `{_markdown_text(evidence.scientific_closure_identity)}`",
        f"- **Context identity:** `{_markdown_text(evidence.context_identity)}`",
        f"- **Canonical gene identity:** `{_text(evidence.canonical_gene_identity, unavailable=unavailable)}`",
        f"- **Contract format version:** `{_markdown_text(evidence.format_version)}`",
        "- **Portable source artifacts:** " + ", ".join(
            f"`{_markdown_text(name)}`" for name in evidence.provenance["source_artifact_names"]
        ),
        "", "### Limitations", "",
    ])
    lines.extend(f"- {_markdown_text(item)}" for item in _limitations(evidence))
    return "\n".join(lines) + "\n"


def render_dependency_html(evidence: DependencyReportEvidence) -> str:
    """Render the same escaped content in a semantic dedicated HTML section."""
    markdown = render_dependency_markdown(evidence)
    _, body = markdown.split("\n\n", 1)
    sections = re.split(r"\n(?=### )", body.rstrip("\n"))
    rendered: list[str] = [
        '<section class="card functional-dependency">',
        f'<h2>Functional dependency — {html_escape(_release_name(evidence.release_identifier), quote=True)}</h2>',
    ]
    for section in sections:
        heading, content = section.split("\n", 1)
        if not heading.startswith("### "):
            raise DependencyPresentationError("invalid_dependency_presentation_structure")
        rendered.append(f"<h3>{html_escape(heading[4:], quote=True)}</h3>")
        rendered.append(f'<pre class="note">{html_escape(content, quote=True)}</pre>')
    rendered.append("</section>")
    return "\n".join(rendered) + "\n"
