"""``prodocux.workbook_profile`` — Kernel XLSX-intake adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .http_client import ProDocuXHttpClient

TOOL_ID = "prodocux.workbook_profile"
MAX_WORKBOOK_BYTES = 16 * 1024 * 1024


class WorkbookProfileExecutor:
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
                    "name": "workbook_profile.json",
                    "uri": f"artifact://{TOOL_ID}/workbook_profile.json",
                    "media_type": "application/json",
                }
            ],
            "detail": result["result"],
            "tool_provider": "prodocux_kernel",
            "transport": "http",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        path = Path(str(inputs.get("workbook_path") or ""))
        if not path.is_file():
            raise ValueError("workbook_path must identify an existing file")
        if path.suffix.casefold() != ".xlsx":
            raise ValueError("workbook_path must end with .xlsx")
        raw = path.read_bytes()
        if len(raw) > MAX_WORKBOOK_BYTES:
            raise ValueError(f"XLSX exceeds {MAX_WORKBOOK_BYTES} bytes")
        response = self.client.profile_workbook(
            document_b64=base64.b64encode(raw).decode("ascii"),
            document_filename=path.name,
        )
        profile = response.get("profile") or {}
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "workbook_profile.json"
        report.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "result": {
                "status": "ok",
                "tool": TOOL_ID,
                "kernel_version": response.get("kernel_version"),
                "sheet_count": profile.get("sheet_count", 0),
            },
            "files": [report],
            "outputs": {
                "workbook_profile.json": report.as_posix(),
                "profile": profile,
            },
        }


def make_workbook_profile_executor(base_url: str | None = None) -> WorkbookProfileExecutor:
    return WorkbookProfileExecutor(
        ProDocuXHttpClient(
            base_url
            or os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )
    )
