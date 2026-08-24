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
from pdx_artifact_core.events import (
    InMemoryEventSink,
    RunEventError,
    run_event,
    run_event_v1,
    validate_ordered_run_events,
    validate_run_event_v1,
)
from pdx_artifact_core.execution import (
    CancellationSignal,
    ExecutionContextError,
    ManualCancellationSignal,
    create_execution_context,
    ensure_execution_allowed,
    next_execution_attempt,
    validate_execution_context,
)
from pdx_artifact_core.external_operations import (
    ExternalOperationError,
    create_external_operation,
    external_operation_retry_allowed,
    external_operation_run_state,
    transition_external_operation,
    validate_external_operation,
)
from pdx_artifact_core.protocols import (
    CheckpointRepository,
    DecisionRepository,
    EventSink,
    StorageAdapter,
    ToolExecutor,
    Verifier,
)
from pdx_artifact_core.receipts import (
    PublicationReceiptError,
    create_publication_receipt,
    validate_publication_receipt,
)
from pdx_artifact_core.snapshots import (
    MAX_SNAPSHOT_BYTES,
    InMemoryCheckpointRepository,
    InMemoryDecisionRepository,
    SnapshotError,
    create_run_snapshot,
    decode_run_snapshot,
    encode_run_snapshot,
    snapshot_digest,
    validate_run_snapshot,
    validate_step_receipt,
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

__version__ = "0.3.0a2"

__all__ = [
    "MAX_SNAPSHOT_BYTES",
    "ApprovalError",
    "ApprovalLedger",
    "CancellationSignal",
    "CheckpointRepository",
    "DecisionRepository",
    "EventSink",
    "ExecutionContextError",
    "ExternalOperationError",
    "InMemoryCheckpointRepository",
    "InMemoryDecisionRepository",
    "InMemoryEventSink",
    "ManualCancellationSignal",
    "PublicationReceiptError",
    "RunEventError",
    "RunState",
    "SnapshotError",
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
    "create_execution_context",
    "create_external_operation",
    "create_publication_receipt",
    "create_run_snapshot",
    "decode_run_snapshot",
    "encode_run_snapshot",
    "ensure_execution_allowed",
    "external_operation_retry_allowed",
    "external_operation_run_state",
    "is_forbidden_artifact_uri",
    "load_schema",
    "next_execution_attempt",
    "run_event",
    "run_event_v1",
    "snapshot_digest",
    "transition_external_operation",
    "translate_plan_v0_to_v1",
    "validate_artifact_storage_identity",
    "validate_execution_context",
    "validate_execution_plan",
    "validate_external_operation",
    "validate_instance",
    "validate_ordered_run_events",
    "validate_publication_receipt",
    "validate_run_event_v1",
    "validate_run_snapshot",
    "validate_step_receipt",
    "validate_tool_request",
    "validate_tool_result",
    "validate_verifier_result",
]
