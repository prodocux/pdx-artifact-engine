"""SQLite persistence for runtime-provider workflows.

Every state transition uses ``BEGIN IMMEDIATE`` so counters, attempts, claims,
records, and terminal state change as one durable unit across processes.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RuntimeWorkflowStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_workflows (
                    workflow_job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    operation_digest TEXT NOT NULL,
                    plan_digest TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    counters_json TEXT NOT NULL,
                    terminal_error_json TEXT,
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_workflow_steps (
                    workflow_job_id TEXT NOT NULL,
                    workflow_step_id TEXT NOT NULL,
                    step_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (workflow_job_id, workflow_step_id),
                    FOREIGN KEY (workflow_job_id) REFERENCES runtime_workflows(workflow_job_id)
                );
                CREATE TABLE IF NOT EXISTS runtime_workflow_claims (
                    claim_id TEXT PRIMARY KEY,
                    workflow_job_id TEXT NOT NULL,
                    workflow_step_id TEXT NOT NULL,
                    step_kind TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    activation_idempotency_key TEXT NOT NULL,
                    binding_json TEXT NOT NULL,
                    invocation_id TEXT,
                    provider_id TEXT,
                    provider_instance_id TEXT,
                    execution_constraints_digest TEXT NOT NULL,
                    workspace_ref TEXT NOT NULL,
                    operation_digest TEXT,
                    check_definition_digest TEXT,
                    hmac_key_id TEXT NOT NULL DEFAULT 'default',
                    lease_token_digest TEXT NOT NULL,
                    started_unix INTEGER NOT NULL DEFAULT 0,
                    runtime_accounted_seconds INTEGER NOT NULL DEFAULT 0,
                    lease_expires_unix INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    next_sequence INTEGER NOT NULL DEFAULT 0,
                    terminal_record_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (workflow_job_id, step_kind, activation_idempotency_key),
                    UNIQUE (workflow_job_id, workflow_step_id, attempt_number)
                );
                CREATE INDEX IF NOT EXISTS runtime_claim_active_step
                ON runtime_workflow_claims(workflow_job_id, workflow_step_id, status);
                CREATE UNIQUE INDEX IF NOT EXISTS runtime_provider_invocation_once
                ON runtime_workflow_claims(workflow_job_id, invocation_id)
                WHERE invocation_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS runtime_workflow_records (
                    claim_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (claim_id, record_id),
                    UNIQUE (claim_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS runtime_artifact_edges (
                    workflow_job_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    identity_digest TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    PRIMARY KEY (workflow_job_id, edge_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS runtime_post_terminal_activity (
                    workflow_job_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    PRIMARY KEY (workflow_job_id, record_id)
                );
                """
            )
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(runtime_workflow_claims)"
                ).fetchall()
            }
            if "hmac_key_id" not in columns:
                connection.execute(
                    "ALTER TABLE runtime_workflow_claims ADD COLUMN hmac_key_id TEXT NOT NULL DEFAULT 'default'"
                )
            if "started_unix" not in columns:
                connection.execute(
                    "ALTER TABLE runtime_workflow_claims ADD COLUMN started_unix INTEGER NOT NULL DEFAULT 0"
                )
            if "runtime_accounted_seconds" not in columns:
                connection.execute(
                    "ALTER TABLE runtime_workflow_claims ADD COLUMN runtime_accounted_seconds INTEGER NOT NULL DEFAULT 0"
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException as error:
                if getattr(error, "commit_transaction", False):
                    self._conn.commit()
                else:
                    self._conn.rollback()
                raise
            else:
                self._conn.commit()

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
        """Provide one consistent read snapshot without taking a write reservation."""
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
