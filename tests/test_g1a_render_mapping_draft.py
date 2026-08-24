from __future__ import annotations

import json
from pathlib import Path

from pdx_artifact_core import validate_step_receipt, validate_tool_request, validate_tool_result

ROOT = Path(__file__).resolve().parents[1]
G1A = ROOT / "adapters" / "prodocux" / "fixtures" / "g1a"


def _load(name: str) -> dict:
    return json.loads((G1A / name).read_text(encoding="utf-8"))


def test_g1a_render_mapping_fixtures_are_draft_and_kernel_envelope_is_artifact_only() -> None:
    provenance = _load("provenance.json")
    assert provenance["status"] == "draft"
    assert provenance["synthetic"] is True
    assert provenance["source_commit"] is None

    request = _load("tool_request.render_artifact.draft.json")
    result = _load("tool_result.render_artifact.draft.json")
    receipt = _load("step_receipt.render_artifact.draft.json")

    assert validate_tool_request(request) == []
    assert validate_tool_result(result) == []
    assert validate_step_receipt(receipt) == []

    kernel = request["inputs"]["kernel_request"]
    dumped = json.dumps(kernel)
    assert "gs://" not in dumped
    assert "X-Goog-Signature" not in dumped
    assert kernel["template"]["artifact"]["uri"].startswith("artifact://")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "RENDERER_NOT_AVAILABLE"
    assert receipt["status"] == "failed"
