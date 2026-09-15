from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pdx_adapter_officecli import (
    OfficeCliAdapterError,
    OfficeCliConfig,
    OfficeCliExecutor,
    build_officecli_command,
)


def _config(binary: Path, **changes: object) -> OfficeCliConfig:
    values = {
        "executable": binary,
        "executable_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "enabled": True,
    }
    values.update(changes)
    return OfficeCliConfig(**values)


def test_command_is_local_only_and_does_not_use_shell_flags(tmp_path: Path) -> None:
    binary = tmp_path / "officecli.exe"
    binary.write_bytes(b"fixture")
    command = build_officecli_command(
        _config(binary), target_format="docx", title="Brief", prompt="Draft it", output_dir=tmp_path / "out"
    )
    assert command[-2:] == ["--json", "--no-publish"]
    assert command[:3] == [str(binary), "new", "docx"]


def test_executor_is_disabled_and_hosted_mode_is_denied_by_default(tmp_path: Path) -> None:
    binary = tmp_path / "officecli.exe"
    binary.write_bytes(b"fixture")
    with pytest.raises(OfficeCliAdapterError, match="disabled"):
        OfficeCliExecutor(_config(binary, enabled=False))({}, tmp_path / "out")
    with pytest.raises(OfficeCliAdapterError, match="hosted"):
        OfficeCliExecutor(_config(binary))(
            {"runtime_mode": "hosted", "target_format": "docx", "title": "A", "prompt": "B"},
            tmp_path / "out",
        )


def test_executor_returns_unverified_candidate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    binary = tmp_path / "officecli.exe"
    binary.write_bytes(b"fixture")
    output = tmp_path / "out"

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert kwargs["shell"] is False
        assert "--no-publish" in command
        output.mkdir(parents=True, exist_ok=True)
        (output / "brief.docx").write_bytes(b"PK\x03\x04candidate")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "ok"}))

    monkeypatch.setattr("pdx_adapter_officecli.executor.subprocess.run", fake_run)
    result = OfficeCliExecutor(_config(binary))(
        {"runtime_mode": "external", "target_format": "docx", "title": "Brief", "prompt": "Draft it"},
        output,
    )
    assert result["result"]["status"] == "candidate"
    assert result["result"]["verification_required"] is True


def test_binary_digest_is_fenced(tmp_path: Path) -> None:
    binary = tmp_path / "officecli.exe"
    binary.write_bytes(b"fixture")
    executor = OfficeCliExecutor(_config(binary))
    binary.write_bytes(b"changed")
    with pytest.raises(OfficeCliAdapterError, match="digest mismatch"):
        executor(
            {"runtime_mode": "external", "target_format": "docx", "title": "A", "prompt": "B"},
            tmp_path / "out",
        )
