from __future__ import annotations

import argparse
import re
from pathlib import Path

import tomllib
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"
START = "<!-- pypi-release-status:start -->"
END = "<!-- pypi-release-status:end -->"
PACKAGE = "pdx-artifact-engine"
REPOSITORY = "prodocux/pdx-artifact-engine"


def source_version() -> str:
    with PYPROJECT.open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def status_block(version: str, tag: str, commit: str) -> str:
    source = source_version()
    return f"""{START}
Source version in this branch: **`{source}`**.

Latest verified PyPI release: **[`{version}`](https://pypi.org/project/{PACKAGE}/{version}/)**,
published from tag **[`{tag}`](https://github.com/{REPOSITORY}/releases/tag/{tag})**
at commit `{commit}`.

```powershell
python -m pip install \"{PACKAGE}=={version}\"
```
{END}"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-source-version", action="store_true")
    parser.add_argument("--version")
    parser.add_argument("--tag")
    parser.add_argument("--commit")
    args = parser.parse_args()
    text = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    match = pattern.search(text)
    if match is None:
        raise SystemExit("README release-status markers are missing")
    if args.check_source_version:
        expected = f"Source version in this branch: **`{source_version()}`**."
        if expected not in match.group(0):
            raise SystemExit(
                f"README source version must match pyproject.toml: {expected}"
            )
        return 0
    if not all((args.version, args.tag, args.commit)):
        parser.error("--version, --tag, and --commit are required when updating")
    if (
        args.tag != f"v{args.version}"
        or re.fullmatch(r"[a-f0-9]{40}", args.commit) is None
    ):
        raise SystemExit("Release tag or commit identity is invalid")
    current = re.search(
        r"Latest verified PyPI release:.*?\[`([^`]+)`\]", match.group(0), re.DOTALL
    )
    if current and Version(args.version) < Version(current.group(1)):
        raise SystemExit("Refusing to downgrade the verified PyPI release")
    replacement = status_block(args.version, args.tag, args.commit)
    README.write_text(
        pattern.sub(lambda _: replacement, text, count=1),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
