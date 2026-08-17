"""PDX Artifact Core — platform-neutral contracts and runtime primitives.

Orchestrators decide *what*; Core validates and (later) executes *how*.
Does not import ProDocuX Kernel or call LLMs.
"""

from __future__ import annotations

from pdx_artifact_core.approval import (
    ApprovalError,
    ApprovalLedger,
    build_resumed_plan,
    cancel_checkpoint,
    canonical_digest,
    create_approval_request,
    create_checkpoint,
)
from pdx_artifact_core.compat_v0 import translate_plan_v0_to_v1
from pdx_artifact_core.events import InMemoryEventSink, run_event
from pdx_artifact_core.protocols import (
    EventSink,
    StorageAdapter,
    ToolExecutor,
    Verifier,
)
from pdx_artifact_core.state import RunState, allowed_transitions, can_transition
from pdx_artifact_core.storage import validate_artifact_storage_identity
from pdx_artifact_core.validate import (
    is_forbidden_artifact_uri,
    load_schema,
    validate_execution_plan,
    validate_instance,
    validate_tool_request,
    validate_tool_result,
)
from pdx_artifact_core.verification import validate_verifier_result

__version__ = "0.2.0a2"

__all__ = [
    "ApprovalError",
    "ApprovalLedger",
    "EventSink",
    "InMemoryEventSink",
    "RunState",
    "StorageAdapter",
    "ToolExecutor",
    "Verifier",
    "__version__",
    "allowed_transitions",
    "build_resumed_plan",
    "can_transition",
    "cancel_checkpoint",
    "canonical_digest",
    "create_approval_request",
    "create_checkpoint",
    "is_forbidden_artifact_uri",
    "load_schema",
    "run_event",
    "translate_plan_v0_to_v1",
    "validate_execution_plan",
    "validate_artifact_storage_identity",
    "validate_instance",
    "validate_tool_request",
    "validate_tool_result",
    "validate_verifier_result",
]
