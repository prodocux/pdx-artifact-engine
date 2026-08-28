"""Stdlib HTTP façade for E-05 private job routes."""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pdx_artifact_engine.jobs import JobStore
from pdx_artifact_engine.jobs.service import JobService, JobServiceError
from pdx_artifact_engine.internal_http.auth import (
    auth_profile_ok,
    authenticate_request,
)
from pdx_artifact_engine.staging import StagingStore

_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]+$")

# Engine Phase 0 encoded ceiling + fixed JSON envelope margin (not logged).
_DEFAULT_MAX_ENCODED_BYTES = 44_739_244
_JSON_ENVELOPE_MARGIN_BYTES = 65_536


def max_request_body_bytes() -> int:
    raw = os.environ.get("PDX_ENGINE_MAX_ENCODED_BYTES", "").strip()
    encoded = int(raw) if raw else _DEFAULT_MAX_ENCODED_BYTES
    return encoded + _JSON_ENVELOPE_MARGIN_BYTES


class BodyLimitError(Exception):
    def __init__(self, *, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def as_error_document(self) -> dict[str, Any]:
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": self.code,
            "message": self.message,
            "retryable": False,
            "request_id": "unknown",
            "correlation_id": "unknown",
        }


class InternalJobHandler(BaseHTTPRequestHandler):
    service: JobService

    def log_message(self, format: str, *args: Any) -> None:
        # Never log request bodies; keep access lines minimal.
        return

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or raw_length.strip() == "":
            raise BodyLimitError(
                code="LENGTH_REQUIRED",
                message="Content-Length is required",
                status=411,
            )
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise BodyLimitError(
                code="LENGTH_INVALID",
                message="Content-Length must be a non-negative integer",
                status=400,
            ) from exc
        if length < 0:
            raise BodyLimitError(
                code="LENGTH_INVALID",
                message="Content-Length must be a non-negative integer",
                status=400,
            )
        ceiling = max_request_body_bytes()
        if length > ceiling:
            raise BodyLimitError(
                code="BODY_TOO_LARGE",
                message="request body exceeds Engine encoded payload ceiling",
                status=413,
            )
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise BodyLimitError(
                code="BODY_INCOMPLETE",
                message="request body shorter than Content-Length",
                status=400,
            )
        return json.loads(raw.decode("utf-8"))

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self) -> bool:
        path = urlparse(self.path).path
        if path in {"/health", "/ready"}:
            return True
        error = authenticate_request(self.headers)
        if error is None:
            return True
        status = 503 if error.get("code") == "AUTH_MISCONFIGURED" else 401
        self._send(status, error)
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth_ok():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok", "service": "pdx-artifact-engine"})
            return
        if path == "/ready":
            ok = auth_profile_ok()
            self._send(
                200 if ok else 503,
                {
                    "status": "ready" if ok else "not_ready",
                    "checks": {"auth_profile_ok": ok},
                },
            )
            return
        match = re.fullmatch(r"/internal/v1/jobs/([^/]+)", path)
        if match:
            job_id = match.group(1)
            if not _JOB_ID.fullmatch(job_id):
                self._send(
                    400,
                    {
                        "schema_version": "pdx_internal_error_v1",
                        "ok": False,
                        "code": "JOB_ID_INVALID",
                        "message": "job_id is not a safe identifier",
                        "retryable": False,
                        "request_id": "unknown",
                        "correlation_id": "unknown",
                    },
                )
                return
            try:
                doc = self.service.get(job_id)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return
        result_match = re.fullmatch(r"/internal/v1/jobs/([^/]+)/result", path)
        if result_match:
            job_id = result_match.group(1)
            if not _JOB_ID.fullmatch(job_id):
                self._send(
                    400,
                    {
                        "schema_version": "pdx_internal_error_v1",
                        "ok": False,
                        "code": "JOB_ID_INVALID",
                        "message": "job_id is not a safe identifier",
                        "retryable": False,
                        "request_id": "unknown",
                        "correlation_id": "unknown",
                    },
                )
                return
            try:
                doc = self.service.get_result(job_id)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return
        results_match = re.fullmatch(r"/internal/v1/jobs/([^/]+)/results", path)
        if results_match:
            job_id = results_match.group(1)
            if not _JOB_ID.fullmatch(job_id):
                self._send(
                    400,
                    {
                        "schema_version": "pdx_internal_error_v1",
                        "ok": False,
                        "code": "JOB_ID_INVALID",
                        "message": "job_id is not a safe identifier",
                        "retryable": False,
                        "request_id": "unknown",
                        "correlation_id": "unknown",
                    },
                )
                return
            try:
                doc = self.service.get_results(job_id)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return
        self._send(
            404,
            {
                "schema_version": "pdx_internal_error_v1",
                "ok": False,
                "code": "NOT_FOUND",
                "message": "route not found",
                "retryable": False,
                "request_id": "unknown",
                "correlation_id": "unknown",
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth_ok():
            return
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except BodyLimitError as exc:
            self._send(exc.status, exc.as_error_document())
            return
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(
                400,
                {
                    "schema_version": "pdx_internal_error_v1",
                    "ok": False,
                    "code": "BODY_INVALID",
                    "message": "request body must be JSON",
                    "retryable": False,
                    "request_id": "unknown",
                    "correlation_id": "unknown",
                },
            )
            return

        if path == "/internal/v1/jobs":
            try:
                status, doc = self.service.create(body)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(status, doc)
            return

        cancel = re.fullmatch(r"/internal/v1/jobs/([^/]+)/cancel", path)
        if cancel:
            try:
                doc = self.service.cancel(cancel.group(1), body)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return

        reconcile = re.fullmatch(r"/internal/v1/jobs/([^/]+)/reconcile", path)
        if reconcile:
            try:
                doc = self.service.reconcile(reconcile.group(1), body)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return

        retrieve = re.fullmatch(r"/internal/v1/jobs/([^/]+)/retrieve", path)
        if retrieve:
            try:
                doc = self.service.retrieve(retrieve.group(1), body)
            except JobServiceError as exc:
                self._send(exc.status, exc.as_error_document())
                return
            self._send(200, doc)
            return

        self._send(
            404,
            {
                "schema_version": "pdx_internal_error_v1",
                "ok": False,
                "code": "NOT_FOUND",
                "message": "route not found",
                "retryable": False,
                "request_id": "unknown",
                "correlation_id": "unknown",
            },
        )


def _default_kernel_client() -> Any | None:
    base = os.environ.get("PDX_KERNEL_BASE_URL", "").strip()
    token = os.environ.get("PRODOCUX_BEARER_TOKEN", "").strip()
    if not base or not token:
        return None
    from pdx_adapter_prodocux.http_client import (
        ProDocuXHttpClient,
        build_client_ssl_context,
    )

    ssl_ctx = None
    try:
        ssl_ctx = build_client_ssl_context()
    except ValueError:
        ssl_ctx = None
    return ProDocuXHttpClient(
        base_url=base,
        bearer_token=token,
        ssl_context=ssl_ctx,
    )


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8910,
    db_path: Path,
    staging_root: Path,
    kernel: Any | None = None,
) -> ThreadingHTTPServer:
    store = JobStore(db_path)
    staging = StagingStore(staging_root)
    kernel_client = kernel if kernel is not None else _default_kernel_client()
    service = JobService(store=store, staging=staging, kernel=kernel_client)

    class BoundHandler(InternalJobHandler):
        pass

    BoundHandler.service = service
    return ThreadingHTTPServer((host, port), BoundHandler)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="PDX Engine private E-05 HTTP façade")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument(
        "--db",
        default=os.environ.get("PDX_ENGINE_JOB_DB", "./.pdx-engine/jobs.sqlite3"),
    )
    parser.add_argument(
        "--staging",
        default=os.environ.get(
            "PDX_ENGINE_STAGING_ROOT", "./.pdx-engine/staging"
        ),
    )
    args = parser.parse_args(argv)
    server = make_server(
        host=args.host,
        port=args.port,
        db_path=Path(args.db),
        staging_root=Path(args.staging),
    )
    print(f"pdx-internal listening on http://{args.host}:{args.port}/internal/v1/jobs")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
