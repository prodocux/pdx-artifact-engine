"""Shared input safety for ProDocuX adapter façades."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from pdx_artifact_core.validate import is_forbidden_artifact_uri


def assert_safe_uri(value: str, *, label: str) -> None:
    if is_forbidden_artifact_uri(value):
        raise ValueError(f"{label}: forbidden signed/credentialed URI")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and ("?" in value or "#" in value):
        if is_forbidden_artifact_uri(value):
            raise ValueError(f"{label}: forbidden signed/credentialed URI")


def require_basename(name: str, *, allowed_suffixes: tuple[str, ...]) -> str:
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("filename must be a plain basename")
    lower = name.lower()
    if not any(lower.endswith(suf) for suf in allowed_suffixes):
        raise ValueError(
            f"filename must end with one of {allowed_suffixes}; got {name!r}"
        )
    return name


def decode_bounded_b64(value: str, *, max_bytes: int, label: str = "document_b64") -> bytes:
    raw = base64.b64decode(str(value), validate=True)
    if len(raw) > max_bytes:
        raise ValueError(f"{label} decoded size {len(raw)} exceeds {max_bytes} bytes")
    return raw


def resolve_gs_uri(inputs: Mapping[str, Any], *, key: str = "document_uri") -> str | None:
    uri = inputs.get(key) or inputs.get("pdf_uri")
    if not uri:
        return None
    uri_s = str(uri)
    assert_safe_uri(uri_s, label=key)
    if not uri_s.startswith("gs://"):
        raise ValueError(f"{key} must be gs:// object identity (not a signed URL)")
    return uri_s


def write_bytes_under_output(
    raw: bytes,
    output_dir: Path,
    filename: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    target.write_bytes(raw)
    return target
