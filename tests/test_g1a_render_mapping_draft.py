from __future__ import annotations

import json
from pathlib import Path

from pdx_artifact_core import validate_step_receipt, validate_tool_request, validate_tool_result

ROOT = Path(__file__).resolve().parents[1]
G1A = ROOT / "adapters" / "prodocux" / "fixtures" / "g1a"


def _load(name: str) -> dict:
    return json.loads((G1A / name).read_text(encoding="utf-8"))


PDX_COMMIT_A = "cccc9a192d1f773d5bf6b8becbe16e41e3164dd2"


def test_g1a_render_mapping_fixtures_are_frozen_and_kernel_envelope_is_artifact_only() -> None:
    provenance = _load("provenance.json")
    assert provenance["status"] == "frozen"
    assert provenance["synthetic"] is True
    assert provenance["source_commit"] == PDX_COMMIT_A

    request = _load("tool_request.render_artifact.json")
    result = _load("tool_result.render_artifact.json")
    receipt = _load("step_receipt.render_artifact.json")

    assert validate_tool_request(request) == []
    assert validate_tool_result(result) == []
    assert validate_step_receipt(receipt) == []

    kernel = request["inputs"]["kernel_request"]
    dumped = json.dumps(kernel)
    assert "gs://" not in dumped
    assert "X-Goog-Signature" not in dumped
    assert "template" not in kernel
    assert kernel["output"]["delivery_mode"] == "artifact"
    assert result["status"] == "completed"
    assert result["tool_version"] == "0.3.0rc1"
    assert result["artifacts"][0]["uri"].startswith("artifact://")
    assert result["artifacts"][0]["uri"] != "artifact://prodocux.render_artifact/render_result.json"
    assert receipt["status"] == "completed"
    assert receipt["output_digest"] == result["artifacts"][0]["checksum"].split(":", 1)[1]
