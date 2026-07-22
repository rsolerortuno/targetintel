"""
HTML report generation for TargetIntel-IO.

This module converts ranked TargetIntel-IO rows into styled standalone HTML
target reports and an index page.

The reports are intended for transparent portfolio-style target triage summaries.
They are not clinical recommendations.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from targetintel.hypothesis_cards import recommend_next_experiment
from targetintel.evidence.reporting import EvidenceCard
from targetintel.feasibility.presentation import (
    make_feasibility_report_section,
    render_feasibility_html,
)
from targetintel.functional_dependency.presentation import (
    DependencyPresentationError,
    render_dependency_html,
)
from targetintel.functional_dependency.report_contract import DependencyReportEvidence


DEFAULT_HTML_REPORT_DIR = Path("results/html_reports")


def _safe_str(value: Any) -> str:
    """Convert missing values into clean display strings."""
    if value is None:
        return "not available"

    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    value = str(value).strip()

    if not value:
        return "not available"

    return value


def _safe_float(value: Any, digits: int = 3) -> str:
    """Format numeric values safely."""
    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "not available"


def _safe_int(value: Any) -> str:
    """Format integer-like values safely."""
    try:
        if pd.isna(value):
            return "not available"
    except TypeError:
        pass

    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "not available"


def _safe_score(value: Any) -> float:
    """Return numeric score in [0, 1] if possible, otherwise 0."""
    try:
        if pd.isna(value):
            return 0.0
    except TypeError:
        pass

    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0

    return max(0.0, min(1.0, score))


def _split_pipe_text(value: Any) -> list[str]:
    """Split pipe-separated evidence strings."""
    text = _safe_str(value)

    if text == "not available":
        return []

    return [item.strip() for item in text.split("|") if item.strip()]


def _priority_class(priority: Any) -> str:
    """Map priority labels to CSS classes."""
    priority = _safe_str(priority).lower()

    if priority == "high":
        return "badge-high"
    if priority == "medium":
        return "badge-medium"
    if priority == "low":
        return "badge-low"

    return "badge-none"


def _format_bullets(items: list[str]) -> str:
    """Format evidence items as HTML bullets."""
    if not items:
        return "<li>not available</li>"

    return "\n".join(f"<li>{escape(item)}</li>" for item in items)


def _score_bar(score: Any) -> str:
    """Create a small horizontal score bar."""
    numeric_score = _safe_score(score)
    width = int(round(numeric_score * 100))

    return (
        '<div class="scorebar">'
        f'<div class="scorebar-fill" style="width: {width}%"></div>'
        "</div>"
    )


def _make_evidence_html(evidence_card: EvidenceCard | None) -> str:
    """Render source-linked stored observations, never a target-level conclusion."""
    if evidence_card is None:
        return ""
    metrics = evidence_card.metrics
    rows: list[str] = []
    for item in evidence_card.items:
        if item.quoted_span is not None and item.computed_support is not None:
            support_type = "Hybrid quotation and computed support"
            support = f"Quoted span: {item.quoted_span}\nComputed support: {item.computed_support}"
        elif item.quoted_span is not None:
            support_type, support = "Quoted source text", item.quoted_span
        else:
            support_type, support = "Computed/database support", item.computed_support or "not available"
        confidence = "not reported" if item.extraction_confidence is None else f"{float(item.extraction_confidence):.3f}"
        family = item.evidence_family or "ineligible for independence metrics"
        rows.append(
            "<tr>"
            f"<td>{escape(item.evidence_id)}</td>"
            f"<td>{escape(item.evidence_type)} / {escape(item.evidence_direction)}</td>"
            f"<td>{escape(item.observation)}</td>"
            f"<td>{escape(item.source)} ({escape(item.source_id)})</td>"
            f"<td>{escape(support_type)}: {escape(support)}</td>"
            f"<td>{escape(item.validation_status)}</td>"
            f"<td>{escape(confidence)}<br><span class=\"note\">extraction-system, not scientific confidence</span></td>"
            f"<td>{escape(family)}</td>"
            "</tr>"
        )
    return f"""
