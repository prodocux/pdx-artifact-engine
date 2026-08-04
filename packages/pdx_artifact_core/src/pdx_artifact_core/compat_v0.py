"""Translate legacy pdx_plan_v0 into pdx_execution_plan_v1.

Legacy expert has no Core equivalent — rejected unless pre_resolved_expert=True
(in which case expert steps must already be removed by the caller).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_KIND_MAP = {
    "skill": "tool",
    "fixture": "tool",
    "human_input": "approval",
    "verification": "verify",
}


class CompatError(ValueError):
    """A v0 plan cannot be translated without changing its meaning."""


def translate_plan_v0_to_v1(
    plan_v0: dict[str, Any],
    *,
    producer_type: str = "manual",
    producer_name: str | None = None,
    pre_resolved_expert: bool = False,
) -> dict[str, Any]:
    """Return a new v1 execution plan dict.

    - skill/fixture → tool (tool id from step.name)
    - human_input → approval
    - verification → verify
    - expert → CompatError unless pre_resolved_expert and no expert steps remain
    """
    if plan_v0.get("schema_version") != "pdx_plan_v0":
        raise CompatError(
            f"expected schema_version pdx_plan_v0, got {plan_v0.get('schema_version')!r}"
        )

    steps_out: list[dict[str, Any]] = []
    for step in plan_v0.get("steps") or []:
        kind = step.get("kind")
        if kind == "expert":
            if pre_resolved_expert:
                raise CompatError(
                    f"step {step.get('id')!r}: expert still present; "
                    "orchestrator must resolve/remove expert before translate"
                )
            raise CompatError(
                f"step {step.get('id')!r}: legacy expert has no Core equivalent; "
                "resolve in orchestrator or reject (D3)"
            )
        if kind not in _KIND_MAP:
            raise CompatError(f"step {step.get('id')!r}: unknown v0 kind {kind!r}")

        new_kind = _KIND_MAP[kind]
        new_step: dict[str, Any] = {
            "id": step["id"],
            "kind": new_kind,
        }
        if "name" in step:
            new_step["name"] = step["name"]
        if "depends_on" in step:
            new_step["depends_on"] = list(step["depends_on"])
        if "inputs" in step:
            new_step["inputs"] = deepcopy(step["inputs"])
        if "outputs" in step:
            new_step["outputs"] = list(step["outputs"])

        if new_kind == "tool":
            tool_id = step.get("name")
            if not tool_id:
                raise CompatError(f"step {step.get('id')!r}: tool steps need name as tool id")
            new_step["tool"] = tool_id

        # Per-step approval: human_input → approval implies approval_required
        if new_kind == "approval":
            new_step["policies"] = {"approval_required": True}

        steps_out.append(new_step)

    out: dict[str, Any] = {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": plan_v0["request_id"],
        "producer": {"type": producer_type},
        "steps": steps_out,
    }
    if producer_name:
        out["producer"]["name"] = producer_name
    if "intent" in plan_v0:
        out["intent"] = deepcopy(plan_v0["intent"])
    if "verification" in plan_v0:
        out["verification"] = deepcopy(plan_v0["verification"])
    return out
