from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import write_manifest


def build_run_manifest(
    *,
    run_id: str,
    request_id: str,
    status: str,
    steps: list[dict[str, Any]],
    verification: list[dict[str, str]],
    artifact_manifest: str = "artifact_manifest.json",
    errors: list[str] | None = None,
    planner: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "pdx_run_manifest_v0",
        "run_id": run_id,
        "request_id": request_id,
        "status": status,
        "steps": steps,
        "verification": verification,
        "artifact_manifest": artifact_manifest,
        "errors": errors or [],
    }
    if planner:
        payload["planner"] = planner
    return payload


def write_run_manifest(manifest: dict[str, Any], path: Path) -> None:
    write_manifest(manifest, path)


def load_run_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
