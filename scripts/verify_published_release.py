"""Verify public PyPI bytes against approved assets and clean-install that wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
import venv
from pathlib import Path
from urllib.parse import urlparse

import tomllib


def verify_public_files(release, public, package, version, dist):
    stem = package.replace("-", "_")
    expected = {f"{stem}-{version}-py3-none-any.whl", f"{stem}-{version}.tar.gz"}
    if (
        public["info"]["version"] != version
        or public["info"]["name"].replace("_", "-").lower() != package.lower()
    ):
        raise ValueError("PyPI identity mismatch")
    files = {x["filename"]: x for x in public["urls"]}
    assets = {x["name"]: x for x in release["assets"]}
    if (
        set(files) != expected
        or release.get("draft")
        or release["tag_name"] != "v" + version
    ):
        raise ValueError("Release file set or tag mismatch")
    for name in expected:
        digest = hashlib.sha256((dist / name).read_bytes()).hexdigest()
        if (
            files[name].get("yanked")
            or files[name]["digests"]["sha256"] != digest
            or assets[name].get("digest") != "sha256:" + digest
        ):
            raise ValueError("Public asset digest mismatch")
        if files[name]["size"] != (dist / name).stat().st_size:
            raise ValueError("Public asset size mismatch")
        parsed = urlparse(files[name]["url"])
        if (
            parsed.scheme != "https"
            or parsed.hostname != "files.pythonhosted.org"
            or parsed.username
            or parsed.password
            or parsed.query
        ):
            raise ValueError("Unexpected distribution origin")
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    project = tomllib.loads((args.source / "pyproject.toml").read_text())["project"]
    package, version = project["name"], project["version"]
    if args.tag != "v" + version:
        raise ValueError("Tag/source mismatch")
    release = json.loads(args.release_json.read_text())
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{package}/{version}/json", timeout=30
    ) as response:
        public = json.load(response)
    files = verify_public_files(release, public, package, version, args.dist)
    with tempfile.TemporaryDirectory(prefix="verified-public-install-") as tmp:
        root = Path(tmp)
        downloads = root / "distributions"
        downloads.mkdir()
        for name, item in files.items():
            with urllib.request.urlopen(item["url"], timeout=60) as response:
                if urlparse(response.url).hostname != "files.pythonhosted.org":
                    raise ValueError("Distribution redirected to unexpected host")
                raw = response.read(item["size"] + 1)
            if (
                len(raw) != item["size"]
                or hashlib.sha256(raw).hexdigest() != item["digests"]["sha256"]
            ):
                raise ValueError("Downloaded distribution digest mismatch")
            (downloads / name).write_bytes(raw)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        wheel = next(downloads.glob("*.whl"))
        subprocess.run(
            [str(python), "-m", "pip", "install", "--only-binary=:all:", str(wheel)],
            cwd=root,
            check=True,
        )
        subprocess.run([str(python), "-m", "pip", "check"], cwd=root, check=True)
        modules = (
            ["prodocux_kernel", "api.main"]
            if package == "prodocux"
            else ["pdx_artifact_engine", "pdx_artifact_core", "pdx_adapter_prodocux"]
        )
        smoke = "import importlib,importlib.metadata; from pathlib import Path; "
        smoke += f"assert importlib.metadata.version({package!r})=={version!r}; "
        smoke += "; ".join(
            f"assert 'site-packages' in str(Path(importlib.import_module({m!r}).__file__))"
            for m in modules
        )
        subprocess.run([str(python), "-I", "-c", smoke], cwd=root, check=True)
    print("PUBLIC_DISTRIBUTIONS_AND_CLEAN_INSTALL_VERIFIED")


if __name__ == "__main__":
    main()
