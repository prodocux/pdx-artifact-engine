"""Minimal HTTP client for ProDocuX Kernel ``/v1`` (stdlib only)."""

from __future__ import annotations

import json
import math
import socket
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
        opener: Any | None = None,
    ) -> None:
        validate_http_service_url(base_url, label="base_url")
        if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s):
            raise ValueError("timeout_s must be a finite positive number")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be a finite positive number")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_s = float(timeout_s)
        self._opener = opener  # injectable for tests (urlopen-compatible)

    def _url(self, path: str) -> str:
        if not path or urlparse(path).scheme or path.startswith(("/", "\\")):
            raise ValueError("path must be relative to the configured Kernel base URL")
        if any(part == ".." for part in path.replace("\\", "/").split("/")):
            raise ValueError("path traversal is not allowed")
        return urljoin(self.base_url, path.lstrip("/"))

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        open_fn = self._opener or urllib.request.urlopen
        try:
            with open_fn(req, timeout=self.timeout_s) as resp:
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
            headers={"Accept": "application/json"},
            method="GET",
        )
        open_fn = self._opener or urllib.request.urlopen
        try:
            with open_fn(req, timeout=self.timeout_s) as resp:
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
