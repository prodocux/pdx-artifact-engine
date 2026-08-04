"""Media registration + optional ffprobe metadata; never semantic analysis."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

TOOL_ID = "media.technical_profile"
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mxf", ".r3d"}
CAMERA_RAW_EXTENSIONS = {".r3d"}


class ProbeUnavailable(RuntimeError):
    pass


class ProbeRunner(Protocol):
    def probe(self, path: Path) -> dict[str, Any]: ...


class FfprobeRunner:
    def __init__(self, executable: str = "ffprobe") -> None:
        self.executable = executable

    def probe(self, path: Path) -> dict[str, Any]:
        executable = shutil.which(self.executable)
        if executable is None:
            raise ProbeUnavailable("ffprobe is not installed")
        try:
            process = subprocess.run(
                [
                    executable,
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-show_entries",
                    (
                        "format=format_name,duration,size,bit_rate:"
                        "stream=index,codec_type,codec_name,profile,width,height,"
                        "pix_fmt,r_frame_rate,avg_frame_rate,channels,sample_rate,bit_rate"
                    ),
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProbeUnavailable("ffprobe timed out") from exc
        if process.returncode != 0:
            raise ProbeUnavailable(f"ffprobe failed with exit code {process.returncode}")
        value = json.loads(process.stdout)
        if not isinstance(value, dict):
            raise ProbeUnavailable("ffprobe returned a non-object result")
        return value


def _bounded_probe_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    format_keys = {"format_name", "duration", "size", "bit_rate"}
    stream_keys = {
        "index",
        "codec_type",
        "codec_name",
        "profile",
        "width",
        "height",
        "pix_fmt",
        "r_frame_rate",
        "avg_frame_rate",
        "channels",
        "sample_rate",
        "bit_rate",
    }
    raw_format = value.get("format")
    raw_streams = value.get("streams")
    format_data = (
        {key: raw_format[key] for key in format_keys if key in raw_format}
        if isinstance(raw_format, Mapping)
        else {}
    )
    streams = []
    if isinstance(raw_streams, list):
        for stream in raw_streams[:128]:
            if isinstance(stream, Mapping):
                streams.append(
                    {key: stream[key] for key in stream_keys if key in stream}
                )
    return {
        "format": format_data,
        "streams": streams,
        "streams_truncated": isinstance(raw_streams, list) and len(raw_streams) > 128,
    }


def build_media_identity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "name": path.name,
        "extension": path.suffix.casefold(),
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


class MediaProfileExecutor:
    def __init__(
        self,
        runner: ProbeRunner | None = None,
        *,
        allowed_roots: Iterable[str | Path] | None = None,
    ) -> None:
        self.runner = runner or FfprobeRunner()
        self.allowed_roots = (
            tuple(Path(root).resolve() for root in allowed_roots)
            if allowed_roots is not None
            else None
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
            "status": (
                "completed" if result["result"]["probed"] else "completed_with_review"
            ),
            "outputs": result["outputs"],
            "artifacts": [
                {
                    "name": "media_profile.json",
                    "uri": f"artifact://{TOOL_ID}/media_profile.json",
                    "media_type": "application/json",
                }
            ],
            "tool_provider": "media_adapter",
            "transport": "local_process" if result["result"]["probed"] else "identity_only",
        }

    def run(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        try:
            path = Path(str(inputs.get("media_path") or "")).resolve(strict=True)
        except OSError as exc:
            raise ValueError("media_path must identify an existing file") from exc
        if not path.is_file():
            raise ValueError("media_path must identify an existing file")
        if self.allowed_roots is not None and not any(
            path == root or path.is_relative_to(root) for root in self.allowed_roots
        ):
            raise ValueError("media_path is outside configured media roots")
        suffix = path.suffix.casefold()
        if suffix not in MEDIA_EXTENSIONS:
            raise ValueError(f"unsupported media extension: {suffix}")
        identity = build_media_identity(path)
        technical: dict[str, Any] | None = None
        probe_error: str | None = None
        if suffix in CAMERA_RAW_EXTENSIONS:
            probe_error = "RED SDK or approved proxy required; original not decoded"
        else:
            try:
                technical = _bounded_probe_metadata(self.runner.probe(path))
            except ProbeUnavailable:
                probe_error = "ffprobe unavailable or failed"
            except (json.JSONDecodeError, TypeError, ValueError):
                probe_error = "ffprobe returned invalid metadata"
        profile = {
            "schema_version": "pdx_media_profile_v1",
            "identity": identity,
            "technical_metadata": technical,
            "probe_status": "probed" if technical is not None else "review_required",
            "probe_error": probe_error,
            "proxy": {
                "status": "required" if suffix in CAMERA_RAW_EXTENSIONS else "not_registered",
                "uri": None,
            },
            "interpretation": "none",
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "media_profile.json"
        report.write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        probed = technical is not None
        return {
            "result": {
                "status": "ok" if probed else "review",
                "tool": TOOL_ID,
                "probed": probed,
                "probe_status": profile["probe_status"],
            },
            "files": [report],
            "outputs": {
                "media_profile.json": report.as_posix(),
                "profile": profile,
            },
        }


def make_media_profile_executor() -> MediaProfileExecutor:
    return MediaProfileExecutor()
