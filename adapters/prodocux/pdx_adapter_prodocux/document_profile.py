"""``prodocux.document_profile`` — Kernel DOCX-intake adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .http_client import ProDocuXHttpClient

TOOL_ID = "prodocux.document_profile"
MAX_DOCX_BYTES = 16 * 1024 * 1024


class DocumentProfileExecutor:
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
                    "name": "document_profile.json",
                    "uri": f"artifact://{TOOL_ID}/document_profile.json",
                    "media_type": "application/json",
                }
            ],
            "detail": result["result"],
            "tool_provider": "prodocux_kernel",
            "transport": "http",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        path = Path(str(inputs.get("document_path") or ""))
        if not path.is_file():
            raise ValueError("document_path must identify an existing file")
        if path.suffix.casefold() != ".docx":
            raise ValueError("document_path must end with .docx")
        raw = path.read_bytes()
        if len(raw) > MAX_DOCX_BYTES:
            raise ValueError(f"DOCX exceeds {MAX_DOCX_BYTES} bytes")
        response = self.client.profile_document(
            document_b64=base64.b64encode(raw).decode("ascii"),
            document_filename=path.name,
        )
        profile = response.get("profile") or {}
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "document_profile.json"
        report.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "result": {
                "status": "ok",
                "tool": TOOL_ID,
                "kernel_version": response.get("kernel_version"),
                "paragraph_count": profile.get("paragraph_count", 0),
                "table_count": profile.get("table_count", 0),
            },
            "files": [report],
            "outputs": {
                "document_profile.json": report.as_posix(),
                "profile": profile,
            },
        }


def make_document_profile_executor(base_url: str | None = None) -> DocumentProfileExecutor:
    return DocumentProfileExecutor(
        ProDocuXHttpClient(
            base_url
            or os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )
    )
