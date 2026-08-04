"""``prodocux.validate_structure`` → Kernel ``POST /v1/validate-structure``.

Security:
- Plan/tool inputs must not carry signed URLs or credentialed URIs.
- Kernel today accepts ``document_path`` (server-local). This adapter treats
  that path as an **operator/colocated Kernel path**, not a client-uploaded
  arbitrary filesystem path to be persisted in manifests.
- Preferred future inputs: multipart / ``gs://`` identity / small base64 via a
  Kernel façade upgrade; until then local/dev uses ``document_path``.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from pdx_artifact_core.validate import is_forbidden_artifact_uri

from .http_client import ProDocuXHttpClient, ProDocuXHttpError

TOOL_ID = "prodocux.validate_structure"
_MAX_B64_BYTES = 2 * 1024 * 1024  # 2 MiB decoded — small-file only


def _assert_safe_uri(value: str, *, label: str) -> None:
    if is_forbidden_artifact_uri(value):
        raise ValueError(f"{label}: forbidden signed/credentialed URI")
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and ("?" in value or "#" in value):
        # Belt-and-suspenders beyond marker scan
        if is_forbidden_artifact_uri(value):
            raise ValueError(f"{label}: forbidden signed/credentialed URI")


def resolve_document_path_for_kernel(
    inputs: Mapping[str, Any],
    output_dir: Path,
) -> tuple[str, str | None]:
    """Return (document_path, reference_path) for Kernel JSON body.

    Allowed:
    - ``document_path`` / ``reference_path``: Kernel-local paths (dev/colocated)
    - ``document_b64`` (+ optional ``document_filename``): write under output_dir
      then pass that local path (only useful when Kernel shares the filesystem)
    - ``document_uri`` starting with ``gs://``: passed through as identity string
      only if Kernel accepts it as ``document_path`` (opaque identity — no signing)
    """
    ref = inputs.get("reference_path")
    reference_path = str(ref) if ref else None
    if reference_path:
        _assert_safe_uri(reference_path, label="reference_path")

    if inputs.get("document_path"):
        path = str(inputs["document_path"])
        _assert_safe_uri(path, label="document_path")
        return path, reference_path

    uri = inputs.get("document_uri")
    if uri:
        uri_s = str(uri)
        _assert_safe_uri(uri_s, label="document_uri")
        if not uri_s.startswith("gs://"):
            raise ValueError(
                "document_uri must be gs:// object identity (not a signed URL)"
            )
        return uri_s, reference_path

    b64 = inputs.get("document_b64")
    if b64:
        raw = base64.b64decode(str(b64), validate=True)
        if len(raw) > _MAX_B64_BYTES:
            raise ValueError(
                f"document_b64 decoded size {len(raw)} exceeds {_MAX_B64_BYTES} bytes"
            )
        name = str(inputs.get("document_filename") or "document.docx")
        if "/" in name or "\\" in name or ".." in name:
            raise ValueError("document_filename must be a plain basename")
        if not name.lower().endswith(".docx"):
            raise ValueError("document_filename must end with .docx")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / name
        target.write_bytes(raw)
        return str(target.resolve()), reference_path

    raise ValueError(
        "validate_structure requires document_path, document_uri (gs://), "
        "or document_b64"
    )


class ValidateStructureExecutor:
    """Dispatcher-compatible executor + ToolExecutor protocol."""

    def __init__(self, client: ProDocuXHttpClient | None = None) -> None:
        self.client = client or ProDocuXHttpClient(
            os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )

    def __call__(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        return self.run(inputs, output_dir)

    def execute(
        self,
        request: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """ToolExecutor: request is ToolRequest-shaped."""
        tool = request.get("tool") or request.get("name")
        if tool and tool != TOOL_ID:
            raise ValueError(f"Unsupported tool {tool!r}; expected {TOOL_ID}")
        inputs = dict(request.get("inputs") or {})
        out = Path((context or {}).get("output_dir") or ".")
        result = self.run(inputs, out)
        return {
            "schema_version": "pdx_tool_result_v1",
            "tool": TOOL_ID,
            "status": "ok" if result.get("result", {}).get("passed") else "failed",
            "outputs": result.get("outputs") or {},
            "artifacts": [
                {"name": Path(p).name, "uri": f"file://{Path(p).as_posix()}"}
                for p in result.get("files") or []
                if not is_forbidden_artifact_uri(f"file://{Path(p).as_posix()}")
            ],
            "detail": result.get("result"),
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        document_path, reference_path = resolve_document_path_for_kernel(
            inputs, output_dir
        )
        try:
            response = self.client.validate_structure(
                document_path=document_path,
                reference_path=reference_path,
            )
        except ProDocuXHttpError:
            raise

        report_path = output_dir / "validate_structure.json"
        report_path.write_text(
            json.dumps(response, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        passed = bool(response.get("passed"))
        return {
            "result": {
                "status": "ok" if passed else "failed",
                "passed": passed,
                "kernel_version": response.get("kernel_version"),
                "invariant_count": len(response.get("invariants") or []),
            },
            "files": [report_path],
            "outputs": {"validate_structure.json": report_path.as_posix()},
        }


def make_validate_structure_executor(
    base_url: str | None = None,
) -> ValidateStructureExecutor:
    url = base_url or os.environ.get(
        "PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1"
    )
    return ValidateStructureExecutor(ProDocuXHttpClient(url))
