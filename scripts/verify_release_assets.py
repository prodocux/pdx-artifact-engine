"""Verify coordinated PDX release assets against GitHub and package metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError(f"expected one METADATA file in {path.name}")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    return metadata["Name"], metadata["Version"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    project_files = (
        args.source / "pyproject.toml",
        args.source / "adapters" / "media" / "pyproject.toml",
    )
    projects = [tomllib.loads(path.read_text("utf-8"))["project"] for path in project_files]
    engine = projects[0]
    if args.tag != f"v{engine['version']}":
        raise ValueError(f"tag {args.tag!r} does not match engine version {engine['version']!r}")

    expected_names: set[str] = set()
    wheel_paths: dict[str, Path] = {}
    for project in projects:
        name, version = project["name"], project["version"]
        distribution_stem = name.replace("-", "_")
        wheel_name = f"{distribution_stem}-{version}-py3-none-any.whl"
        expected_names.update((wheel_name, f"{distribution_stem}-{version}.tar.gz"))
        wheel_paths[name] = args.dist / wheel_name

    local_names = {path.name for path in args.dist.iterdir() if path.is_file()}
    if local_names != expected_names:
        raise ValueError(f"release assets mismatch: expected {expected_names}, got {local_names}")

    release = json.loads(args.release_json.read_text("utf-8"))
    if release["tag_name"] != args.tag:
        raise ValueError("GitHub release tag does not match requested tag")
    remote_digests = {asset["name"]: asset.get("digest") for asset in release["assets"]}
    for asset_name in expected_names:
        local_digest = f"sha256:{_sha256(args.dist / asset_name)}"
        if remote_digests.get(asset_name) != local_digest:
            raise ValueError(f"digest mismatch for {asset_name}")

    for project in projects:
        actual = _wheel_metadata(wheel_paths[project["name"]])
        expected = (project["name"], project["version"])
        if actual != expected:
            raise ValueError(f"wheel metadata mismatch: expected {expected}, got {actual}")
    print("release assets PASS: " + ", ".join(f"{p['name']} {p['version']}" for p in projects))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
