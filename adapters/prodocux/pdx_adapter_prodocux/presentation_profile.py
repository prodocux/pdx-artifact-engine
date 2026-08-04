"""``prodocux.presentation_profile`` — Kernel PPTX-intake adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .http_client import ProDocuXHttpClient

TOOL_ID = "prodocux.presentation_profile"
MAX_PRESENTATION_BYTES = 32 * 1024 * 1024


class PresentationProfileExecutor:
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
                    "name": "presentation_profile.json",
                    "uri": f"artifact://{TOOL_ID}/presentation_profile.json",
                    "media_type": "application/json",
                }
            ],
            "detail": result["result"],
            "tool_provider": "prodocux_kernel",
            "transport": "http",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        path = Path(str(inputs.get("presentation_path") or ""))
        if not path.is_file():
            raise ValueError("presentation_path must identify an existing file")
        if path.suffix.casefold() != ".pptx":
            raise ValueError("presentation_path must end with .pptx")
        raw = path.read_bytes()
        if len(raw) > MAX_PRESENTATION_BYTES:
            raise ValueError(f"PPTX exceeds {MAX_PRESENTATION_BYTES} bytes")
        response = self.client.profile_presentation(
            document_b64=base64.b64encode(raw).decode("ascii"),
            document_filename=path.name,
        )
        profile = response.get("profile") or {}
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "presentation_profile.json"
        report.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "result": {
                "status": "ok",
                "tool": TOOL_ID,
                "kernel_version": response.get("kernel_version"),
                "slide_count": profile.get("slide_count", 0),
            },
            "files": [report],
            "outputs": {
                "presentation_profile.json": report.as_posix(),
                "profile": profile,
            },
        }


def make_presentation_profile_executor(
    base_url: str | None = None,
) -> PresentationProfileExecutor:
    return PresentationProfileExecutor(
        ProDocuXHttpClient(
            base_url
            or os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )
    )
