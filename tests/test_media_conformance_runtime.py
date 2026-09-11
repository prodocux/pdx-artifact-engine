from __future__ import annotations

import json
from pathlib import Path

from pdx_adapter_media import (
    ProbeUnavailable,
    build_technical_profile_v2,
    evaluate_media_conformance,
    not_evaluated_result,
)


class CompleteProbe:
    def probe(self, path: Path) -> dict:
        return {
            "format": {"duration": "5.0", "format_name": "mov,mp4"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1024, "height": 576, "avg_frame_rate": "24/1", "nb_frames": "120"}],
            "black_frame_ratio": 0.0,
            "freeze_ranges": [],
        }


class MissingProbe:
    def probe(self, path: Path) -> dict:
        raise ProbeUnavailable("not installed")


def _expected() -> dict:
    root = Path(__file__).resolve().parents[1]
    value = json.loads((root / "adapters" / "media" / "examples" / "fsf_broll_expected.v1.json").read_text(encoding="utf-8"))
    return value["expected"]


def test_broll_profile_conforms_to_frozen_expected(tmp_path: Path) -> None:
    source = tmp_path / "shot.mp4"
    source.write_bytes(b"fixture")
    profile = build_technical_profile_v2(source, CompleteProbe())
    result = evaluate_media_conformance({"schema_version": "pdx_media_conformance_request_v1", "request_id": "request:media:001", "profile": profile, "expected": _expected()})
    assert profile["probe_status"] == "measured"
    assert profile["streams"][0]["fps"] == 24
    assert result["evaluation_status"] == "conforms"
    assert result["issues"] == []


def test_measured_mismatch_is_not_execution_failure(tmp_path: Path) -> None:
    source = tmp_path / "shot.mp4"
    source.write_bytes(b"fixture")
    profile = build_technical_profile_v2(source, CompleteProbe())
    expected = {**_expected(), "width": 1920}
    result = evaluate_media_conformance({"schema_version": "pdx_media_conformance_request_v1", "request_id": "request:media:002", "profile": profile, "expected": expected})
    assert result["evaluation_status"] == "does_not_conform"
    assert {item["code"] for item in result["issues"]} == {"MEDIA_DIMENSIONS_MISMATCH"}


def test_missing_analyzer_is_evaluation_failed(tmp_path: Path) -> None:
    source = tmp_path / "shot.mp4"
    source.write_bytes(b"fixture")
    profile = build_technical_profile_v2(source, MissingProbe())
    result = evaluate_media_conformance({"schema_version": "pdx_media_conformance_request_v1", "request_id": "request:media:003", "profile": profile, "expected": _expected()})
    assert result["evaluation_status"] == "evaluation_failed"
    assert result["issues"][0]["code"] == "MEDIA_ANALYZER_UNAVAILABLE"
    assert result["issues"][0]["retryable"] is True


def test_not_requested_has_no_fake_request_or_expected_digest(tmp_path: Path) -> None:
    source = tmp_path / "shot.mp4"
    source.write_bytes(b"fixture")
    result = not_evaluated_result(build_technical_profile_v2(source, CompleteProbe()))
    assert result["evaluation_status"] == "not_evaluated"
    assert "request_id" not in result
    assert "expected_digest" not in result
