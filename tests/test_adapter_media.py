from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pdx_adapter_media import FfprobeRunner, MediaProfileExecutor, ProbeUnavailable
from pdx_artifact_core import validate_tool_result


class FakeProbe:
    def probe(self, path: Path) -> dict:
        return {
            "format": {"duration": "12.5", "format_name": "mov,mp4"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
        }


class MissingProbe:
    def probe(self, path: Path) -> dict:
        raise ProbeUnavailable("ffprobe is not installed")


class MustNotProbe:
    def probe(self, path: Path) -> dict:
        raise AssertionError("R3D original must not be sent to generic ffprobe")


def test_media_profile_records_identity_and_probe_metadata(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"small-fixture")
    result = MediaProfileExecutor(FakeProbe())(
        {"media_path": str(source)}, tmp_path / "out"
    )
    profile = result["outputs"]["profile"]
    assert result["result"]["status"] == "ok"
    assert profile["identity"]["extension"] == ".mp4"
    assert len(profile["identity"]["sha256"]) == 64
    assert profile["technical_metadata"]["streams"][0]["codec_name"] == "h264"
    assert json.loads((tmp_path / "out" / "media_profile.json").read_text())["interpretation"] == "none"


def test_missing_ffprobe_is_review_not_false_success(tmp_path: Path) -> None:
    source = tmp_path / "clip.mov"
    source.write_bytes(b"small-fixture")
    result = MediaProfileExecutor(MissingProbe())(
        {"media_path": str(source)}, tmp_path / "out"
    )
    assert result["result"]["status"] == "review"
    assert result["outputs"]["profile"]["technical_metadata"] is None
    assert result["outputs"]["profile"]["probe_error"] == "ffprobe unavailable or failed"


def test_r3d_registers_original_without_generic_decode(tmp_path: Path) -> None:
    source = tmp_path / "A001_C001.R3D"
    source.write_bytes(b"camera-original-fixture")
    result = MediaProfileExecutor(MustNotProbe())(
        {"media_path": str(source)}, tmp_path / "out"
    )
    profile = result["outputs"]["profile"]
    assert result["result"]["status"] == "review"
    assert profile["proxy"]["status"] == "required"
    assert profile["technical_metadata"] is None
    assert "RED SDK" in profile["probe_error"]


def test_execute_returns_schema_valid_tool_result(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"small-fixture")
    result = MediaProfileExecutor(FakeProbe()).execute(
        {"tool": "media.technical_profile", "inputs": {"media_path": str(source)}},
        {"output_dir": tmp_path / "out"},
    )
    assert result["status"] == "completed"
    assert validate_tool_result(dict(result)) == []


def test_execute_review_result_conforms_to_tool_result(tmp_path: Path) -> None:
    source = tmp_path / "clip.mov"
    source.write_bytes(b"small-fixture")
    result = MediaProfileExecutor(MissingProbe()).execute(
        {"inputs": {"media_path": str(source)}},
        {"output_dir": tmp_path / "out"},
    )
    assert result["status"] == "completed_with_review"
    assert validate_tool_result(dict(result)) == []


def test_media_path_can_be_constrained_to_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"small-fixture")
    with pytest.raises(ValueError, match="outside configured"):
        MediaProfileExecutor(FakeProbe(), allowed_roots=[allowed])(
            {"media_path": str(outside)}, tmp_path / "out"
        )


def test_probe_metadata_is_allowlisted_and_bounded(tmp_path: Path) -> None:
    class NoisyProbe:
        def probe(self, path: Path) -> dict:
            return {
                "format": {"duration": "1", "tags": {"secret": "drop"}},
                "streams": [
                    {"index": index, "codec_type": "video", "tags": {"drop": True}}
                    for index in range(130)
                ],
            }

    source = tmp_path / "clip.mxf"
    source.write_bytes(b"small-fixture")
    profile = MediaProfileExecutor(NoisyProbe())(
        {"media_path": str(source)}, tmp_path / "out"
    )["outputs"]["profile"]
    metadata = profile["technical_metadata"]
    assert metadata["format"] == {"duration": "1"}
    assert len(metadata["streams"]) == 128
    assert metadata["streams_truncated"] is True
    assert all("tags" not in stream for stream in metadata["streams"])


def test_ffprobe_timeout_becomes_sanitized_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "secret-name.mp4"
    source.write_bytes(b"small-fixture")
    monkeypatch.setattr("shutil.which", lambda executable: "C:/tools/ffprobe.exe")

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            cmd=["ffprobe", str(source), "token=do-not-leak"], timeout=60
        )

    monkeypatch.setattr("subprocess.run", timeout)
    result = MediaProfileExecutor(FfprobeRunner())(
        {"media_path": str(source)}, tmp_path / "out"
    )
    assert result["result"]["status"] == "review"
    assert result["outputs"]["profile"]["probe_error"] == (
        "ffprobe unavailable or failed"
    )
    serialized = json.dumps(
        {"result": result["result"], "profile": result["outputs"]["profile"]}
    )
    assert "token=do-not-leak" not in serialized
    assert "token=do-not-leak" not in (
        tmp_path / "out" / "media_profile.json"
    ).read_text(encoding="utf-8")
