"""Product-neutral run state machine and explicit return edges."""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_TOOL = "awaiting_tool"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    COMPLETED_WITH_REVIEW = "completed_with_review"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PENDING: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING: frozenset(
        {
            RunState.AWAITING_TOOL,
            RunState.AWAITING_APPROVAL,
            RunState.COMPLETED,
            RunState.COMPLETED_WITH_REVIEW,
            RunState.FAILED,
            RunState.BLOCKED,
            RunState.CANCELLED,
            RunState.TIMED_OUT,
        }
    ),
    RunState.AWAITING_TOOL: frozenset(
        {
            RunState.RUNNING,
            RunState.FAILED,
            RunState.BLOCKED,
            RunState.CANCELLED,
            RunState.TIMED_OUT,
        }
    ),
    RunState.AWAITING_APPROVAL: frozenset(
        {
            RunState.RUNNING,
            RunState.COMPLETED_WITH_REVIEW,
            RunState.FAILED,
            RunState.BLOCKED,
            RunState.CANCELLED,
            RunState.TIMED_OUT,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.COMPLETED_WITH_REVIEW: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.BLOCKED: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
}


def allowed_transitions(state: RunState) -> frozenset[RunState]:
    return _TRANSITIONS[state]


def can_transition(src: RunState, dst: RunState) -> bool:
    return dst in _TRANSITIONS[src]
