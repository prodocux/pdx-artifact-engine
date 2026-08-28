"""SQLite-backed private job rows (Phase 1). Durable state stores handles only."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdx_artifact_engine.jobs.result_contract import (
    normalize_result_items,
    validate_result_items,
)

TERMINAL_STATES = frozenset(
    {
        "completed",
        "completed_with_review",
        "failed",
        "blocked",
        "cancelled",
        "timed_out",
    }
)


@dataclass
class JobRecord:
    job_id: str
    state: str
    document: dict[str, Any]
    idempotency_key: str
    operation_digest: str
    payload_filename: str = "document.bin"
    payload_media_type: str = "application/octet-stream"
    deadline_at: str | None = None
    attempt_count: int = 0
    lease_owner: str | None = None
    lease_expires_unix: int | None = None
    # Single dict (legacy) or list of result items (Phase 1 multi-kind).
    result: dict[str, Any] | list[dict[str, Any]] | None = None

    def status_document(self) -> dict[str, Any]:
        return dict(self.document)


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    operation_digest TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    payload_filename TEXT NOT NULL DEFAULT 'document.bin',
                    payload_media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                    deadline_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_unix INTEGER,
                    result_json TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_idempotency
                ON jobs(idempotency_key)
                """
            )
            self._migrate_columns()
            self._conn.commit()

    def _migrate_columns(self) -> None:
        existing = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        alters = {
            "payload_filename": "TEXT NOT NULL DEFAULT 'document.bin'",
            "payload_media_type": "TEXT NOT NULL DEFAULT 'application/octet-stream'",
            "deadline_at": "TEXT",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "lease_owner": "TEXT",
            "lease_expires_unix": "INTEGER",
            "result_json": "TEXT",
        }
        for name, ddl in alters.items():
            if name not in existing:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}")

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        keys = row.keys()
        result = None
        if "result_json" in keys and row["result_json"]:
            result = json.loads(row["result_json"])
        return JobRecord(
            job_id=row["job_id"],
            state=row["state"],
            document=json.loads(row["document_json"]),
            idempotency_key=row["idempotency_key"],
            operation_digest=row["operation_digest"],
            payload_filename=row["payload_filename"]
            if "payload_filename" in keys and row["payload_filename"]
            else "document.bin",
            payload_media_type=row["payload_media_type"]
            if "payload_media_type" in keys and row["payload_media_type"]
            else "application/octet-stream",
            deadline_at=row["deadline_at"] if "deadline_at" in keys else None,
            attempt_count=int(row["attempt_count"] or 0)
            if "attempt_count" in keys
            else 0,
            lease_owner=row["lease_owner"] if "lease_owner" in keys else None,
            lease_expires_unix=row["lease_expires_unix"]
            if "lease_expires_unix" in keys
            else None,
            result=result,
        )

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_by_idempotency(self, idempotency_key: str) -> JobRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def insert(self, record: JobRecord) -> None:
        dumped = json.dumps(record.document, ensure_ascii=True, separators=(",", ":"))
        if "content_b64" in dumped:
            raise ValueError("REFUSAL_PERSIST_BYTES")
        result_json = self._dump_result(record)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs(
                    job_id, state, idempotency_key, operation_digest, document_json,
                    payload_filename, payload_media_type, deadline_at,
                    attempt_count, lease_owner, lease_expires_unix, result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.job_id,
                    record.state,
                    record.idempotency_key,
                    record.operation_digest,
                    dumped,
                    record.payload_filename,
                    record.payload_media_type,
                    record.deadline_at,
                    record.attempt_count,
                    record.lease_owner,
                    record.lease_expires_unix,
                    result_json,
                ),
            )
            self._conn.commit()

    def update(self, record: JobRecord) -> None:
        dumped = json.dumps(record.document, ensure_ascii=True, separators=(",", ":"))
        if "content_b64" in dumped:
            raise ValueError("REFUSAL_PERSIST_BYTES")
        result_json = self._dump_result(record)
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs
                SET state = ?, document_json = ?, operation_digest = ?,
                    payload_filename = ?, payload_media_type = ?, deadline_at = ?,
                    attempt_count = ?, lease_owner = ?, lease_expires_unix = ?,
                    result_json = ?
                WHERE job_id = ?
                """,
                (
                    record.state,
                    dumped,
                    record.operation_digest,
                    record.payload_filename,
                    record.payload_media_type,
                    record.deadline_at,
                    record.attempt_count,
                    record.lease_owner,
                    record.lease_expires_unix,
                    result_json,
                    record.job_id,
                ),
            )
            self._conn.commit()

    def _dump_result(self, record: JobRecord) -> str | None:
        if record.result is None:
            return None
        items = validate_result_items(
            normalize_result_items(record.result), job_id=record.job_id
        )
        record.result = items
        result_json = json.dumps(items, ensure_ascii=True, separators=(",", ":"))
        if "content_b64" in result_json:
            raise ValueError("REFUSAL_PERSIST_BYTES")
        return result_json

    def claim_next(
        self,
        *,
        owner: str,
        lease_seconds: int = 60,
        max_attempts: int = 3,
        now: int | None = None,
    ) -> JobRecord | None:
        """Atomically claim one pending (or expired-lease running) job."""
        now_unix = int(time.time() if now is None else now)
        lease_expires = now_unix + lease_seconds
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE (
                    state = 'pending'
                    OR (
                        state = 'running'
                        AND lease_expires_unix IS NOT NULL
                        AND lease_expires_unix < ?
                    )
                )
                AND attempt_count < ?
                ORDER BY rowid ASC
                LIMIT 1
                """,
                (now_unix, max_attempts),
            ).fetchone()
            if row is None:
                return None
            record = self._row_to_record(row)
            previous_attempts = record.attempt_count
            record.state = "running"
            record.attempt_count += 1
            record.lease_owner = owner
            record.lease_expires_unix = lease_expires
            doc = dict(record.document)
            doc["state"] = "running"
            if "run_id" not in doc:
                doc["run_id"] = f"run_{record.job_id}_{record.attempt_count}"
            record.document = doc
            dumped = json.dumps(doc, ensure_ascii=True, separators=(",", ":"))
            updated = self._conn.execute(
                """
                UPDATE jobs
                SET state = ?, document_json = ?, attempt_count = ?,
                    lease_owner = ?, lease_expires_unix = ?
                WHERE job_id = ?
                  AND attempt_count = ?
                  AND (
                    state = 'pending'
                    OR (
                        state = 'running'
                        AND lease_expires_unix IS NOT NULL
                        AND lease_expires_unix < ?
                    )
                  )
                """,
                (
                    record.state,
                    dumped,
                    record.attempt_count,
                    record.lease_owner,
                    record.lease_expires_unix,
                    record.job_id,
                    previous_attempts,
                    now_unix,
                ),
            )
            if updated.rowcount != 1:
                self._conn.rollback()
                return None
            self._conn.commit()
            return record

    def renew_lease(
        self,
        job_id: str,
        *,
        owner: str,
        lease_seconds: int = 60,
        now: int | None = None,
    ) -> bool:
        """Extend a running lease only if this owner still holds it."""
        now_unix = int(time.time() if now is None else now)
        lease_expires = now_unix + lease_seconds
        with self._lock:
            updated = self._conn.execute(
                """
                UPDATE jobs
                SET lease_expires_unix = ?
                WHERE job_id = ? AND lease_owner = ? AND state = 'running'
                """,
                (lease_expires, job_id, owner),
            )
            self._conn.commit()
            return updated.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._conn.close()
