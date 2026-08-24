"""``prodocux.render_artifact`` — Kernel Cloud-safe render adapter."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .http_client import ProDocuXHttpClient
from .inputs import assert_safe_uri

TOOL_ID = "prodocux.render_artifact"


def _reject_storage_urls(payload: Mapping[str, Any]) -> None:
    dumped = json.dumps(payload, ensure_ascii=True)
    lowered = dumped.casefold()
    if "gs://" in lowered or "x-goog-signature" in lowered or "x-amz-signature" in lowered:
        raise ValueError("kernel_request must not contain storage URLs or signed URIs")
    if "template_path" in dumped or "output_path" in dumped or "output_uri" in dumped:
        raise ValueError("kernel_request must not include path or output URI fields")


class RenderArtifactExecutor:
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
        artifacts = [
            {
                "name": "render_result.json",
                "uri": f"artifact://{TOOL_ID}/render_result.json",
                "media_type": "application/json",
            }
        ]
        rendered = result["outputs"].get("rendered_file")
        if rendered:
            artifacts.append(
                {
                    "name": Path(str(rendered)).name,
                    "uri": f"artifact://{TOOL_ID}/{Path(str(rendered)).name}",
                    "media_type": result["result"].get("media_type") or "application/octet-stream",
                }
            )
        return {
            "schema_version": "pdx_tool_result_v1",
            "tool": TOOL_ID,
            "status": "ok" if result["result"].get("status") == "completed" else "failed",
            "outputs": result["outputs"],
            "artifacts": artifacts,
            "detail": result["result"],
            "tool_provider": "prodocux_kernel",
            "transport": "http",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        kernel_request = inputs.get("kernel_request")
        if not isinstance(kernel_request, dict):
            raise ValueError("kernel_request must be an object")
        uri = inputs.get("document_uri") or inputs.get("template_uri")
        if uri:
            assert_safe_uri(str(uri), label="uri")
        _reject_storage_urls(kernel_request)
        response = self.client.render_artifact(kernel_request)
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "render_result.json"
        report.write_text(
            json.dumps(response, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        outputs: dict[str, Any] = {"render_result.json": report.as_posix(), "result": response}
        inline = response.get("content_b64")
        if inline:
            name = str((kernel_request.get("output") or {}).get("output_name") or "rendered.bin")
            if "/" in name or "\\" in name or ".." in name:
                raise ValueError("output_name must be a plain basename")
            rendered = output_dir / name
            rendered.write_bytes(base64.b64decode(inline, validate=True))
            outputs["rendered_file"] = rendered.as_posix()
        return {
            "result": {
                "status": response.get("status"),
                "tool": TOOL_ID,
                "kernel_version": response.get("kernel_version"),
                "output_sha256": response.get("output_sha256"),
                "media_type": response.get("media_type"),
            },
            "files": [report],
            "outputs": outputs,
        }


def make_render_artifact_executor(base_url: str | None = None) -> RenderArtifactExecutor:
    return RenderArtifactExecutor(
        ProDocuXHttpClient(
            base_url
            or os.environ.get("PRODOCUX_V1_BASE_URL", "http://127.0.0.1:8900/v1")
        )
    )
