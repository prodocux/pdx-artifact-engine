"""Private job create/get/cancel/reconcile against Phase 0 E-05 contracts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_engine.jobs import TERMINAL_STATES, JobRecord, JobStore
from pdx_artifact_engine.jobs.result_contract import (
    ResultContractError,
    normalize_result_items,
    validate_result_items,
)
from pdx_artifact_engine.staging import StagingStore


class JobServiceError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status: int,
        request_id: str = "unknown",
        correlation_id: str = "unknown",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        self.correlation_id = correlation_id
        self.retryable = retryable

    def as_error_document(self) -> dict[str, Any]:
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
        }


def default_contract_root() -> Path:
    import os

    env = os.environ.get("PDX_ENGINE_CONTRACT_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "docs" / "phase0"


def _parse_deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class JobService:
    store: JobStore
    staging: StagingStore
    contract_root: Path | None = None

    def __post_init__(self) -> None:
        root = self.contract_root or default_contract_root()
        self._create_schema = json.loads(
            (root / "schemas" / "pdx_internal_job_create_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self._cancel_schema = json.loads(
            (root / "schemas" / "pdx_internal_job_cancel_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self._reconcile_schema = json.loads(
            (root / "schemas" / "pdx_internal_job_reconcile_v1.schema.json").read_text(
                encoding="utf-8"
            )
        )

    def _validate_request(
        self,
        schema: dict[str, Any],
        body: dict[str, Any],
        *,
        path_job_id: str | None = None,
        invalid_message: str = "request document failed schema validation",
    ) -> None:
        request_id = str(body.get("request_id") or "unknown")
        correlation_id = str(body.get("correlation_id") or "unknown")
        if not isinstance(body, dict):
            raise JobServiceError(
                code="REQUEST_INVALID",
                message="request body must be a JSON object",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                body
            )
        )
        if errors:
            raise JobServiceError(
                code="REQUEST_INVALID",
                message=invalid_message,
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if path_job_id is not None and body.get("job_id") != path_job_id:
            raise JobServiceError(
                code="JOB_ID_MISMATCH",
                message="body job_id must equal path job_id",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            )

    def create(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self._validate_request(
            self._create_schema,
            body,
            invalid_message="job create document failed schema validation",
        )
        request_id = str(body.get("request_id") or "unknown")
        correlation_id = str(body.get("correlation_id") or "unknown")

        existing = self.store.get_by_idempotency(body["idempotency_key"])
        if existing is not None:
            if existing.operation_digest != body["operation_digest"]:
                raise JobServiceError(
                    code="IDEMPOTENCY_CONFLICT",
                    message="idempotency key reused with a different operation digest",
                    status=409,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
            return 202, existing.status_document()

        if self.store.get(body["job_id"]) is not None:
            raise JobServiceError(
                code="JOB_EXISTS",
                message="job_id already exists",
                status=409,
                request_id=request_id,
                correlation_id=correlation_id,
            )

        payload = body["payload"]
        try:
            raw = base64.b64decode(payload["content_b64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise JobServiceError(
                code="PAYLOAD_INVALID",
                message="content_b64 is not valid base64",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            ) from exc
        if len(raw) != int(payload["decoded_size_bytes"]):
            raise JobServiceError(
                code="PAYLOAD_SIZE_MISMATCH",
                message="decoded_size_bytes does not match decoded payload",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        digest = hashlib.sha256(raw).hexdigest()
        if digest != body["input_digest"]:
            raise JobServiceError(
                code="DIGEST_MISMATCH",
                message="input_digest does not match decoded payload",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            )

        try:
            handle = self.staging.stage(
                payload=raw,
                media_type=payload["media_type"],
                expected_sha256=digest,
            )
        except ValueError as exc:
            raise JobServiceError(
                code="STAGING_REJECTED",
                message="payload rejected by staging limits",
                status=400,
                request_id=request_id,
                correlation_id=correlation_id,
            ) from exc

        status_doc = {
            "schema_version": "pdx_internal_job_status_v1",
            "job_id": body["job_id"],
            "operation": body["operation"],
            "state": "pending",
            "input_digest": body["input_digest"],
            "operation_digest": body["operation_digest"],
            "idempotency_key": body["idempotency_key"],
            "correlation_id": body["correlation_id"],
            "request_id": body["request_id"],
            "kernel_contract": body["kernel_contract"],
            "staging": handle.as_wire(),
        }
        record = JobRecord(
            job_id=body["job_id"],
            state="pending",
            document=status_doc,
            idempotency_key=body["idempotency_key"],
            operation_digest=body["operation_digest"],
            payload_filename=str(payload["filename"]),
            payload_media_type=str(payload["media_type"]),
            deadline_at=str(body["deadline_at"]),
        )
        self.store.insert(record)
        return 202, status_doc

    def get(self, job_id: str) -> dict[str, Any]:
        record = self.store.get(job_id)
        if record is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id="unknown",
                correlation_id="unknown",
            )
        return record.status_document()

    def get_result(self, job_id: str) -> dict[str, Any]:
        """Phase 1 additive single-item view (prefers materialized_source)."""
        record = self.store.get(job_id)
        if record is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id="unknown",
                correlation_id="unknown",
            )
        try:
            items = validate_result_items(
                normalize_result_items(record.result), job_id=job_id
            )
        except ResultContractError as exc:
            raise JobServiceError(
                code="RESULT_CONTRACT_INVALID",
                message=str(exc),
                status=500,
                request_id=str(record.document.get("request_id") or "unknown"),
                correlation_id=str(
                    record.document.get("correlation_id") or "unknown"
                ),
            ) from exc
        if not items:
            raise JobServiceError(
                code="RESULT_NOT_READY",
                message="job has no result identity yet",
                status=404,
                request_id=str(record.document.get("request_id") or "unknown"),
                correlation_id=str(
                    record.document.get("correlation_id") or "unknown"
                ),
            )
        for item in items:
            if item.get("kind") == "materialized_source":
                return dict(item)
        return dict(items[0])

    def get_results(self, job_id: str) -> dict[str, Any]:
        """Phase 1 additive multi-kind list (not part of frozen status v1).

        Incomplete jobs return ``results=[]`` with success (contrast
        ``get_result`` which raises RESULT_NOT_READY). Array order is
        non-semantic; consumers must select by ``kind``.
        """
        record = self.store.get(job_id)
        if record is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id="unknown",
                correlation_id="unknown",
            )
        try:
            items = validate_result_items(
                normalize_result_items(record.result), job_id=job_id
            )
        except ResultContractError as exc:
            raise JobServiceError(
                code="RESULT_CONTRACT_INVALID",
                message=str(exc),
                status=500,
                request_id=str(record.document.get("request_id") or "unknown"),
                correlation_id=str(
                    record.document.get("correlation_id") or "unknown"
                ),
            ) from exc
        return {
            "schema_version": "pdx_internal_job_results_v1",
            "job_id": job_id,
            "results": items,
        }

    def cancel(self, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self._validate_request(self._cancel_schema, body, path_job_id=job_id)
        record = self.store.get(job_id)
        if record is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id=str(body.get("request_id") or "unknown"),
                correlation_id=str(body.get("correlation_id") or "unknown"),
            )
        if record.state in TERMINAL_STATES:
            raise JobServiceError(
                code="JOB_TERMINAL",
                message="job is already terminal",
                status=409,
                request_id=str(body.get("request_id") or record.document["request_id"]),
                correlation_id=str(
                    body.get("correlation_id") or record.document["correlation_id"]
                ),
            )
        return self._finalize(
            record,
            state="cancelled",
            error=None,
        )

    def reconcile(self, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Drive restart-safe status convergence (not a GET alias)."""
        self._validate_request(self._reconcile_schema, body, path_job_id=job_id)
        request_id = str(body.get("request_id") or "unknown")
        correlation_id = str(body.get("correlation_id") or "unknown")
        record = self.store.get(job_id)
        if record is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if record.state in TERMINAL_STATES:
            return record.status_document()

        now = datetime.now(timezone.utc)
        deadline = _parse_deadline(record.deadline_at)
        staging_meta = record.document.get("staging")
        handle = None
        if isinstance(staging_meta, dict):
            handle = staging_meta.get("handle")

        staging_alive = False
        if isinstance(handle, str):
            staging_alive = self.staging.get_handle(handle) is not None

        if deadline is not None and now > deadline:
            return self._finalize(
                record,
                state="timed_out",
                error={
                    "schema_version": "pdx_internal_error_v1",
                    "ok": False,
                    "code": "DEADLINE_EXCEEDED",
                    "message": "job deadline elapsed during reconcile",
                    "retryable": False,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )

        if not staging_alive:
            return self._finalize(
                record,
                state="failed",
                error={
                    "schema_version": "pdx_internal_error_v1",
                    "ok": False,
                    "code": "STAGING_MISSING",
                    "message": "staging bytes missing or expired; fail closed",
                    "retryable": False,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                },
            )

        # Expired worker lease: return to pending so another worker may claim.
        import time

        now_unix = int(time.time())
        if (
            record.state == "running"
            and record.lease_expires_unix is not None
            and record.lease_expires_unix < now_unix
        ):
            updated = dict(record.document)
            updated["state"] = "pending"
            record.state = "pending"
            record.lease_owner = None
            record.lease_expires_unix = None
            record.document = updated
            self.store.update(record)
            return record.status_document()

        return record.status_document()

    def _finalize(
        self,
        record: JobRecord,
        *,
        state: str,
        error: dict[str, Any] | None,
    ) -> dict[str, Any]:
        staging = record.document.get("staging")
        if isinstance(staging, dict) and "handle" in staging:
            self.staging.delete(str(staging["handle"]))
        updated = dict(record.document)
        updated["state"] = state
        updated.pop("staging", None)
        if error is not None:
            updated["error"] = error
        else:
            updated.pop("error", None)
        record.state = state
        record.document = updated
        record.lease_owner = None
        record.lease_expires_unix = None
        self.store.update(record)
        return updated
