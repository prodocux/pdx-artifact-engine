"""Private job worker: claim → Kernel artifact hop → terminal status.

Phase 1 dock slice:

``intake_document``
1. Read Engine staging bytes ephemerally
2. ``POST /v1/intake/materialize`` once (Kernel-owned ``artifact://intake/…``)
3. ``POST /v1/intake/extract-blocks`` with ``document_artifact`` (no b64)
4. Persist extract JSON via ``POST /v1/artifacts/derived`` (``processing_output``)
5. Persist result list; ``GET …/result`` prefers ``materialized_source``

``render_artifact``
1. Staging bytes are the Kernel render request JSON
2. ``POST /v1/render/artifact``
3. Persist ``processing_output`` from Kernel artifact / derived store

``compare_normalized_profiles`` / ``verify_evidence``
1. Staging bytes are the Kernel request JSON
2. ``POST /v1/compare/normalized-profiles`` or ``POST /v1/verify/evidence-bundle``
3. Persist structured JSON via ``POST /v1/artifacts/derived`` as ``processing_output``
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from pdx_artifact_engine.jobs import TERMINAL_STATES, JobRecord, JobStore
from pdx_artifact_engine.jobs.service import JobService
from pdx_artifact_engine.staging import StagingStore


class KernelClient(Protocol):
    def materialize_intake(
        self,
        *,
        document_b64: str,
        document_filename: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]: ...

    def extract_content_blocks_from_artifact(
        self, *, document_artifact: dict[str, Any], document_filename: str
    ) -> dict[str, Any]: ...

    def store_derived(
        self,
        *,
        output_name: str,
        content_b64: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]: ...

    def render_artifact(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def compare_normalized_profiles(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def verify_evidence_bundle(self, payload: dict[str, Any]) -> dict[str, Any]: ...


def _result_item(
    *,
    job_id: str,
    kind: str,
    artifact: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "pdx_internal_job_result_v1",
        "job_id": job_id,
        "kind": kind,
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": artifact["artifact_id"],
            "uri": artifact["uri"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "media_type": artifact["media_type"],
        },
    }


def default_worker_instance_id() -> str:
    """Unique per process instance; hostname alone is not a worker identity."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex}"


