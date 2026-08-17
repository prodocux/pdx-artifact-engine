"""Build a wheel, install it into a temporary venv, and smoke-test imports."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ("pdx_artifact_engine", "pdx_artifact_core", "pdx_adapter_prodocux")


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="retain temporary files")
    args = parser.parse_args()
    temp = None if args.keep else tempfile.TemporaryDirectory(prefix="pdx-release-")
    work = Path(tempfile.mkdtemp(prefix="pdx-release-")) if args.keep else Path(temp.name)
    try:
        wheels = work / "wheels"
        wheels.mkdir()
        _run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), str(ROOT), cwd=work)
        wheel = next(wheels.glob("pdx_artifact_engine-*.whl"))
        env_dir = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        _run(str(python), "-m", "pip", "install", str(wheel), cwd=work)
        smoke = "; ".join(f"import {name}" for name in IMPORTS)
        smoke += (
            "; from importlib.resources import files"
            "; assert files('pdx_artifact_core.schemas')"
            ".joinpath('execution_plan.v1.schema.json').is_file()"
        )
        _run(str(python), "-c", smoke, cwd=work)
        print(f"clean-install PASS: {wheel.name}")
        print(f"isolated cwd: {work}")
        if args.keep:
            print(f"retained evidence directory: {work}")
        return 0
    finally:
        if temp is not None:
            temp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
