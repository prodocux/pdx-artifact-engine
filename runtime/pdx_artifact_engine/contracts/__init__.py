"""Runtime JSON schemas packaged with the Engine wheel."""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any


def load_schema(phase: str, name: str, *, root: Path | None = None) -> dict[str, Any]:
    """Load a runtime schema from an explicit root, env override, or package data."""
    if root is not None:
        return json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
    env_key = (
        "PDX_ENGINE_CONTRACT_ROOT"
        if phase == "phase0"
        else "PDX_ENGINE_PHASE3_CONTRACT_ROOT"
    )
    env = os.environ.get(env_key, "").strip()
    if env:
        return json.loads((Path(env) / "schemas" / name).read_text(encoding="utf-8"))
    package = f"pdx_artifact_engine.contracts.{phase}"
    return json.loads(files(package).joinpath(name).read_text(encoding="utf-8"))