@dataclass
class JobWorker:
    store: JobStore
    staging: StagingStore
    service: JobService
    kernel: KernelClient
    owner: str = field(default_factory=default_worker_instance_id)
    lease_seconds: int = 60
    max_attempts: int = 3
    poll_seconds: float = 0.5

    def run_once(self) -> JobRecord | None:
        claimed = self.store.claim_next(
            owner=self.owner,
            lease_seconds=self.lease_seconds,
            max_attempts=self.max_attempts,
        )
        if claimed is None:
            return None
        self._process(claimed)
        return self.store.get(claimed.job_id)

    def run_forever(self, *, max_jobs: int | None = None) -> int:
        done = 0
        while max_jobs is None or done < max_jobs:
            record = self.run_once()
            if record is None:
                time.sleep(self.poll_seconds)
                continue
            done += 1
        return done

    def _process(self, record: JobRecord) -> None:
        lease_token = record.lease_token
        if not lease_token:
            return
        stop = threading.Event()
        lost = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(record.job_id, lease_token, stop, lost),
            daemon=True,
            name=f"pdx-lease-{record.job_id}",
        )
        heartbeat.start()
        try:
            self._process_locked(record, lease_token=lease_token, lost=lost)
        finally:
            stop.set()
            heartbeat.join(timeout=1)

    def _heartbeat(
        self,
        job_id: str,
        lease_token: str,
        stop: threading.Event,
        lost: threading.Event,
    ) -> None:
        interval = max(1, int(self.lease_seconds / 3))
        while not stop.wait(interval):
            renewed = self.store.renew_lease(
                job_id,
                owner=self.owner,
                lease_token=lease_token,
                lease_seconds=self.lease_seconds,
            )
            if not renewed:
                lost.set()
                return

    def _lease_lost(
        self, job_id: str, lease_token: str, lost: threading.Event
    ) -> bool:
        if lost.is_set():
            return True
        if not self.store.holds_lease(
            job_id, owner=self.owner, lease_token=lease_token
        ):
            lost.set()
            return True
        return False

    def _finalize_claim(
        self,
        record: JobRecord,
        *,
        lease_token: str,
        lost: threading.Event,
        state: str,
        error: dict[str, Any] | None,
    ) -> None:
        if self._lease_lost(record.job_id, lease_token, lost):
            return
        applied = self.service._finalize(
            record,
            state=state,
            error=error,
            expected_lease_token=lease_token,
        )
        if applied is None:
            lost.set()

    def _update_claim(
        self,
        record: JobRecord,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> bool:
        if self._lease_lost(record.job_id, lease_token, lost):
            return False
        if not self.store.update(record, expected_lease_token=lease_token):
            lost.set()
            return False
        return True

    def _process_locked(
        self,
        record: JobRecord,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        if self._lease_lost(record.job_id, lease_token, lost):
            return
        latest = self.store.get(record.job_id)
        if latest is None or latest.state in TERMINAL_STATES:
            return
        if latest.state == "cancelled":
            return

        staging = latest.document.get("staging")
        if not isinstance(staging, dict) or "handle" not in staging:
            self._finalize_claim(
                latest,
                lease_token=lease_token,
                lost=lost,
                state="failed",
                error=self._error(latest, "STAGING_MISSING", "staging handle absent"),
            )
            return

        handle = str(staging["handle"])
        payload = self.staging.read_bytes(handle)
        if payload is None:
            self._finalize_claim(
                latest,
                lease_token=lease_token,
                lost=lost,
                state="failed",
                error=self._error(
                    latest, "STAGING_MISSING", "staging bytes missing or expired"
                ),
            )
            return

        digest = hashlib.sha256(payload).hexdigest()
        if digest != latest.document.get("input_digest"):
            self._finalize_claim(
                latest,
                lease_token=lease_token,
                lost=lost,
                state="failed",
                error=self._error(
                    latest, "DIGEST_MISMATCH", "staging digest diverged from job"
                ),
            )
            return

        operation = latest.document.get("operation")
        if operation == "intake_document":
            self._run_intake(
                latest, handle, payload, digest, lease_token=lease_token, lost=lost
            )
            return
        if operation == "render_artifact":
            self._run_render(
                latest, handle, payload, lease_token=lease_token, lost=lost
            )
            return
        if operation == "compare_normalized_profiles":
            self._run_compare(
                latest, handle, payload, lease_token=lease_token, lost=lost
            )
            return
        if operation == "verify_evidence":
            self._run_verify(
                latest, handle, payload, lease_token=lease_token, lost=lost
            )
            return

        self._finalize_claim(
            latest,
            lease_token=lease_token,
            lost=lost,
            state="blocked",
            error=self._error(
                latest,
                "OPERATION_UNSUPPORTED",
                f"worker does not yet execute {operation}",
            ),
        )

    def _run_intake(
        self,
        latest: JobRecord,
        handle: str,
        payload: bytes,
        digest: str,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        document_b64 = base64.b64encode(payload).decode("ascii")
        payload = b""
        try:
            identity = self.kernel.materialize_intake(
                document_b64=document_b64,
                document_filename=latest.payload_filename,
                media_type=latest.payload_media_type,
                sha256=digest,
            )
            document_b64 = ""
            if not str(identity.get("uri", "")).startswith("artifact://"):
                raise RuntimeError("kernel materialize did not return artifact://")
            extract = self.kernel.extract_content_blocks_from_artifact(
                document_artifact=identity,
                document_filename=latest.payload_filename,
            )
            extract_bytes = json.dumps(
                extract, ensure_ascii=True, separators=(",", ":")
            ).encode("utf-8")
            extract_digest = hashlib.sha256(extract_bytes).hexdigest()
            derived = self.kernel.store_derived(
                output_name="content_blocks.json",
                content_b64=base64.b64encode(extract_bytes).decode("ascii"),
                media_type="application/json",
                sha256=extract_digest,
            )
            extract_bytes = b""
            if not str(derived.get("uri", "")).startswith("artifact://derived/"):
                raise RuntimeError("kernel derived store did not return artifact://derived/")
        except Exception:  # noqa: BLE001
            document_b64 = ""
            self._maybe_retry_or_fail(
                latest, lease_token=lease_token, lost=lost
            )
            return

        if self._lease_lost(latest.job_id, lease_token, lost):
            return
        latest = self.store.get(latest.job_id)
        if latest is None:
            return
        if latest.state == "cancelled" or latest.state in TERMINAL_STATES:
            self.staging.delete(handle)
            return
        if self._lease_lost(latest.job_id, lease_token, lost):
            return

        latest.result = [
            _result_item(
                job_id=latest.job_id,
                kind="materialized_source",
                artifact=identity,
            ),
            _result_item(
                job_id=latest.job_id,
                kind="processing_output",
                artifact=derived,
            ),
        ]
        self._finalize_claim(
            latest,
            lease_token=lease_token,
            lost=lost,
            state="completed",
            error=None,
        )

    def _run_render(
        self,
        latest: JobRecord,
        handle: str,
        payload: bytes,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        try:
            request = json.loads(payload.decode("utf-8"))
            if not isinstance(request, dict):
                raise TypeError("render request must be a JSON object")
            output = request.get("output")
            if isinstance(output, dict) and output.get("delivery_mode") != "artifact":
                # Private Engine path always asks Kernel for artifact delivery.
                request = dict(request)
                request["output"] = {
                    **output,
                    "delivery_mode": "artifact",
                }
            response = self.kernel.render_artifact(request)
            artifact = response.get("artifact")
            if isinstance(artifact, dict) and str(artifact.get("uri", "")).startswith(
                "artifact://"
            ):
                processing = artifact
            elif isinstance(response.get("content_b64"), str):
                raw = base64.b64decode(response["content_b64"], validate=True)
                name = "render.bin"
                if isinstance(output, dict) and output.get("output_name"):
                    name = str(output["output_name"])
                processing = self.kernel.store_derived(
                    output_name=_safe_output_name(name),
                    content_b64=base64.b64encode(raw).decode("ascii"),
                    media_type=str(
                        response.get("media_type") or "application/octet-stream"
                    ),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            else:
                raise RuntimeError("kernel render returned neither artifact nor content")
        except Exception:  # noqa: BLE001
            self._maybe_retry_or_fail(
                latest, lease_token=lease_token, lost=lost
            )
            return

        if self._lease_lost(latest.job_id, lease_token, lost):
            return
        latest = self.store.get(latest.job_id)
        if latest is None:
            return
        if latest.state == "cancelled" or latest.state in TERMINAL_STATES:
            self.staging.delete(handle)
            return
        if self._lease_lost(latest.job_id, lease_token, lost):
            return

        latest.result = [
            _result_item(
                job_id=latest.job_id,
                kind="processing_output",
                artifact=processing,
            )
        ]
        self._finalize_claim(
            latest,
            lease_token=lease_token,
            lost=lost,
            state="completed",
            error=None,
        )

    def _run_compare(
        self,
        latest: JobRecord,
        handle: str,
        payload: bytes,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        self._run_kernel_json_operation(
            latest,
            handle,
            payload,
            output_name="normalized_diff_result.json",
            kernel_call=self.kernel.compare_normalized_profiles,
            lease_token=lease_token,
            lost=lost,
        )

    def _run_verify(
        self,
        latest: JobRecord,
        handle: str,
        payload: bytes,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        self._run_kernel_json_operation(
            latest,
            handle,
            payload,
            output_name="evidence_bundle_result.json",
            kernel_call=self.kernel.verify_evidence_bundle,
            lease_token=lease_token,
            lost=lost,
        )

    def _run_kernel_json_operation(
        self,
        latest: JobRecord,
        handle: str,
        payload: bytes,
        *,
        output_name: str,
        kernel_call: Any,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        try:
            request = json.loads(payload.decode("utf-8"))
            if not isinstance(request, dict):
                raise TypeError("kernel request must be a JSON object")
            response = kernel_call(request)
            if not isinstance(response, dict):
                raise TypeError("kernel response must be a JSON object")
            processing = self._persist_kernel_json(response, output_name)
        except Exception:  # noqa: BLE001
            self._maybe_retry_or_fail(
                latest, lease_token=lease_token, lost=lost
            )
            return

        if self._lease_lost(latest.job_id, lease_token, lost):
            return
        latest = self.store.get(latest.job_id)
        if latest is None:
            return
        if latest.state == "cancelled" or latest.state in TERMINAL_STATES:
            self.staging.delete(handle)
            return
        if self._lease_lost(latest.job_id, lease_token, lost):
            return

        latest.result = [
            _result_item(
                job_id=latest.job_id,
                kind="processing_output",
                artifact=processing,
            )
        ]
        self._finalize_claim(
            latest,
            lease_token=lease_token,
            lost=lost,
            state="completed",
            error=None,
        )

    def _persist_kernel_json(
        self, response: dict[str, Any], output_name: str
    ) -> dict[str, Any]:
        result_bytes = json.dumps(
            response, ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        digest = hashlib.sha256(result_bytes).hexdigest()
        derived = self.kernel.store_derived(
            output_name=output_name,
            content_b64=base64.b64encode(result_bytes).decode("ascii"),
            media_type="application/json",
            sha256=digest,
        )
        if not str(derived.get("uri", "")).startswith("artifact://derived/"):
            raise RuntimeError("kernel derived store did not return artifact://derived/")
        return derived

    def _maybe_retry_or_fail(
        self,
        latest: JobRecord,
        *,
        lease_token: str,
        lost: threading.Event,
    ) -> None:
        retryable = latest.attempt_count < self.max_attempts
        if retryable:
            latest.state = "pending"
            latest.lease_owner = None
            latest.lease_expires_unix = None
            latest.lease_token = None
            doc = dict(latest.document)
            doc["state"] = "pending"
            latest.document = doc
            self._update_claim(latest, lease_token=lease_token, lost=lost)
            return
        self._finalize_claim(
            latest,
            lease_token=lease_token,
            lost=lost,
            state="failed",
            error=self._error(
                latest,
                "KERNEL_CALL_FAILED",
                "kernel call failed after attempts",
                retryable=False,
            ),
        )

    def _error(
        self,
        record: JobRecord,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": str(record.document.get("request_id") or "unknown"),
            "correlation_id": str(record.document.get("correlation_id") or "unknown"),
        }


def _safe_output_name(name: str) -> str:
    """Keep only a basename-safe output name for derived store."""
    base = name.replace("\\", "/").split("/")[-1]
    if not base or base in {".", ".."}:
        return "render.bin"
    return base[:127]


def build_default_kernel_client():
    from pdx_adapter_prodocux.http_client import (
        ProDocuXHttpClient,
        build_client_ssl_context,
    )

    base = os.environ.get("PDX_KERNEL_BASE_URL", "http://127.0.0.1:8900/v1")
    token = os.environ.get("PRODOCUX_BEARER_TOKEN", "").strip() or None
    return ProDocuXHttpClient(
        base_url=base,
        bearer_token=token,
        ssl_context=build_client_ssl_context(),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="PDX Engine private job worker")
    parser.add_argument(
        "--db",
        default=os.environ.get("PDX_ENGINE_JOB_DB", "./.pdx-engine/jobs.sqlite3"),
    )
    parser.add_argument(
        "--staging",
        default=os.environ.get("PDX_ENGINE_STAGING_ROOT", "./.pdx-engine/staging"),
    )
    parser.add_argument(
        "--owner",
        default=os.environ.get("PDX_ENGINE_WORKER_OWNER")
        or default_worker_instance_id(),
    )
    parser.add_argument("--max-jobs", type=int, default=None)
    args = parser.parse_args(argv)

    store = JobStore(Path(args.db))
    staging = StagingStore(Path(args.staging))
    service = JobService(store=store, staging=staging)
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=build_default_kernel_client(),
        owner=str(args.owner),
    )
    print(f"pdx-worker owner={args.owner} db={args.db}")
    try:
        worker.run_forever(max_jobs=args.max_jobs)
    except KeyboardInterrupt:
        pass
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
