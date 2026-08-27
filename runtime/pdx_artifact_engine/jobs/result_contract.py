"""Phase 1 result contract validation (kind↔URI, uniqueness, job binding).

JSON Schema covers structural shape and kind→URI namespace binding.
Cross-item rules (one item per kind, item.job_id == envelope job_id) are
enforced here and locked by contract tests.
"""

from __future__ import annotations

import re
from typing import Any

_INTAKE_URI = re.compile(
    r"^artifact://intake/[A-Za-z0-9_-]+/[A-Za-z0-9._-]+$"
)
_PROCESSING_URI = re.compile(
    r"^artifact://(derived|sink|render)/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?$"
)
_KIND_URI = {
    "materialized_source": _INTAKE_URI,
    "processing_output": _PROCESSING_URI,
}


class ResultContractError(ValueError):
    """Result envelope or item violates Phase 1 `/results` semantics."""


def validate_result_item(item: dict[str, Any], *, job_id: str) -> None:
    if not isinstance(item, dict):
        raise ResultContractError("result item must be an object")
    if item.get("schema_version") != "pdx_internal_job_result_v1":
        raise ResultContractError("result item schema_version mismatch")
    if item.get("job_id") != job_id:
        raise ResultContractError("result item job_id must equal envelope job_id")
    kind = item.get("kind")
    if kind not in _KIND_URI:
        raise ResultContractError(f"unsupported result kind: {kind!r}")
    artifact = item.get("artifact")
    if not isinstance(artifact, dict):
        raise ResultContractError("result item artifact must be an object")
    uri = str(artifact.get("uri") or "")
    if not _KIND_URI[kind].fullmatch(uri):
        raise ResultContractError(
            f"kind {kind!r} is not bound to URI namespace for {uri!r}"
        )


def validate_result_items(
    items: list[dict[str, Any]], *, job_id: str
) -> list[dict[str, Any]]:
    """Validate and return a defensive copy. Order is not semantic."""
    if len(items) > 2:
        raise ResultContractError("results may contain at most one item per kind")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in items:
        item = dict(raw)
        validate_result_item(item, job_id=job_id)
        kind = str(item["kind"])
        if kind in seen:
            raise ResultContractError(f"duplicate result kind: {kind}")
        seen.add(kind)
        out.append(item)
    return out


def normalize_result_items(
    result: dict[str, Any] | list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [dict(item) for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        return [dict(result)]
    return []
