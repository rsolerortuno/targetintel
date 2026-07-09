"""Tests for the exact TargetIntel-IO dependency lockfile."""

from __future__ import annotations

import re
from pathlib import Path


LOCK_PATH = Path("requirements-lock.txt")

EXPECTED_DIRECT_DEPENDENCIES = {
    "matplotlib",
    "numpy",
    "pandas",
    "pyyaml",
    "requests",
    "scikit-learn",
    "pytest",
}


def _normalize_package_name(name: str) -> str:
    """Normalize Python distribution names."""
    return re.sub(
        r"[-_.]+",
        "-",
        name.strip().lower(),
    )


def _locked_packages() -> dict[str, str]:
    """Extract exact package versions from the pip-compile lockfile."""
    packages: dict[str, str] = {}

    pattern = re.compile(
        r"^([A-Za-z0-9_.-]+)==([^\\\s;]+)"
    )

    for raw_line in LOCK_PATH.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()

        match = pattern.match(line)

        if not match:
            continue

        name = _normalize_package_name(
            match.group(1)
        )

        packages[name] = match.group(2)

    return packages


def test_lockfile_exists_and_is_non_empty() -> None:
    assert LOCK_PATH.is_file()
    assert LOCK_PATH.stat().st_size > 1_000


def test_lockfile_uses_exact_versions_and_hashes() -> None:
    text = LOCK_PATH.read_text(
        encoding="utf-8"
    )

    packages = _locked_packages()

    assert packages
    assert "--hash=sha256:" in text

    for version in packages.values():
        assert version
        assert not any(
            operator in version
            for operator in [
                ">",
                "<",
                "~",
                "*",
            ]
        )


def test_lockfile_contains_all_direct_dependencies() -> None:
    packages = set(
        _locked_packages()
    )

    assert (
        EXPECTED_DIRECT_DEPENDENCIES
        <= packages
    )


def test_lockfile_contains_no_local_or_editable_paths() -> None:
    text = LOCK_PATH.read_text(
        encoding="utf-8"
    )

    assert "file://" not in text
    assert "\n-e " not in text
    assert "\n--editable " not in text


def test_lockfile_documents_python_version() -> None:
    text = LOCK_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "Generated for Python 3.11 "
        "from pyproject.toml."
        in text
    )
