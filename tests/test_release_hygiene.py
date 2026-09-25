"""Source-tree and packaging-boundary release checks."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "pyproject.toml",
]
PUBLIC_TREES = [
    ROOT / "compatibility",
    ROOT / "docs",
    ROOT / "packages",
    ROOT / "runtime",
    ROOT / "adapters" / "prodocux",
    ROOT / "adapters" / "media",
]
TEXT_SUFFIXES = {
    ".md", ".py", ".toml", ".json", ".yml", ".yaml", ".mjs",
    ".ipynb", ".ps1",
}
PUBLIC_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".tmp",
    "build",
    "dist",
    "node_modules",
    "tests",
}
HISTORICAL_PRODUCT_PATTERN = (
    r"case[-_ ]?memory|cinema|fortified[-_ ]?enterprise[-_ ]?fleet|"
    r"\bfleet\b|handcheck|crdb[-_ ]?agent[-_ ]?memory|datahub[-_ ]?gate|"
    r"evidence[-_ ]?gate|local[-_ ]?ai|reviewdesk|roadstar|shelfready|"
    r"studio.?tower|\bfarpals\b|free[-_ ]?studio[-_ ]?flow|\bfsf\b|"
    r"b-?roll|wordpress|woocommerce|kaggle|devpost|opencv|connectome|tlorder"
)
FORBIDDEN_PUBLIC_TERMS = re.compile(
    HISTORICAL_PRODUCT_PATTERN
    + r"|agentic|grafana|\bcursor\b|\bcodex\b|dual[- ]track",
    re.IGNORECASE,
)


def _public_text_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in TEXT_SUFFIXES
        and not (set(path.relative_to(ROOT).parts) & PUBLIC_EXCLUDED_PARTS)
    ]


def test_public_release_surface_has_no_product_or_agent_attribution() -> None:
    matches = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8")
        if FORBIDDEN_PUBLIC_TERMS.search(path.name) or FORBIDDEN_PUBLIC_TERMS.search(text):
            matches.append(path.relative_to(ROOT).as_posix())
    assert matches == []


def test_private_incubator_files_are_absent_from_release_tree() -> None:
    denied = [
        ROOT / "runtime" / "pdx_artifact_engine" / "cinema_dryrun.py",
        ROOT / "docs" / "CINEMA_RUNTIME.md",
        ROOT / "docs" / "DUAL_TRACK_UPGRADE.md",
        ROOT / "docs" / "DUAL_TRACK_ADDENDUM_A.md",
    ]
    assert [path.as_posix() for path in denied if path.exists()] == []


def test_internal_document_classes_are_absent_from_public_tree() -> None:
    denied_names = {
        "BACKLOG.md",
        "COMMERCIALIZATION.md",
        "FARPALS_REALIGNMENT_BACKLOG.md",
        "GITHUB_REPO_PLAN.md",
        "HOST_GATE_BACKLOG.md",
        "IMPLEMENTATION_PLAN.md",
        "KAGGLE_PLAN.md",
        "PHASE0_DECISIONS.md",
        "PHASE1_FARPALS_DOCK.md",
        "PHASE1_STATUS.md",
        "PHASE3_STATUS.md",
        "RELEASE_A9.md",
        "ROADSTAR_SCHEDULING_BACKLOG.md",
        "SECURITY_RUNTIME.md",
    }
    found = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*.md")
        if path.name in denied_names
        and not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        and path.relative_to(ROOT).parts[0] not in {"build", "dist"}
    )
    assert found == []


def test_public_release_surface_has_no_windows_checkout_paths() -> None:
    windows_path = re.compile(r"(?i)\b[A-Z]:\\")
    found = [
        path.relative_to(ROOT).as_posix()
        for path in _public_text_files()
        if windows_path.search(path.read_text(encoding="utf-8"))
    ]
    assert found == []


def test_consumer_provenance_is_not_stored_in_public_docs() -> None:
    found = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file()
        and "consumer-provenance" in path.name.casefold()
        and not (set(path.relative_to(ROOT).parts) & PUBLIC_EXCLUDED_PARTS)
    )
    assert found == []


def test_release_records_and_conformance_evidence_are_product_neutral() -> None:
    consumer_attribution = re.compile(HISTORICAL_PRODUCT_PATTERN, re.IGNORECASE)
    trees = [
        ROOT / "compatibility",
        ROOT / "docs" / "conformance-checks",
        ROOT / "adapters" / "media" / "examples",
    ]
    found = []
    for tree in trees:
        for path in tree.rglob("*"):
            if (
                path.is_file()
                and path.suffix.casefold() in TEXT_SUFFIXES
                and (
                    consumer_attribution.search(path.name)
                    or consumer_attribution.search(path.read_text(encoding="utf-8"))
                )
            ):
                found.append(path.relative_to(ROOT).as_posix())
    assert found == []


def test_main_and_media_packages_are_separate() -> None:
    root_config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    root_include = root_config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "pdx_adapter_prodocux*" in root_include
    assert "pdx_adapter_media*" not in root_include

    media_config = tomllib.loads(
        (ROOT / "adapters" / "media" / "pyproject.toml").read_text("utf-8")
    )
    media_include = media_config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert media_include == ["pdx_adapter_media*"]


def test_public_distribution_metadata_is_complete() -> None:
    root_project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text("utf-8")
    )["project"]
    media_project = tomllib.loads(
        (ROOT / "adapters" / "media" / "pyproject.toml").read_text("utf-8")
    )["project"]
    assert root_project["license-files"] == ["LICENSE"]
    assert root_project["authors"]
    assert root_project["urls"]["Repository"].endswith("/pdx-artifact-engine")
    assert media_project["license-files"] == ["LICENSE"]
    assert media_project["authors"]
    root_license = (ROOT / "LICENSE").read_text("utf-8")
    assert (ROOT / "adapters" / "media" / "LICENSE").read_text("utf-8") == root_license
    assert (
        ROOT / "packages" / "pdx_artifact_core" / "LICENSE"
    ).read_text("utf-8") == root_license


def test_core_is_not_published_as_a_second_overlapping_distribution() -> None:
    root_config = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert "pdx_artifact_core*" in root_config["tool"]["setuptools"]["packages"]["find"]["include"]
    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    assert "pdx_artifact_core-*" not in release_workflow


def test_pending_publishers_have_unambiguous_environment_identities() -> None:
    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
    assert "environment: pypi\n" in release_workflow
    assert "environment: pypi-media\n" in release_workflow
    assert "name: pypi-engine-" in release_workflow
    assert "name: pypi-media-" in release_workflow
