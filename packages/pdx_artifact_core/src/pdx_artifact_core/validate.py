"""JSON Schema + semantic validation for Core contracts."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

from jsonschema import Draft202012Validator

# Query / fragment markers that indicate a credentialed or signed URL
_SIGNED_URI_MARKERS = (
    "x-goog-signature",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "signature=",
    "sig=",
    "access_token=",
    "id_token=",
    "token=",
    "auth=",
)


def _schema_text(name: str) -> str:
    root = resources.files("pdx_artifact_core.schemas")
    return (root / name).read_text(encoding="utf-8")


@lru_cache(maxsize=16)
def load_schema(name: str) -> dict[str, Any]:
    """Load a packaged schema by filename (e.g. execution_plan.v1.schema.json)."""
    return json.loads(_schema_text(name))


def validate_instance(schema: dict[str, Any], instance: Any) -> list[str]:
    validator = Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    ]


def is_forbidden_artifact_uri(uri: str) -> bool:
    """Return true when a URI looks signed or embeds credentials."""
    if not isinstance(uri, str) or not uri.strip():
        return True
    lower = uri.lower().strip()
    if any(m in lower for m in _SIGNED_URI_MARKERS):
        return True
    # userinfo in authority: https://token@host/...
    parsed = urlparse(uri)
    if parsed.username or parsed.password:
        return True
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for key in qs:
            k = key.lower()
            if k in {
                "signature",
                "x-goog-signature",
                "x-amz-signature",
                "x-amz-credential",
                "x-amz-security-token",
                "access_token",
                "id_token",
                "token",
                "auth",
                "sig",
            }:
                return True
    return False


def _graph_has_cycle(ids: set[str], edges: dict[str, list[str]]) -> list[str]:
    """Return list of nodes involved in a cycle, or empty if DAG."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}
    cycle_nodes: list[str] = []

    def dfs(u: str, stack: list[str]) -> bool:
        color[u] = GRAY
        stack.append(u)
        for v in edges.get(u, []):
            if v not in ids:
                continue
            if color[v] == GRAY:
                # cycle
                idx = stack.index(v)
                cycle_nodes.extend(stack[idx:])
                return True
            if color[v] == WHITE and dfs(v, stack):
                return True
        stack.pop()
        color[u] = BLACK
        return False

    for node in ids:
        if color[node] == WHITE and dfs(node, []):
            return cycle_nodes
    return []


def _semantic_execution_plan_errors(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        return errors

    ids: list[str] = []
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            continue
        ids.append(sid)
        kind = step.get("kind")
        if kind == "transform" and not step.get("transform"):
            errors.append(f"steps/{i}: transform steps require 'transform'")
        if kind == "verify":
            ver = step.get("verification")
            if not isinstance(ver, list) or len(ver) < 1:
                errors.append(f"steps/{i}: verify steps require non-empty 'verification'")

    # duplicate ids
    seen: set[str] = set()
    dupes: set[str] = set()
    for sid in ids:
        if sid in seen:
            dupes.add(sid)
        seen.add(sid)
    for d in sorted(dupes):
        errors.append(f"steps: duplicate step id {d!r}")

    id_set = set(ids)
    edges: dict[str, list[str]] = {sid: [] for sid in id_set}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        sid = step.get("id")
        deps = step.get("depends_on") or []
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if dep not in id_set:
                errors.append(f"steps/{i}: unknown dependency {dep!r}")
            elif isinstance(sid, str) and sid in id_set:
                edges[dep].append(sid)  # edge dep → sid (dep before sid)

    cycle = _graph_has_cycle(id_set, edges)
    if cycle:
        errors.append(f"steps: dependency cycle involving {cycle!r}")

    return errors


def _semantic_tool_result_errors(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artifacts = result.get("artifacts") or []
    if not isinstance(artifacts, list):
        return errors
    for i, art in enumerate(artifacts):
        if not isinstance(art, dict):
            continue
        uri = art.get("uri")
        if isinstance(uri, str) and is_forbidden_artifact_uri(uri):
            errors.append(
                f"artifacts/{i}/uri: forbidden signed URL or credentialed URI "
                "(use opaque identity only)"
            )
    return errors


def validate_execution_plan(plan: dict[str, Any]) -> list[str]:
    errs = validate_instance(load_schema("execution_plan.v1.schema.json"), plan)
    if not errs:
        errs.extend(_semantic_execution_plan_errors(plan))
    return errs


def validate_tool_request(request: dict[str, Any]) -> list[str]:
    return validate_instance(load_schema("tool_request.v1.schema.json"), request)


def validate_tool_result(result: dict[str, Any]) -> list[str]:
    errs = validate_instance(load_schema("tool_result.v1.schema.json"), result)
    if not errs:
        errs.extend(_semantic_tool_result_errors(result))
    return errs
