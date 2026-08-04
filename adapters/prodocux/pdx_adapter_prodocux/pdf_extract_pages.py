"""``prodocux.pdf_extract_pages`` — **skill façade** (not Kernel ``/v1``).

Kernel ``POST /v1/extract`` is still 501. This adapter talks to a versioned
HTTP skill façade when ``PRODOCUX_PDF_EXTRACT_URL`` is set; otherwise it runs a
local deterministic path (optional ``pypdf``, else disclosed stub).

Never imports ``prodocux_kernel`` or ``skills.*``.
Security: no arbitrary local paths by default and no signed URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from .http_client import (
    ProDocuXHttpClient,
    ProDocuXHttpError,
    validate_http_service_url,
)
from .inputs import (
    assert_safe_uri,
    decode_bounded_b64,
    require_basename,
    resolve_gs_uri,
    write_bytes_under_output,
)

TOOL_ID = "prodocux.pdf_extract_pages"
LEGACY_TOOL_ID = "prodocux.pdf_extract"
_MAX_B64_BYTES = 8 * 1024 * 1024  # 8 MiB — small-file base64 only
_ALLOW_LOCAL_ENV = "PDX_ALLOW_LOCAL_PDF_PATH"
_URL_ENV = "PRODOCUX_PDF_EXTRACT_URL"


def _sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _extract_with_pypdf(raw: bytes, filename: str) -> dict[str, Any] | None:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return None
    try:
        reader = PdfReader(BytesIO(raw))
        pages: list[dict[str, Any]] = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(
                {
                    "file": filename,
                    "page": i,
                    "text": text,
                    "char_count": len(text),
                }
            )
        return {
            "schema": "pdx_pages_facade_v0",
            "engine": "pypdf",
            "engine_version": "optional",
            "page_count": len(pages),
            "pages": pages,
            "source_files": [
                {
                    "file": filename,
                    "page_count": len(pages),
                    "sha256": _sha256_hex(raw),
                }
            ],
            "errors": {},
        }
    except Exception as exc:  # noqa: BLE001 — façade must not crash caller
        return {
            "schema": "pdx_pages_facade_v0",
            "engine": "pypdf",
            "page_count": 0,
            "pages": [],
            "source_files": [{"file": filename, "sha256": _sha256_hex(raw)}],
            "errors": {"pypdf": str(exc)},
        }


def _stub_document(filename: str, *, sha256: str, reason: str) -> dict[str, Any]:
    return {
        "schema": "pdx_pages_facade_v0",
        "engine": "stub",
        "page_count": 0,
        "pages": [],
        "source_files": [{"file": filename, "sha256": sha256, "page_count": 0}],
        "errors": {},
        "disclosure": reason,
        "requires_live_facade": True,
        "extraction_available": False,
    }


def resolve_pdf_bytes(
    inputs: Mapping[str, Any],
    output_dir: Path,
) -> tuple[bytes | None, str, str | None]:
    """Return (bytes_or_none, filename, gs_uri_or_none).

    Prefer ``pdf_b64`` / ``document_b64``. ``gs://`` returns bytes=None + uri.
    Local ``pdf_path`` only when ``PDX_ALLOW_LOCAL_PDF_PATH=1``.
    """
    filename = require_basename(
        str(inputs.get("pdf_filename") or inputs.get("document_filename") or "input.pdf"),
        allowed_suffixes=(".pdf",),
    )

    b64 = inputs.get("pdf_b64") or inputs.get("document_b64")
    if b64:
        raw = decode_bounded_b64(str(b64), max_bytes=_MAX_B64_BYTES, label="pdf_b64")
        write_bytes_under_output(raw, output_dir / "_upload", filename)
        return raw, filename, None

    gs = resolve_gs_uri(inputs, key="pdf_uri")
    if gs:
        return None, filename, gs

    path_key = None
    for key in ("pdf_path", "source_pdf", "document_path"):
        if inputs.get(key):
            path_key = key
            break
    if path_key:
        if os.environ.get(_ALLOW_LOCAL_ENV, "").strip() not in {"1", "true", "yes"}:
            raise ValueError(
                f"{path_key} rejected: set {_ALLOW_LOCAL_ENV}=1 for colocated "
                "dev only; prefer pdf_b64 or gs:// identity"
            )
        path = Path(str(inputs[path_key]))
        assert_safe_uri(str(path), label=path_key)
        if not path.is_file():
            raise FileNotFoundError(f"{path_key} not found: {path}")
        raw = path.read_bytes()
        if len(raw) > _MAX_B64_BYTES:
            raise ValueError(f"{path_key} size {len(raw)} exceeds {_MAX_B64_BYTES} bytes")
        return raw, path.name if path.suffix.lower() == ".pdf" else filename, None

    raise ValueError(
        "pdf_extract_pages requires pdf_b64, pdf_uri (gs://), or pdf_path "
        f"with {_ALLOW_LOCAL_ENV}=1"
    )


class PdfExtractPagesExecutor:
    """Dispatcher executor + ToolExecutor for the PDF skill façade."""

    def __init__(
        self,
        *,
        facade_url: str | None = None,
        http_client: ProDocuXHttpClient | None = None,
    ) -> None:
        configured_url = facade_url or os.environ.get(_URL_ENV) or ""
        self.facade_url = (
            validate_http_service_url(configured_url, label="facade_url").rstrip("/")
            if configured_url
            else ""
        )
        self.http_client = http_client

    def __call__(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        return self.run(inputs, output_dir)

    def execute(
        self,
        request: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        tool = request.get("tool") or request.get("name")
        if tool and tool not in {TOOL_ID, LEGACY_TOOL_ID}:
            raise ValueError(f"Unsupported tool {tool!r}; expected {TOOL_ID}")
        inputs = dict(request.get("inputs") or {})
        out = Path((context or {}).get("output_dir") or ".")
        result = self.run(inputs, out)
        ok = bool(result.get("result", {}).get("ok"))
        return {
            "schema_version": "pdx_tool_result_v1",
            "tool": TOOL_ID,
            "status": "ok" if ok else "failed",
            "outputs": result.get("outputs") or {},
            "artifacts": [
                {
                    "name": "pages.json",
                    "uri": f"artifact://{TOOL_ID}/pages.json",
                    "media_type": "application/json",
                }
            ],
            "detail": result.get("result"),
            "tool_provider": "skill_facade",
            "transport": "http" if self.facade_url else "in_process",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        raw, filename, gs_uri = resolve_pdf_bytes(inputs, output_dir)

        if self.facade_url:
            document, mode = self._via_http(raw=raw, filename=filename, gs_uri=gs_uri)
        elif gs_uri and raw is None:
            document = _stub_document(
                filename,
                sha256="",
                reason=(
                    f"gs:// identity {gs_uri!r} recorded only; set {_URL_ENV} "
                    "to resolve via skill façade (no signed URL fetch in Core)"
                ),
            )
            mode = "gs_identity_stub"
        elif raw is not None:
            document = _extract_with_pypdf(raw, filename)
            if document is None:
                document = _stub_document(
                    filename,
                    sha256=_sha256_hex(raw),
                    reason=(
                        "No PRODOCUX_PDF_EXTRACT_URL and pypdf not installed; "
                        "stub pages.json only; extraction is unavailable"
                    ),
                )
                mode = "stub"
            elif document.get("errors"):
                mode = "pypdf_error"
            else:
                mode = "pypdf"
        else:
            raise ValueError("internal: no pdf bytes and no gs uri")

        pages_path = output_dir / "pages.json"
        pages_path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ok = bool(document.get("page_count", 0) > 0) and not document.get("errors")
        return {
            "result": {
                "status": "ok" if ok else "failed",
                "ok": ok,
                "mode": mode,
                "tool": TOOL_ID,
                "page_count": document.get("page_count", 0),
                "facade": "skill" if self.facade_url else "local",
                "disclosure": document.get("disclosure"),
            },
            "files": [pages_path],
            "outputs": {
                "pages.json": pages_path.as_posix(),
                "pages": document,
            },
        }

    def _via_http(
        self,
        *,
        raw: bytes | None,
        filename: str,
        gs_uri: str | None,
    ) -> tuple[dict[str, Any], str]:
        import base64
        import urllib.error
        import urllib.request

        payload: dict[str, Any] = {"filename": filename, "tool": TOOL_ID}
        if raw is not None:
            payload["pdf_b64"] = base64.b64encode(raw).decode("ascii")
            payload["sha256"] = _sha256_hex(raw)
        if gs_uri:
            payload["pdf_uri"] = gs_uri

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.facade_url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        open_fn = (self.http_client._opener if self.http_client else None) or urllib.request.urlopen
        timeout = self.http_client.timeout_s if self.http_client else 60.0
        try:
            with open_fn(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ProDocuXHttpError(
                f"pdf_extract façade HTTP {exc.code}",
                status=exc.code,
            ) from exc
        except Exception as exc:
            raise ProDocuXHttpError("pdf_extract façade request failed") from exc

        try:
            response = json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise ProDocuXHttpError("pdf_extract façade returned non-JSON") from exc
        if not isinstance(response, dict):
            raise ProDocuXHttpError("pdf_extract façade returned non-object JSON")
        document = response.get("document")
        if not isinstance(document, dict):
            document = {
                "schema": "pdx_pages_facade_v0",
                "engine": "remote_facade",
                "page_count": 0,
                "pages": [],
                "errors": {"facade": "missing document"},
            }
        return document, "http_facade"


def make_pdf_extract_pages_executor(
    facade_url: str | None = None,
) -> PdfExtractPagesExecutor:
    return PdfExtractPagesExecutor(facade_url=facade_url)
