import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_source_preserved_and_downgrade_rejected(tmp_path, monkeypatch):
    module = load("update_readme_after_publish")
    monkeypatch.setattr(module, "README", tmp_path / "README.md")
    monkeypatch.setattr(module, "PYPROJECT", tmp_path / "pyproject.toml")
    module.PYPROJECT.write_text('[project]\nversion="0.4.0rc1"\n')
    original = (
        "before\n"
        + module.status_block("0.3.0rc10", "v0.3.0rc10", "a" * 40)
        + "\nafter\n"
    )
    module.README.write_text(original)
    monkeypatch.setattr(
        sys,
        "argv",
        ["update", "--version", "0.3.0rc9", "--tag", "v0.3.0rc9", "--commit", "a" * 40],
    )
    with pytest.raises(SystemExit, match="downgrade"):
        module.main()
    assert module.README.read_text() == original
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "update",
            "--version",
            "0.3.0rc11",
            "--tag",
            "v0.3.0rc11",
            "--commit",
            "b" * 40,
        ],
    )
    module.main()
    result = module.README.read_text()
    assert "Source version in this branch: **`0.4.0rc1`**." in result
    assert result.startswith("before\n") and result.endswith("\nafter\n")
    module.main()
    assert module.README.read_text() == result


@pytest.mark.parametrize(
    "fault", ["none", "pypi_digest", "github_digest", "yanked", "origin", "file_set"]
)
def test_public_files_gate(tmp_path, fault):
    module = load("verify_published_release")
    package = "example-package"
    version = "1.0rc1"
    names = ["example_package-1.0rc1-py3-none-any.whl", "example_package-1.0rc1.tar.gz"]
    public = {"info": {"name": package, "version": version}, "urls": []}
    release = {"tag_name": "v" + version, "assets": [], "draft": False}
    for name in names:
        raw = name.encode()
        (tmp_path / name).write_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        public["urls"].append(
            {
                "filename": name,
                "size": len(raw),
                "digests": {"sha256": sha},
                "url": "https://files.pythonhosted.org/packages/" + name,
                "yanked": False,
            }
        )
        release["assets"].append({"name": name, "digest": "sha256:" + sha})
    if fault == "pypi_digest":
        public["urls"][0]["digests"]["sha256"] = "0" * 64
    if fault == "github_digest":
        release["assets"][0]["digest"] = "sha256:" + "0" * 64
    if fault == "yanked":
        public["urls"][0]["yanked"] = True
    if fault == "origin":
        public["urls"][0]["url"] = "https://untrusted.invalid/wheel"
    if fault == "file_set":
        public["urls"].pop()
    if fault == "none":
        assert (
            len(module.verify_public_files(release, public, package, version, tmp_path))
            == 2
        )
    else:
        with pytest.raises(ValueError):
            module.verify_public_files(release, public, package, version, tmp_path)


def test_workflow_gates_and_repository_scope():
    flow = (ROOT / ".github/workflows/readme-after-publish.yml").read_text()
    assert flow.index("verify_published_release.py") < flow.index(
        "Mint repository-scoped App token"
    )
    for text in (
        "persist-credentials: false",
        "add-paths: README.md",
        "permission-contents: write",
        "permission-pull-requests: write",
        "repositories: ${{ github.event.repository.name }}",
    ):
        assert text in flow
    assert "continue-on-error" not in flow
    assert "auto-merge" not in flow
    assert (
        "uses: ./.github/workflows/readme-after-publish.yml"
        in (ROOT / ".github/workflows/release.yml").read_text()
    )