<section class="card">
    <h2>Stored evidence observations</h2>
    <p class="note">Source-linked observations only; they do not alter deterministic classification, scores, or rankings.</p>
    <div class="grid">
        <div class="metric"><div class="metric-label">Distinct records</div><div class="metric-value">{metrics.record_count}</div></div>
        <div class="metric"><div class="metric-label">Known publications</div><div class="metric-value">{metrics.publication_count}</div></div>
        <div class="metric"><div class="metric-label">Known experiments</div><div class="metric-value">{metrics.experiment_count}</div></div>
        <div class="metric"><div class="metric-label">Known patient cohorts</div><div class="metric-value">{metrics.patient_cohort_count}</div></div>
        <div class="metric"><div class="metric-label">Independence-eligible root families</div><div class="metric-value">{metrics.independent_family_count}</div></div>
        <div class="metric"><div class="metric-label">Records ineligible for family metrics</div><div class="metric-value">{metrics.ineligible_record_count}</div></div>
    </div>
    <table><thead><tr><th>Record</th><th>Type / direction</th><th>Observation</th><th>Source</th><th>Support</th><th>Status</th><th>Extraction confidence</th><th>Family</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table>
</section>
"""


def get_report_css() -> str:
    """Return shared CSS for all reports."""
    return """
:root {
    --bg: #f6f8fb;
    --card: #ffffff;
    --text: #1f2937;
    --muted: #6b7280;
    --border: #e5e7eb;
    --high: #14532d;
    --high-bg: #dcfce7;
    --medium: #854d0e;
    --medium-bg: #fef3c7;
    --low: #1e3a8a;
    --low-bg: #dbeafe;
    --none: #374151;
    --none-bg: #e5e7eb;
    --accent: #2563eb;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 32px;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    line-height: 1.55;
}

.container {
    max-width: 1120px;
    margin: 0 auto;
}

.header {
    background: linear-gradient(135deg, #111827, #1e3a8a);
    color: white;
    padding: 32px;
    border-radius: 18px;
    margin-bottom: 24px;
}

.header h1 {
    margin: 0 0 8px 0;
    font-size: 34px;
}

.header p {
    margin: 0;
    color: #dbeafe;
}

.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
}

.grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}

.metric {
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px;
    background: #fbfdff;
}

.metric-label {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    margin-bottom: 4px;
}

.metric-value {
    font-size: 16px;
    font-weight: 650;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 12px;
}

th, td {
    border-bottom: 1px solid var(--border);
    padding: 10px;
    text-align: left;
    vertical-align: top;
}

th {
    font-size: 13px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 650;
}

.badge-high {
    color: var(--high);
    background: var(--high-bg);
}

.badge-medium {
    color: var(--medium);
    background: var(--medium-bg);
}

.badge-low {
    color: var(--low);
    background: var(--low-bg);
}

.badge-none {
    color: var(--none);
    background: var(--none-bg);
}

.scorebar {
    height: 8px;
    width: 100%;
    background: #e5e7eb;
    border-radius: 999px;
    overflow: hidden;
    margin-top: 6px;
}

.scorebar-fill {
    height: 100%;
    background: var(--accent);
}

.note {
    color: var(--muted);
    font-size: 14px;
}

.footer {
    margin-top: 32px;
    color: var(--muted);
    font-size: 13px;
}

