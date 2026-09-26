"""SQLite persistence for continuable extraction operations.

Range artifacts are produced outside SQLite.  Their immutable identities are
first staged here, then accepted into the extraction checkpoint by one
``BEGIN IMMEDIATE`` transaction.  An interrupted process can therefore
reconcile staged records without publishing a partial projection.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ContinuableExtractionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init()

    def _init(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS continuable_extractions (
                    operation_id TEXT PRIMARY KEY,
                    creation_digest TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    receipt_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS continuable_extraction_staged_ranges (
                    operation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    expected_revision INTEGER NOT NULL,
                    transition_json TEXT NOT NULL,
                    transition_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    staged_at TEXT NOT NULL,
                    accepted_revision INTEGER,
                    PRIMARY KEY (operation_id, idempotency_key),
                    FOREIGN KEY (operation_id)
                        REFERENCES continuable_extractions(operation_id)
                );
                CREATE INDEX IF NOT EXISTS continuable_staged_pending
                ON continuable_extraction_staged_ranges(operation_id, status, staged_at);
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    @contextmanager
    def read_transaction(self) -> Iterator[sqlite3.Connection]:
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
