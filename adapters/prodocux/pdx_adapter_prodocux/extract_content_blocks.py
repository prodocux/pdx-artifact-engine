"""``prodocux.extract_content_blocks`` — Kernel content-block intake adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .http_client import ProDocuXHttpClient
from .inputs import assert_safe_uri, decode_bounded_b64, require_basename

TOOL_ID = "prodocux.extract_content_blocks"
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
_ALLOWED = (".pdf", ".csv", ".docx", ".xlsx", ".pptx")


class ExtractContentBlocksExecutor:
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
        tool = request.get("tool") or request.get("name")
        if tool and tool != TOOL_ID:
            raise ValueError(f"Unsupported tool {tool!r}; expected {TOOL_ID}")
        result = self.run(
            dict(request.get("inputs") or {}),
            Path((context or {}).get("output_dir") or "."),
        )
        return {
            "schema_version": "pdx_tool_result_v1",
            "tool": TOOL_ID,
            "status": "ok",
            "outputs": result["outputs"],
            "artifacts": [
                {
                    "name": "content_blocks.json",
                    "uri": f"artifact://{TOOL_ID}/content_blocks.json",
                    "media_type": "application/json",
                }
            ],
            "detail": result["result"],
            "tool_provider": "prodocux_kernel",
            "transport": "http",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        uri = inputs.get("document_uri")
        if uri:
            assert_safe_uri(str(uri), label="document_uri")
            raise ValueError("document_uri is host-resolved; Kernel accepts only basename + bytes")

        filename: str
        raw: bytes
        if inputs.get("document_b64"):
            filename = require_basename(
                str(inputs.get("document_filename") or "document.bin"),
                allowed_suffixes=_ALLOWED,
            )
            raw = decode_bounded_b64(
                str(inputs["document_b64"]),
                max_bytes=MAX_DOCUMENT_BYTES,
                label="document_b64",
            )
        else:
            path = Path(str(inputs.get("document_path") or ""))
            if not path.is_file():
                raise ValueError("document_path must identify an existing file")
            filename = require_basename(path.name, allowed_suffixes=_ALLOWED)
            raw = path.read_bytes()
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ValueError(f"document exceeds {MAX_DOCUMENT_BYTES} bytes")

        response = self.client.extract_content_blocks(
            document_b64=base64.b64encode(raw).decode("ascii"),
            document_filename=filename,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "content_blocks.json"
        report.write_text(
            json.dumps(response, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        content = response.get("content") or {}
        return {
            "result": {
                "status": "ok",
                "tool": TOOL_ID,
                "kernel_version": response.get("kernel_version"),
                "format": response.get("format"),
                "source_sha256": response.get("source_sha256"),
                "block_count": len(content.get("blocks") or []),
            },
            "files": [report],
            "outputs": {
                "content_blocks.json": report.as_posix(),
                "content": content,
                "text_items": response.get("text_items") or [],
            },
        }


def make_extract_content_blocks_executor(
    base_url: str | None = None,
) -> ExtractContentBlocksExecutor:
    return ExtractContentBlocksExecutor(
        ProDocuXHttpClient(
            base_url
            or os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )
    )
