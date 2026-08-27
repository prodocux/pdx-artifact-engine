"""Minimal HTTP client for ProDocuX Kernel ``/v1`` (stdlib only)."""

from __future__ import annotations

import json
import math
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlparse


def validate_http_service_url(value: str, *, label: str) -> str:
    """Validate a configured service URL without exposing embedded secrets."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"{label} must not contain credentials, query, or fragment"
        )
    return value


def build_client_ssl_context(
    *,
    client_cert: str | None = None,
    client_key: str | None = None,
    ca_cert: str | None = None,
) -> ssl.SSLContext | None:
    """Build an optional client TLS context for production mTLS hops."""
    cert = (client_cert or os.environ.get("PRODOCUX_CLIENT_CERT", "")).strip()
    key = (client_key or os.environ.get("PRODOCUX_CLIENT_KEY", "")).strip()
    ca = (ca_cert or os.environ.get("PRODOCUX_CA_CERT", "")).strip()
    if not cert and not key and not ca:
        return None
    if bool(cert) != bool(key):
        raise ValueError("PRODOCUX_CLIENT_CERT and PRODOCUX_CLIENT_KEY must be set together")
    ctx = ssl.create_default_context(cafile=ca or None)
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    return ctx


class ProDocuXHttpError(RuntimeError):
    """Kernel HTTP call failed."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ProDocuXHttpClient:
    """POST/GET against Kernel base URL (e.g. ``http://127.0.0.1:8900/v1``)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8900/v1",
        *,
        timeout_s: float = 60.0,
        bearer_token: str | None = None,
        opener: Any | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        validate_http_service_url(base_url, label="base_url")
        if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be a finite positive number")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be a finite positive number")
        if bearer_token is not None and (
            not isinstance(bearer_token, str) or not bearer_token.strip()
        ):
            raise ValueError("bearer_token must be a non-empty string when set")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_s = float(timeout_s)
        self.bearer_token = bearer_token.strip() if bearer_token else None
        self._ssl_context = ssl_context
        if opener is not None:
            self._opener = opener
        elif ssl_context is not None:
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ssl_context)
            ).open
        else:
            self._opener = None

    def _headers(self, *, accept: str, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": accept}
        if content_type is not None:
            headers["Content-Type"] = content_type
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def _url(self, path: str) -> str:
        if not path or urlparse(path).scheme or path.startswith(("/", "\\")):
            raise ValueError("path must be relative to the configured Kernel base URL")
        if any(part == ".." for part in path.replace("\\", "/").split("/")):
            raise ValueError("path traversal is not allowed")
        return urljoin(self.base_url, path.lstrip("/"))

    def _open(self, req: urllib.request.Request):
        open_fn = self._opener or urllib.request.urlopen
        return open_fn(req, timeout=self.timeout_s)

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers=self._headers(
                accept="application/json", content_type="application/json"
            ),
            method="POST",
        )
        try:
            with self._open(req) as resp:
                raw = resp.read().decode("utf-8")
                status = getattr(resp, "status", None) or resp.getcode()
        except urllib.error.HTTPError as exc:
            raise ProDocuXHttpError(
                f"Kernel HTTP {exc.code} on {path}",
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise ProDocuXHttpError(f"Kernel unreachable on {path}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProDocuXHttpError(f"Kernel timeout on {path}") from exc

        if status and int(status) >= 400:
            raise ProDocuXHttpError(
                f"Kernel HTTP {status} on {path}",
                status=int(status),
            )
        try:
            value = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ProDocuXHttpError(
                f"Kernel returned non-JSON on {path}",
                status=int(status) if status else None,
            ) from exc
        if not isinstance(value, dict):
            raise ProDocuXHttpError(f"Kernel JSON root must be object on {path}")
        return value

    def validate_structure(
        self,
        *,
        document_path: str,
        reference_path: str | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/validate-structure`` — Kernel CONTRACT §4.3."""
        payload: dict[str, Any] = {"document_path": document_path}
        if reference_path:
            payload["reference_path"] = reference_path
        return self.post_json("validate-structure", payload)

    def profile_table(
        self, *, document_b64: str, document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/profile-table``."""
        return self.post_json(
            "intake/profile-table",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
            },
        )

    def extract_pages(
        self, *, document_b64: str, document_filename: str, max_pages: int = 50
    ) -> dict[str, Any]:
        """``POST /v1/intake/extract-pages`` (ProDocuX G2 contract)."""
        return self.post_json(
            "intake/extract-pages",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
                "max_pages": max_pages,
            },
        )

    def extract_content_blocks(
        self, *, document_b64: str, document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/extract-blocks``."""
        return self.post_json(
            "intake/extract-blocks",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
            },
        )

    def materialize_intake(
        self,
        *,
        document_b64: str,
        document_filename: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/intake/materialize`` → opaque ``artifact://`` identity."""
        payload: dict[str, Any] = {
            "document_b64": document_b64,
            "document_filename": document_filename,
            "media_type": media_type,
        }
        if sha256 is not None:
            payload["sha256"] = sha256
        return self.post_json("intake/materialize", payload)

    def extract_content_blocks_from_artifact(
        self, *, document_artifact: dict[str, Any], document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/extract-blocks`` with opaque artifact identity."""
        return self.post_json(
            "intake/extract-blocks",
            {
                "document_filename": document_filename,
                "document_artifact": document_artifact,
            },
        )

    def store_derived(
        self,
        *,
        output_name: str,
        content_b64: str,
        media_type: str,
        sha256: str | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/artifacts/derived`` → opaque ``artifact://derived/…`` identity."""
        payload: dict[str, Any] = {
            "output_name": output_name,
            "content_b64": content_b64,
            "media_type": media_type,
        }
        if sha256 is not None:
            payload["sha256"] = sha256
        return self.post_json("artifacts/derived", payload)

    def render_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/render/artifact``."""
        return self.post_json("render/artifact", payload)

    def get_artifact_bytes(self, artifact_id: str) -> bytes:
        """``GET /v1/render/artifacts/{artifact_id}``."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}", artifact_id):
            raise ValueError("artifact_id is not a safe identifier")
        req = urllib.request.Request(
            self._url(f"render/artifacts/{artifact_id}"),
            headers=self._headers(accept="*/*"),
            method="GET",
        )
        try:
            with self._open(req) as resp:
                raw = resp.read()
                status = getattr(resp, "status", None) or resp.getcode()
        except urllib.error.HTTPError as exc:
            raise ProDocuXHttpError(
                f"Kernel HTTP {exc.code} on render/artifacts",
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise ProDocuXHttpError("Kernel unreachable on render/artifacts") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProDocuXHttpError("Kernel timeout on render/artifacts") from exc
        if status and int(status) >= 400:
            raise ProDocuXHttpError(
                f"Kernel HTTP {status} on render/artifacts",
                status=int(status),
            )
        if not isinstance(raw, (bytes, bytearray)):
            raise ProDocuXHttpError("Kernel artifact body must be bytes")
        return bytes(raw)

    def profile_workbook(
        self, *, document_b64: str, document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/profile-workbook``."""
        return self.post_json(
            "intake/profile-workbook",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
            },
        )

    def profile_document(
        self, *, document_b64: str, document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/profile-document``."""
        return self.post_json(
            "intake/profile-document",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
            },
        )

    def profile_presentation(
        self, *, document_b64: str, document_filename: str
    ) -> dict[str, Any]:
        """``POST /v1/intake/profile-presentation``."""
        return self.post_json(
            "intake/profile-presentation",
            {
                "document_b64": document_b64,
                "document_filename": document_filename,
            },
        )

    def version(self) -> dict[str, Any]:
        """``GET /v1/version``."""
        req = urllib.request.Request(
            self._url("version"),
            headers=self._headers(accept="application/json"),
            method="GET",
        )
        try:
            with self._open(req) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ProDocuXHttpError(
                f"Kernel HTTP {exc.code} on version",
                status=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            raise ProDocuXHttpError("Kernel unreachable on version") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ProDocuXHttpError("Kernel timeout on version") from exc
        try:
            value = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ProDocuXHttpError("Kernel returned non-JSON on version") from exc
        if not isinstance(value, dict):
            raise ProDocuXHttpError("Kernel version response must be object")
        return value