a {
    color: var(--accent);
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

@media (max-width: 760px) {
    body {
        padding: 16px;
    }

    .grid {
        grid-template-columns: 1fr;
    }

    .header h1 {
        font-size: 26px;
    }
}
"""


def make_target_html_report(
    row: pd.Series,
    evidence_card: EvidenceCard | None = None,
    feasibility_annotations: tuple[object, ...] | list[object] | None = None,
    feasibility_target_identifier_type: str | None = None,
    dependency_evidence: DependencyReportEvidence | None = None,
) -> str:
    """
    Generate one standalone HTML target report.
    """
    symbol = _safe_str(row.get("target_symbol"))
    target_name = _safe_str(row.get("target_name"))

    next_experiment, experiment_rationale, validation_category = (
        recommend_next_experiment(row)
    )

    evidence_for_items = _split_pipe_text(row.get("evidence_for"))
    evidence_against_items = _split_pipe_text(row.get("evidence_against"))

    antibody_priority = _safe_str(row.get("antibody_io_priority"))
    biomarker_priority = _safe_str(row.get("biomarker_priority"))
    small_molecule_priority = _safe_str(row.get("small_molecule_priority"))
    feasibility_html = ""
    if feasibility_annotations is not None:
        if feasibility_target_identifier_type is None:
            raise ValueError("identifier_type_required_for_feasibility")
        feasibility_html = render_feasibility_html(make_feasibility_report_section(
            target_identifier=symbol,
            target_identifier_type=feasibility_target_identifier_type,
            annotations=feasibility_annotations,
        ))
    feasibility_suffix = f"\n\n{feasibility_html}" if feasibility_html else ""
    dependency_suffix = ""
    if dependency_evidence is not None:
        if not isinstance(dependency_evidence, DependencyReportEvidence):
            raise DependencyPresentationError("invalid_dependency_report_evidence")
        if dependency_evidence.gene_symbol != symbol:
            raise DependencyPresentationError("dependency_evidence_target_mismatch")
        dependency_suffix = f"\n\n{render_dependency_html(dependency_evidence)}"

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TargetIntel-IO report: {escape(symbol)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{get_report_css()}
</style>
</head>
<body>
<div class="container">

<header class="header">
    <h1>Target hypothesis report: {escape(symbol)}</h1>
    <p>TargetIntel-IO therapeutic-intent-aware target triage summary</p>
</header>

<section class="card">
    <h2>Target identity</h2>
    <div class="grid">
        <div class="metric">
            <div class="metric-label">Target symbol</div>
            <div class="metric-value">{escape(symbol)}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Target name</div>
            <div class="metric-value">{escape(target_name)}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Open Targets melanoma score</div>
            <div class="metric-value">{_safe_float(row.get("opentargets_score"))}</div>
            {_score_bar(row.get("opentargets_score"))}
        </div>
        <div class="metric">
            <div class="metric-label">Open Targets baseline rank</div>
            <div class="metric-value">{_safe_int(row.get("opentargets_rank"))}</div>
        </div>
    </div>
</section>

{_make_evidence_html(evidence_card)}{feasibility_suffix}{dependency_suffix}

<section class="card">
    <h2>Stable TargetIntel-IO classification</h2>
    <div class="grid">
        <div class="metric">
            <div class="metric-label">Role classification</div>
            <div class="metric-value">{escape(_safe_str(row.get("role_classification")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Role confidence</div>
            <div class="metric-value">{escape(_safe_str(row.get("role_confidence")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Therapeutic direction</div>
            <div class="metric-value">{escape(_safe_str(row.get("therapeutic_direction")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Best modality</div>
            <div class="metric-value">{escape(_safe_str(row.get("best_modality")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Resistance axis</div>
            <div class="metric-value">{escape(_safe_str(row.get("resistance_axis")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Matched resistance programs</div>
            <div class="metric-value">{escape(_safe_str(row.get("matched_resistance_programs")))}</div>
        </div>
    </div>
</section>

<section class="card">
    <h2>Therapeutic-intent rankings</h2>
    <table>
        <thead>
            <tr>
                <th>Therapeutic intent</th>
                <th>Score</th>
                <th>Rank</th>
                <th>Priority</th>
                <th>Rank shift vs Open Targets</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Antibody / IO-combination</td>
                <td>{_safe_float(row.get("antibody_io_final_score"))}{_score_bar(row.get("antibody_io_final_score"))}</td>
                <td>{_safe_int(row.get("antibody_io_rank"))}</td>
                <td><span class="badge {_priority_class(antibody_priority)}">{escape(antibody_priority)}</span></td>
                <td>{_safe_int(row.get("antibody_io_rank_shift_vs_opentargets"))}</td>
            </tr>
            <tr>
                <td>Resistance biomarker</td>
                <td>{_safe_float(row.get("biomarker_final_score"))}{_score_bar(row.get("biomarker_final_score"))}</td>
                <td>{_safe_int(row.get("biomarker_rank"))}</td>
                <td><span class="badge {_priority_class(biomarker_priority)}">{escape(biomarker_priority)}</span></td>
                <td>{_safe_int(row.get("biomarker_rank_shift_vs_opentargets"))}</td>
            </tr>
            <tr>
                <td>Tumor-intrinsic / small molecule</td>
                <td>{_safe_float(row.get("small_molecule_final_score"))}{_score_bar(row.get("small_molecule_final_score"))}</td>
                <td>{_safe_int(row.get("small_molecule_rank"))}</td>
                <td><span class="badge {_priority_class(small_molecule_priority)}">{escape(small_molecule_priority)}</span></td>
                <td>{_safe_int(row.get("small_molecule_rank_shift_vs_opentargets"))}</td>
            </tr>
        </tbody>
    </table>
</section>

<section class="card">
    <h2>Evidence for</h2>
    <ul>
        {_format_bullets(evidence_for_items)}
    </ul>
</section>

<section class="card">
    <h2>Evidence against / limitations</h2>
    <ul>
        {_format_bullets(evidence_against_items)}
    </ul>
</section>

<section class="card">
    <h2>Confidence and uncertainty</h2>
    <div class="grid">
        <div class="metric">
            <div class="metric-label">Confidence level</div>
            <div class="metric-value">{escape(_safe_str(row.get("confidence_level")))}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Data completeness score</div>
            <div class="metric-value">{_safe_float(row.get("data_completeness_score"))}</div>
            {_score_bar(row.get("data_completeness_score"))}
        </div>
        <div class="metric">
            <div class="metric-label">Contradiction score</div>
            <div class="metric-value">{_safe_float(row.get("contradiction_score"))}</div>
            {_score_bar(row.get("contradiction_score"))}
        </div>
        <div class="metric">
            <div class="metric-label">Main limitation</div>
            <div class="metric-value">{escape(_safe_str(row.get("main_limitation")))}</div>
        </div>
    </div>
    <p><strong>Uncertainty reason:</strong> {escape(_safe_str(row.get("uncertainty_reason")))}</p>
    <p><strong>Deprioritization reason:</strong> {escape(_safe_str(row.get("deprioritization_reason")))}</p>
</section>

<section class="card">
    <h2>Recommended next validation experiment</h2>
    <p><strong>Validation category:</strong> {escape(validation_category)}</p>
    <p><strong>Next experiment:</strong> {escape(next_experiment)}</p>
    <p><strong>Rationale:</strong> {escape(experiment_rationale)}</p>
</section>

<section class="card">
    <h2>Interpretation note</h2>
    <p class="note">
        This report is generated by TargetIntel-IO as a transparent, rule-based
        target triage summary. It is intended for hypothesis generation and
        portfolio demonstration only. It does not represent clinical advice or
        validated therapeutic evidence.
    </p>
</section>

<footer class="footer">
    Generated by TargetIntel-IO.
</footer>

</div>
</body>
</html>
"""

    return html


def write_target_html_report(
    row: pd.Series,
    output_dir: str | Path = DEFAULT_HTML_REPORT_DIR,
    evidence_card: EvidenceCard | None = None,
    feasibility_annotations: tuple[object, ...] | list[object] | None = None,
    feasibility_target_identifier_type: str | None = None,
    dependency_evidence: DependencyReportEvidence | None = None,
) -> Path:
    """
    Write one standalone HTML report.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    symbol = _safe_str(row.get("target_symbol"))
    output_path = output_dir / f"{symbol}.html"

    output_path.write_text(
        make_target_html_report(
            row, evidence_card=evidence_card,
            feasibility_annotations=feasibility_annotations,
            feasibility_target_identifier_type=feasibility_target_identifier_type,
            dependency_evidence=dependency_evidence,
        ),
        encoding="utf-8",
    )

    return output_path


def _make_target_link(symbol: str) -> str:
    """Create an HTML link to a target report."""
    safe_symbol = escape(symbol)
    return f'<a href="{safe_symbol}.html">{safe_symbol}</a>'


def _make_mode_table(
    df: pd.DataFrame,
    mode: str,
    label: str,
    top_n: int,
) -> str:
    """
    Create an HTML table for one therapeutic-intent mode.
    """
    rank_col = f"{mode}_rank"
    score_col = f"{mode}_final_score"
    priority_col = f"{mode}_priority"
    shift_col = f"{mode}_rank_shift_vs_opentargets"

    subset = df.sort_values(rank_col).head(top_n)

    rows = []

    for _, row in subset.iterrows():
        symbol = _safe_str(row.get("target_symbol"))
        priority = _safe_str(row.get(priority_col))

        rows.append(
            f"""
            <tr>
                <td>{_safe_int(row.get(rank_col))}</td>
                <td>{_make_target_link(symbol)}</td>
                <td>{escape(_safe_str(row.get("role_classification")))}</td>
                <td>{escape(_safe_str(row.get("best_modality")))}</td>
                <td>{_safe_float(row.get(score_col))}</td>
                <td><span class="badge {_priority_class(priority)}">{escape(priority)}</span></td>
                <td>{_safe_int(row.get(shift_col))}</td>
            </tr>
            """
        )

    return f"""
    <section class="card">
        <h2>{escape(label)}</h2>
        <table>
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Target</th>
                    <th>Role</th>
                    <th>Best modality</th>
                    <th>Score</th>
                    <th>Priority</th>
                    <th>Rank shift</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </section>
    """


def make_html_index(
    ranked_df: pd.DataFrame,
    top_n_per_mode: int = 10,
) -> str:
    """
    Generate an HTML index page for the target reports.
    """
    antibody_table = _make_mode_table(
        ranked_df,
        mode="antibody_io",
        label="Top antibody / IO-combination targets",
        top_n=top_n_per_mode,
    )

    biomarker_table = _make_mode_table(
        ranked_df,
        mode="biomarker",
        label="Top resistance biomarker candidates",
        top_n=top_n_per_mode,
    )

    small_molecule_table = _make_mode_table(
        ranked_df,
        mode="small_molecule",
        label="Top tumor-intrinsic / small-molecule candidates",
        top_n=top_n_per_mode,
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TargetIntel-IO HTML reports</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{get_report_css()}
</style>
</head>
<body>
<div class="container">

<header class="header">
    <h1>TargetIntel-IO reports</h1>
    <p>Therapeutic-intent-aware target triage for anti-PD-1-resistant melanoma</p>
</header>

<section class="card">
    <h2>How to read these reports</h2>
    <p>
        TargetIntel-IO keeps the biological role of each target stable, but ranks
        targets differently depending on the therapeutic intent.
    </p>
    <ul>
        <li><strong>High</strong>: strong candidate for that therapeutic intent.</li>
        <li><strong>Medium</strong>: plausible secondary candidate.</li>
        <li><strong>Low</strong>: weak or indirect fit.</li>
        <li><strong>Not prioritized</strong>: not a meaningful candidate for that mode under current MVP rules.</li>
    </ul>
</section>

{antibody_table}

{biomarker_table}

{small_molecule_table}

<footer class="footer">
    Generated by TargetIntel-IO.
</footer>

</div>
</body>
</html>
"""


def write_html_index(
    ranked_df: pd.DataFrame,
    output_dir: str | Path = DEFAULT_HTML_REPORT_DIR,
    top_n_per_mode: int = 10,
) -> Path:
    """
    Write the HTML index page.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "index.html"

    output_path.write_text(
        make_html_index(ranked_df, top_n_per_mode=top_n_per_mode),
        encoding="utf-8",
    )

    return output_path


def write_top_html_reports(
    ranked_df: pd.DataFrame,
    output_dir: str | Path = DEFAULT_HTML_REPORT_DIR,
    top_n_per_mode: int = 10,
    evidence_cards: Mapping[str, EvidenceCard] | None = None,
    feasibility_annotations: Mapping[str, tuple[object, ...] | list[object]] | None = None,
    feasibility_target_identifier_type: str | None = None,
    dependency_evidence_by_symbol: Mapping[str, DependencyReportEvidence] | None = None,
) -> list[Path]:
    """
    Write HTML reports for the union of top-N targets across all modes.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    required_rank_columns = [
        "antibody_io_rank",
        "biomarker_rank",
        "small_molecule_rank",
    ]

    for column in required_rank_columns:
        if column not in ranked_df.columns:
            raise KeyError(f"Required rank column not found: {column}")

    selected_symbols = set()

    for rank_column in required_rank_columns:
        top_symbols = (
            ranked_df.sort_values(rank_column)
            .head(top_n_per_mode)["target_symbol"]
            .tolist()
        )
        selected_symbols.update(top_symbols)

    selected_df = ranked_df[
        ranked_df["target_symbol"].isin(selected_symbols)
    ].copy()

    selected_df = selected_df.sort_values(
        by=[
            "antibody_io_rank",
            "biomarker_rank",
            "small_molecule_rank",
        ]
    )

    written_paths = []

    for _, row in selected_df.iterrows():
        target_annotations = (feasibility_annotations or {}).get(str(row["target_symbol"]))
        written_paths.append(write_target_html_report(
            row,
            output_dir=output_dir,
            evidence_card=(evidence_cards or {}).get(str(row["target_symbol"])),
            feasibility_annotations=target_annotations,
            feasibility_target_identifier_type=feasibility_target_identifier_type,
            dependency_evidence=(dependency_evidence_by_symbol or {}).get(str(row["target_symbol"])),
        ))

    index_path = write_html_index(
        ranked_df,
        output_dir=output_dir,
        top_n_per_mode=top_n_per_mode,
    )

    return [index_path] + written_paths
