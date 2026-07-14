"""Tests for TargetIntel-IO package dependency metadata."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml


PYPROJECT_PATH = Path("pyproject.toml")
ENVIRONMENT_PATH = Path("environment.yml")

EXPECTED_RUNTIME_DEPENDENCIES = {
    "duckdb",
    "matplotlib",
    "numpy",
    "pandas",
    "pyyaml",
    "requests",
    "scikit-learn",
}


def _dependency_name(requirement: str) -> str:
    """Extract and normalize a package name from a requirement."""
    name = re.split(
        r"[<>=!~;\[\s]",
        requirement,
        maxsplit=1,
    )[0]

    return name.strip().lower()


def test_pyproject_declares_complete_runtime_dependencies() -> None:
    with PYPROJECT_PATH.open("rb") as handle:
        pyproject = tomllib.load(handle)

    project = pyproject["project"]

    assert project["name"] == "targetintel-io"
    assert project["requires-python"] == ">=3.10"

    dependencies = {
        _dependency_name(requirement)
        for requirement in project["dependencies"]
    }

    assert dependencies == EXPECTED_RUNTIME_DEPENDENCIES


def test_pyproject_declares_test_extra() -> None:
    with PYPROJECT_PATH.open("rb") as handle:
        pyproject = tomllib.load(handle)

    dev_dependencies = {
        _dependency_name(requirement)
        for requirement
        in pyproject["project"][
            "optional-dependencies"
        ]["dev"]
    }

    assert "pytest" in dev_dependencies


def test_environment_contains_runtime_dependencies() -> None:
    environment = yaml.safe_load(
        ENVIRONMENT_PATH.read_text(
            encoding="utf-8"
        )
    )

    conda_dependencies = {
        _dependency_name(requirement)
        for requirement in environment["dependencies"]
        if isinstance(requirement, str)
    }

    assert EXPECTED_RUNTIME_DEPENDENCIES <= conda_dependencies
    assert "pytest" in conda_dependencies
    assert "pip" in conda_dependencies


def test_environment_installs_project_editably() -> None:
    environment = yaml.safe_load(
        ENVIRONMENT_PATH.read_text(
            encoding="utf-8"
        )
    )

    pip_sections = [
        dependency["pip"]
        for dependency in environment["dependencies"]
        if isinstance(dependency, dict)
        and "pip" in dependency
    ]

    assert len(pip_sections) == 1
    assert "-e ." in pip_sections[0]
