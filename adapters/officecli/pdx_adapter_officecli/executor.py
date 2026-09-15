"""Fail-closed wrapper around an explicitly provisioned OfficeCLI binary."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FORMATS = {"docx", "xlsx", "pptx"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class OfficeCliAdapterError(RuntimeError):
    """OfficeCLI execution was disabled, unsafe, or produced invalid output."""


@dataclass(frozen=True)
class OfficeCliConfig:
    executable: Path
    executable_sha256: str
    enabled: bool = False
    allow_hosted_runtime: bool = False
    timeout_seconds: int = 180
    max_output_bytes: int = 100 * 1024 * 1024


def build_officecli_command(
    config: OfficeCliConfig, *, target_format: str, title: str, prompt: str, output_dir: Path
) -> list[str]:
    """Build a local-only argv; the caller is still responsible for egress policy."""
    if target_format not in _FORMATS:
        raise OfficeCliAdapterError("unsupported OfficeCLI target format")
    if not title or len(title) > 200 or _CONTROL.search(title):
        raise OfficeCliAdapterError("invalid OfficeCLI title")
    if not prompt or len(prompt) > 20_000 or "\x00" in prompt:
        raise OfficeCliAdapterError("invalid OfficeCLI prompt")
    return [
        str(config.executable), "new", target_format, title, "--prompt", prompt,
        "--out", str(output_dir), "--json", "--no-publish",
    ]


class OfficeCliExecutor:
    def __init__(self, config: OfficeCliConfig) -> None:
        self.config = config

    def __call__(self, inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        if not self.config.enabled:
            raise OfficeCliAdapterError("OfficeCLI adapter is disabled")
        executable = self.config.executable
        if not executable.is_absolute() or not executable.is_file():
            raise OfficeCliAdapterError("OfficeCLI executable must be an existing absolute file")
        observed = hashlib.sha256(executable.read_bytes()).hexdigest()
        if observed != self.config.executable_sha256:
            raise OfficeCliAdapterError("OfficeCLI executable digest mismatch")
        runtime_mode = inputs.get("runtime_mode")
        if runtime_mode not in {"external", "hosted"}:
            raise OfficeCliAdapterError("OfficeCLI runtime mode must be explicit")
        if runtime_mode == "hosted" and not self.config.allow_hosted_runtime:
            raise OfficeCliAdapterError("OfficeCLI hosted runtime is not allowed")
        output_dir.mkdir(parents=True, exist_ok=True)
        command = build_officecli_command(
            self.config,
            target_format=str(inputs.get("target_format", "")),
            title=str(inputs.get("title", "")),
            prompt=str(inputs.get("prompt", "")),
            output_dir=output_dir,
        )
        completed = subprocess.run(
            command,
            cwd=output_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
            shell=False,
        )
        if completed.returncode != 0:
            raise OfficeCliAdapterError("OfficeCLI process failed")
        if len(completed.stdout.encode("utf-8")) > 64 * 1024:
            raise OfficeCliAdapterError("OfficeCLI response exceeded limit")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OfficeCliAdapterError("OfficeCLI did not return bounded JSON") from exc
        if not isinstance(response, dict):
            raise OfficeCliAdapterError("OfficeCLI response must be a JSON object")
        suffix = "." + str(inputs["target_format"])
        files = [
            path for path in output_dir.rglob("*")
            if path.is_file() and not path.is_symlink() and path.suffix.casefold() == suffix
        ]
        if len(files) != 1:
            raise OfficeCliAdapterError("OfficeCLI must produce exactly one requested artifact")
        artifact = files[0].resolve()
        if output_dir.resolve() not in artifact.parents:
            raise OfficeCliAdapterError("OfficeCLI output escaped its private directory")
        if artifact.stat().st_size > self.config.max_output_bytes:
            raise OfficeCliAdapterError("OfficeCLI artifact exceeded limit")
        return {
            "result": {
                "status": "candidate",
                "runtime_mode": runtime_mode,
                "binary_sha256": observed,
                "response_sha256": hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest(),
                "verification_required": True,
            },
            "files": [artifact],
            "outputs": {"candidate": artifact.as_posix()},
        }
