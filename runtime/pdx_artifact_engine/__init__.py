"""PDX Artifact Engine runtime package.

v0.2.0a1 re-exports Core contracts. Dispatcher normalizes ``pdx_plan_v0`` →
``pdx_execution_plan_v1`` (tool / approval / transform / verify). Legacy
``expert`` has no Core equivalent (D3): blocked unless ``--mock`` demo rewrite.
Stable façade: ``ArtifactRuntime.execute_plan``.
"""

from pdx_artifact_core import (
    RunState,
    StorageAdapter,
    ToolExecutor,
    Verifier,
    __version__ as core_version,
    allowed_transitions,
    can_transition,
    translate_plan_v0_to_v1,
    validate_execution_plan,
    validate_tool_request,
    validate_tool_result,
)

from .runtime import ArtifactRuntime

__version__ = "0.2.0a1"

__all__ = [
    "__version__",
    "core_version",
    "ArtifactRuntime",
    "RunState",
    "StorageAdapter",
    "ToolExecutor",
    "Verifier",
    "allowed_transitions",
    "can_transition",
    "translate_plan_v0_to_v1",
    "validate_execution_plan",
    "validate_tool_request",
    "validate_tool_result",
]
