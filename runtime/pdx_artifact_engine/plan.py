from __future__ import annotations

from pathlib import Path
from typing import Any

from .cli.validate import load_json, validate_file
from .errors import PlanError


def load_plan(path: Path, schema_path: Path) -> dict[str, Any]:
    errors = validate_file(schema_path, path)
    if errors:
        raise PlanError("Invalid plan:\n" + "\n".join(f"- {error}" for error in errors))
    value = load_json(path)
    if not isinstance(value, dict):
        raise PlanError("Plan root must be an object")
    return value
