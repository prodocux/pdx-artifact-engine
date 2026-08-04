"""Stable, product-neutral façade over Dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .dispatcher import Dispatcher
from .registry import SkillDefinition, SkillRegistry

Executor = Callable[[dict[str, Any], Path], dict[str, Any]]


class ArtifactRuntime:
    """Execute a validated (or v0-translatable) plan and write manifests.

    Product applications own planning; this class only runs deterministic steps
    through explicitly registered executors.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        executors: Mapping[str, Executor] | None = None,
        *,
        allow_mock: bool = False,
        planner_name: str = "manual",
    ) -> None:
        self.registry = registry
        self.allow_mock = allow_mock
        self.planner_name = planner_name
        self._dispatcher = Dispatcher(
            registry,
            dict(executors) if executors else None,
            allow_mock=allow_mock,
            planner_name=planner_name,
        )

    def execute_plan(
        self,
        plan: dict[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        """Run ``plan`` into ``output_dir``; return artifact + run manifests."""
        return self._dispatcher.run(plan, Path(output_dir))


def skill_definition(
    *,
    name: str,
    domain: str,
    description: str,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
) -> SkillDefinition:
    """Minimal registry entry for dry-run / adapter tools."""
    outs = outputs or ["result.json"]
    return SkillDefinition(
        name=name,
        version="0.0.0-dryrun",
        domain=domain,
        description=description,
        entrypoint="artifact_runtime:registered_executor",
        inputs=tuple(inputs or []),
        outputs=tuple(outs),
        artifacts=tuple(outs),
        failure_codes=({"code": "DRYRUN_FAIL", "meaning": "dry-run executor failed"},),
        verification_hooks=(),
    )
