"""Source-tree and packaging-boundary release checks."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_FILES = [
    ROOT / "README.md",
    ROOT / "BACKLOG.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "pyproject.toml",
]
PUBLIC_TREES = [
    ROOT / "docs",
    ROOT / "packages",
    ROOT / "runtime",
    ROOT / "adapters" / "prodocux",
    ROOT / "adapters" / "media",
]
TEXT_SUFFIXES = {".md", ".py", ".toml", ".json"}
FORBIDDEN_PUBLIC_TERMS = re.compile(
    r"cinema|studio.?tower|devpost|agentic|grafana|"
    r"\bcursor\b|\bcodex\b|dual-track|track [ab]",
    re.IGNORECASE,
)


def _public_text_files() -> list[Path]:
    files = list(PUBLIC_FILES)
    for tree in PUBLIC_TREES:
        files.extend(
            path
            for path in tree.rglob("*")
            if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES
        )
    return files


def test_public_release_surface_has_no_product_or_agent_attribution() -> None:
    matches = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8")
        if path == ROOT / "README.md":
            text = text.split("\n## Acknowledgments\n", 1)[0]
        if FORBIDDEN_PUBLIC_TERMS.search(text):
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
