"""PDX Artifact Core — platform-neutral contracts and runtime primitives.

Orchestrators decide *what*; Core validates and (later) executes *how*.
Does not import ProDocuX Kernel or call LLMs.
"""

from __future__ import annotations

from pdx_artifact_core.compat_v0 import translate_plan_v0_to_v1
from pdx_artifact_core.protocols import StorageAdapter, ToolExecutor, Verifier
from pdx_artifact_core.state import RunState, allowed_transitions, can_transition
from pdx_artifact_core.validate import (
    is_forbidden_artifact_uri,
    load_schema,
    validate_execution_plan,
    validate_instance,
    validate_tool_request,
    validate_tool_result,
)

__version__ = "0.2.0a1"

__all__ = [
    "__version__",
    "RunState",
    "StorageAdapter",
    "ToolExecutor",
    "Verifier",
    "allowed_transitions",
    "can_transition",
    "is_forbidden_artifact_uri",
    "load_schema",
    "translate_plan_v0_to_v1",
    "validate_execution_plan",
    "validate_instance",
    "validate_tool_request",
    "validate_tool_result",
]
