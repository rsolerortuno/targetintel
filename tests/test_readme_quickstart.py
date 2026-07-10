"""Regression tests for the portfolio-facing README quick start."""

from __future__ import annotations

from pathlib import Path


README_PATH = Path("README.md")


def test_readme_documents_console_workflow() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    required_commands = [
        "targetintel run",
        "targetintel run --validate",
        "targetintel run --refresh",
        "targetintel run --help",
    ]

    for command in required_commands:
        assert command in readme


def test_readme_uses_correct_repository_url() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "https://github.com/"
        "rsolerortuno/TargetIntel-IO.git"
        in readme
    )


def test_readme_links_versioned_examples() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    required_paths = [
        "examples/html_reports/",
        "examples/figures/",
        "examples/benchmark/README.md",
        "examples/sensitivity/README.md",
    ]

    for path in required_paths:
        assert path in readme


def test_readme_does_not_restore_obsolete_workflow() -> None:
    readme = README_PATH.read_text(
        encoding="utf-8"
    )

    obsolete_content = [
        "rsolerortuno/TargetIntel.git",
        "pip install -r requirements.txt",
        "The current prototype can be run",
        "Planned workflow:",
        "Planned MVP milestones",
        "The final MVP will include a Streamlit dashboard",
    ]

    for obsolete_text in obsolete_content:
        assert obsolete_text not in readme


def test_readme_remains_portfolio_length() -> None:
    line_count = len(
        README_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    )

    # The README includes installation, workflow, benchmark,
    # sensitivity, limitations, and reproducibility documentation.
    # Keep it concise enough for portfolio review without removing
    # scientifically important context.
    assert line_count <= 360
