"""Frozen media profile v2 and deterministic conformance evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .media_profile import ProbeRunner, ProbeUnavailable, build_media_identity

_MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".mxf": "application/mxf", ".r3d": "application/x-red-r3d"}


def _schema(name: str) -> dict[str, Any]:
    return json.loads((resources.files("pdx_adapter_media.schemas") / name).read_text(encoding="utf-8"))


def _registry() -> Registry:
    registry = Registry()
    for name in ("pdx_media_technical_profile_v2.json", "pdx_media_conformance_request_v1.json", "pdx_media_conformance_result_v1.json"):
        schema = _schema(name)
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
    return registry


def _validate(name: str, value: Mapping[str, Any]) -> None:
    errors = sorted(Draft202012Validator(_schema(name), registry=_registry()).iter_errors(value), key=lambda item: list(item.absolute_path))
    if errors:
        raise ValueError("invalid media conformance contract: " + "; ".join(error.message for error in errors))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _fps(value: Any) -> float | None:
    if isinstance(value, str) and "/" in value:
        numerator, denominator = value.split("/", 1)
        top, bottom = _number(numerator), _number(denominator)
        return top / bottom if top is not None and bottom not in (None, 0) else None
    return _number(value)


def build_technical_profile_v2(path: str | Path, runner: ProbeRunner) -> dict[str, Any]:
    """Measure a local media file into the frozen v2 fact-only profile."""
    source = Path(path).resolve(strict=True)
    identity_v1 = build_media_identity(source)
    identity = {
        "name": identity_v1["name"], "extension": identity_v1["extension"],
        "size_bytes": identity_v1["size"], "sha256": identity_v1["sha256"],
        "media_type": _MEDIA_TYPES.get(identity_v1["extension"], "application/octet-stream"),
    }
    if identity["extension"] == ".r3d":
        result = {"schema_version": "pdx_media_technical_profile_v2", "identity": identity, "probe_status": "proxy_required", "streams": [], "analysis_error": "RED SDK or approved proxy required", "interpretation": "none"}
        _validate("pdx_media_technical_profile_v2.json", result)
        return result
    try:
        raw = runner.probe(source)
    except ProbeUnavailable:
        result = {"schema_version": "pdx_media_technical_profile_v2", "identity": identity, "probe_status": "analyzer_unavailable", "streams": [], "analysis_error": "media analyzer unavailable", "interpretation": "none"}
        _validate("pdx_media_technical_profile_v2.json", result)
        return result
    raw_format = raw.get("format") if isinstance(raw.get("format"), Mapping) else {}
    raw_streams = raw.get("streams") if isinstance(raw.get("streams"), list) else []
    streams = []
    for index, item in enumerate(raw_streams[:128]):
        if not isinstance(item, Mapping):
            continue
        stream: dict[str, Any] = {"index": int(item.get("index", index)), "kind": item.get("codec_type") if item.get("codec_type") in {"video", "audio", "subtitle", "data", "attachment"} else "unknown", "codec": str(item.get("codec_name") or "unknown")[:128]}
        for key in ("width", "height", "channels", "sample_rate", "nb_frames"):
            number = _number(item.get(key))
            if number is not None and number >= 0:
                target = {"sample_rate": "sample_rate_hz", "nb_frames": "frame_count"}.get(key, key)
                stream[target] = int(number)
        frame_rate = _fps(item.get("avg_frame_rate") or item.get("r_frame_rate"))
        if frame_rate is not None and frame_rate > 0:
            stream["fps"] = frame_rate
        for source_key, target_key in (("loudness_lufs", "loudness_lufs"), ("silence_ratio", "silence_ratio"), ("clipping_ratio", "clipping_ratio")):
            number = _number(item.get(source_key))
            if number is not None:
                stream[target_key] = number
        streams.append(stream)
    result = {
        "schema_version": "pdx_media_technical_profile_v2", "identity": identity,
        "probe_status": "measured", "container": str(raw_format.get("format_name") or "unknown")[:128],
        "duration_seconds": _number(raw_format.get("duration")) or 0.0,
        "streams": streams, "interpretation": "none",
    }
    for key in ("black_frame_ratio", "freeze_ranges"):
        if key in raw:
            result[key] = raw[key]
    _validate("pdx_media_technical_profile_v2.json", result)
    return result


def not_evaluated_result(profile: Mapping[str, Any]) -> dict[str, Any]:
    _validate("pdx_media_technical_profile_v2.json", profile)
    result = {"schema_version": "pdx_media_conformance_result_v1", "profile_digest": _digest(profile), "evaluation_status": "not_evaluated", "issues": [], "interpretation": "none"}
    _validate("pdx_media_conformance_result_v1.json", result)
    return result


def evaluate_media_conformance(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate measured facts against an explicit expected block."""
    _validate("pdx_media_conformance_request_v1.json", request)
    profile, expected = request["profile"], request["expected"]
    issues: list[dict[str, Any]] = []

    def issue(code: str, location: str, message: str, *, retryable: bool = False) -> None:
        issues.append({"code": code, "location": location, "message": message, "retryable": retryable})

    if profile["probe_status"] != "measured":
        issue("MEDIA_ANALYZER_UNAVAILABLE", "analyzer", profile.get("analysis_error", "media analyzer unavailable"), retryable=profile["probe_status"] == "analyzer_unavailable")
        status = "evaluation_failed"
    else:
        containers = {item.strip().casefold() for item in profile.get("container", "").split(",")}
        if "containers" in expected and not containers.intersection(item.casefold() for item in expected["containers"]):
            issue("MEDIA_CONTAINER_MISMATCH", "container", "container is not allowed")
        video = next((item for item in profile["streams"] if item["kind"] == "video"), None)
        audio = [item for item in profile["streams"] if item["kind"] == "audio"]
        if video is None and any(key in expected for key in ("video_codecs", "width", "height", "fps")):
            issue("MEDIA_DECODE_FAILED", "streams/video", "video stream is missing")
        if video is not None:
            if "video_codecs" in expected and video["codec"].casefold() not in {item.casefold() for item in expected["video_codecs"]}:
                issue("MEDIA_CODEC_MISMATCH", f"streams/{video['index']}/codec", "video codec is not allowed")
            if any(video.get(key) != expected[key] for key in ("width", "height") if key in expected):
                issue("MEDIA_DIMENSIONS_MISMATCH", f"streams/{video['index']}/dimensions", "video dimensions differ")
            if "fps" in expected and ("fps" not in video or abs(video["fps"] - expected["fps"]) > expected.get("fps_tolerance", 0)):
                issue("MEDIA_FPS_MISMATCH", f"streams/{video['index']}/fps", "frame rate is outside tolerance")
        if "duration_seconds" in expected and abs(profile["duration_seconds"] - expected["duration_seconds"]) > expected.get("duration_tolerance_seconds", 0):
            issue("MEDIA_DURATION_MISMATCH", "duration_seconds", "duration is outside tolerance")
        audio_policy = expected.get("audio")
        if (audio_policy == "forbidden" and audio) or (audio_policy == "required" and not audio):
            issue("MEDIA_AUDIO_POLICY_MISMATCH", "streams/audio", "audio stream policy differs")
        for field, code in (("max_black_frame_ratio", "MEDIA_BLACK_FRAME_LIMIT_EXCEEDED"),):
            if field in expected:
                measured = profile.get("black_frame_ratio")
                if measured is None:
                    issue("MEDIA_ANALYZER_UNAVAILABLE", "black_frame_ratio", "required measurement is unavailable", retryable=True)
                elif measured > expected[field]:
                    issue(code, "black_frame_ratio", "black-frame ratio exceeds limit")
        if "max_freeze_duration_seconds" in expected:
            ranges = profile.get("freeze_ranges")
            if ranges is None:
                issue("MEDIA_ANALYZER_UNAVAILABLE", "freeze_ranges", "required measurement is unavailable", retryable=True)
            elif any(item["duration_seconds"] > expected["max_freeze_duration_seconds"] for item in ranges):
                issue("MEDIA_FREEZE_LIMIT_EXCEEDED", "freeze_ranges", "freeze duration exceeds limit")
        status = "evaluation_failed" if any(item["code"] in {"MEDIA_ANALYZER_UNAVAILABLE", "MEDIA_DECODE_FAILED"} for item in issues) else ("does_not_conform" if issues else "conforms")
    result = {
        "schema_version": "pdx_media_conformance_result_v1", "request_id": request["request_id"],
        "profile_digest": _digest(profile), "expected_digest": _digest(expected),
        "evaluation_status": status, "issues": issues, "interpretation": "none",
    }
    _validate("pdx_media_conformance_result_v1.json", result)
    return result
