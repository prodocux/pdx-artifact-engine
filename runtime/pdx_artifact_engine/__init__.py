"""PDX Artifact Engine runtime package.

Working tree ``0.3.0a3`` re-exports Core contracts. Dispatcher normalizes
``pdx_plan_v0`` → ``pdx_execution_plan_v1`` (tool / approval / transform /
verify). Legacy ``expert`` has no Core equivalent (D3): blocked unless
``--mock`` demo rewrite. Stable façade: ``ArtifactRuntime.execute_plan``.
Last published PyPI prerelease remains ``0.3.0a2``.
"""

from pdx_artifact_core import (
    RunState,
    StorageAdapter,
    ToolExecutor,
    Verifier,
    allowed_transitions,
    can_transition,
    translate_plan_v0_to_v1,
    validate_execution_plan,
    validate_tool_request,
    validate_tool_result,
)
from pdx_artifact_core import (
    __version__ as core_version,
)

from .runtime import ArtifactRuntime

__version__ = "0.3.0a3"

__all__ = [
    "ArtifactRuntime",
    "RunState",
    "StorageAdapter",
    "ToolExecutor",
    "Verifier",
    "__version__",
    "allowed_transitions",
    "can_transition",
    "core_version",
    "translate_plan_v0_to_v1",
    "validate_execution_plan",
    "validate_tool_request",
    "validate_tool_result",
]
