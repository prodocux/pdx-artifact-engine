"""Private job create/get/cancel/reconcile against Phase 0 E-05 contracts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_engine.contracts import load_schema
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


def default_contract_root() -> Path | None:
    import os

    env = os.environ.get("PDX_ENGINE_CONTRACT_ROOT", "").strip()
    if env:
        return Path(env)
    return None


def default_phase3_contract_root() -> Path | None:
    import os

    env = os.environ.get("PDX_ENGINE_PHASE3_CONTRACT_ROOT", "").strip()
    if env:
        return Path(env)
    return None


_RETRIEVAL_TERMINAL_STATES = frozenset({"completed", "completed_with_review"})


def _artifact_identity_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = (
        "schema_version",
        "artifact_id",
        "uri",
        "sha256",
        "size_bytes",
        "media_type",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def _verify_retrieved_bytes(
    kernel_body: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    """Re-decode Kernel bytes and check size, SHA-256, and media type."""
    content_b64 = kernel_body.get("content_b64")
    if not isinstance(content_b64, str) or not content_b64:
        raise ValueError("Kernel retrieval response missing content_b64")
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Kernel retrieval content_b64 is not canonical base64") from exc
    size_bytes = kernel_body.get("size_bytes")
    sha256 = kernel_body.get("sha256")
    media_type = kernel_body.get("media_type")
    if size_bytes != expected.get("size_bytes") or size_bytes != len(raw):
        raise ValueError("Kernel retrieval size mismatch")
    digest = hashlib.sha256(raw).hexdigest()
    if sha256 != expected.get("sha256") or digest != sha256:
        raise ValueError("Kernel retrieval digest mismatch")
    if media_type != expected.get("media_type"):
        raise ValueError("Kernel retrieval media type mismatch")
    return {
        "media_type": media_type,
        "size_bytes": size_bytes,
        "sha256": digest,
        "content_b64": base64.b64encode(raw).decode("ascii"),
    }


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
    phase3_contract_root: Path | None = None
    kernel: Any | None = None

    def __post_init__(self) -> None:
        root = self.contract_root if self.contract_root is not None else default_contract_root()
        phase3 = (
            self.phase3_contract_root
            if self.phase3_contract_root is not None
            else default_phase3_contract_root()
        )
        self._create_schema = load_schema(
            "phase0", "pdx_internal_job_create_v1.schema.json", root=root
        )
        self._cancel_schema = load_schema(
            "phase0", "pdx_internal_job_cancel_v1.schema.json", root=root
        )
        self._reconcile_schema = load_schema(
            "phase0", "pdx_internal_job_reconcile_v1.schema.json", root=root
        )
        self._retrieve_schema = load_schema(
            "phase3",
            "pdx_internal_job_artifact_retrieve_v1.schema.json",
            root=phase3,
        )

    def _validate_request(
        self,
        schema: dict[str, Any],
        body: dict[str, Any],
        *,
        path_job_id: str | None = None,
        invalid_message: str = "request document failed schema validation",
    ) -> None:
        if not isinstance(body, dict):
            raise JobServiceError(
                code="REQUEST_INVALID",
                message="request body must be a JSON object",
                status=400,
                request_id="unknown",
                correlation_id="unknown",
            )
        request_id = str(body.get("request_id") or "unknown")
        correlation_id = str(body.get("correlation_id") or "unknown")
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

    def retrieve(self, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Phase 3 verified bytes: bind job + kind + artifact, then Kernel hop."""
        self._validate_request(
            self._retrieve_schema,
            body,
            path_job_id=job_id,
            invalid_message="artifact retrieve document failed schema validation",
        )
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
        if record.state not in _RETRIEVAL_TERMINAL_STATES:
            raise JobServiceError(
                code="RESULT_NOT_READY",
                message="job is not in a retrievable terminal state",
                status=404,
                request_id=request_id,
                correlation_id=correlation_id,
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
                request_id=request_id,
                correlation_id=correlation_id,
            ) from exc
        kind = str(body["kind"])
        stored = next((item for item in items if item.get("kind") == kind), None)
        if stored is None:
            raise JobServiceError(
                code="RESULT_KIND_MISSING",
                message="job has no result for the requested kind",
                status=404,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if not _artifact_identity_equal(stored["artifact"], body["artifact"]):
            raise JobServiceError(
                code="ARTIFACT_BINDING_MISMATCH",
                message="artifact identity does not match the stored job result",
                status=409,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        if self.kernel is None:
            raise JobServiceError(
                code="KERNEL_UNAVAILABLE",
                message="Kernel retrieval client is not configured",
                status=503,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        try:
            kernel_body = self.kernel.retrieve_artifact(
                request_id=request_id,
                artifact=body["artifact"],
            )
        except Exception as exc:
            from pdx_adapter_prodocux.http_client import ProDocuXHttpError

            if isinstance(exc, ProDocuXHttpError) and exc.status == 413:
                raise JobServiceError(
                    code="ARTIFACT_TOO_LARGE",
                    message="artifact exceeds retrieval byte limit",
                    status=413,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    retryable=False,
                ) from exc
            raise JobServiceError(
                code="KERNEL_RETRIEVAL_FAILED",
                message="Kernel artifact retrieval failed",
                status=502,
                request_id=request_id,
                correlation_id=correlation_id,
                retryable=True,
            ) from exc
        if not _artifact_identity_equal(kernel_body.get("artifact", {}), body["artifact"]):
            raise JobServiceError(
                code="KERNEL_RESPONSE_INVALID",
                message="Kernel retrieval response artifact mismatch",
                status=502,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        try:
            verified = _verify_retrieved_bytes(kernel_body, body["artifact"])
        except ValueError as exc:
            raise JobServiceError(
                code="KERNEL_RESPONSE_INVALID",
                message=str(exc),
                status=502,
                request_id=request_id,
                correlation_id=correlation_id,
            ) from exc
        return {
            "schema_version": "pdx_internal_job_artifact_content_v1",
            "job_id": job_id,
            "kind": kind,
            "artifact": dict(kernel_body["artifact"]),
            "media_type": verified["media_type"],
            "size_bytes": verified["size_bytes"],
            "sha256": verified["sha256"],
            "content_b64": verified["content_b64"],
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

        now = datetime.now(UTC)
        deadline = _parse_deadline(record.deadline_at)
        staging_meta = record.document.get("staging")
        handle = None
        if isinstance(staging_meta, dict):
            handle = staging_meta.get("handle")

        staging_alive = False
        if isinstance(handle, str):
            staging_alive = self.staging.get_handle(handle) is not None

        if deadline is not None and now > deadline:
            return self._reconcile_finalize(
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
                request_id=request_id,
                correlation_id=correlation_id,
            )

        if not staging_alive:
            return self._reconcile_finalize(
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
                request_id=request_id,
                correlation_id=correlation_id,
            )

        # Expired worker lease: CAS back to pending so another worker may claim.
        now_unix = int(time.time())
        if (
            record.state == "running"
            and record.lease_expires_unix is not None
            and record.lease_expires_unix < now_unix
            and record.lease_token
        ):
            self.store.release_expired_lease(
                record.job_id,
                lease_token=record.lease_token,
                now=now_unix,
            )
            return self._current_status(
                record.job_id,
                request_id=request_id,
                correlation_id=correlation_id,
            )

        return record.status_document()

    def _current_status(
        self,
        job_id: str,
        *,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        fresh = self.store.get(job_id)
        if fresh is None:
            raise JobServiceError(
                code="JOB_NOT_FOUND",
                message="job not found",
                status=404,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        return fresh.status_document()

    def _reconcile_finalize(
        self,
        record: JobRecord,
        *,
        state: str,
        error: dict[str, Any] | None,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        token = record.lease_token if record.state == "running" else None
        applied = self._finalize(
            record,
            state=state,
            error=error,
            expected_lease_token=token,
        )
        if applied is not None:
            return applied
        return self._current_status(
            record.job_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _finalize(
        self,
        record: JobRecord,
        *,
        state: str,
        error: dict[str, Any] | None,
        expected_lease_token: str | None = None,
    ) -> dict[str, Any] | None:
        staging = record.document.get("staging")
        handle = None
        if isinstance(staging, dict) and "handle" in staging:
            handle = str(staging["handle"])
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
        record.lease_token = None
        if not self.store.update(record, expected_lease_token=expected_lease_token):
            return None
        if handle is not None:
            self.staging.delete(handle)
        return updated
