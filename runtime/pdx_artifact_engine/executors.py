from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .paths import ensure_within_directory


def _safe_output_name(raw: str) -> str:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe output name (path traversal rejected): {raw}")
    if not path.parts or path.parts[-1] in {"", ".", ".."}:
        raise ValueError(f"Unsafe output name: {raw}")
    if path.suffix:
        return path.as_posix()
    return f"{path.as_posix()}.json"


def mock_executor(inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Deterministic placeholder executor used when --mock is enabled."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = ensure_within_directory(output_dir, "result.json", label="mock result")
    public_inputs = {key: value for key, value in inputs.items() if not key.startswith("_")}
    result = {"status": "mocked", "inputs": public_inputs}
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    declared = inputs.get("_declared_outputs")
    files = [output_path]
    outputs: dict[str, str] = {"result": output_path.as_posix()}
    if isinstance(declared, list):
        for name in declared:
            raw = str(name)
            safe_name = _safe_output_name(raw)
            path = ensure_within_directory(output_dir, safe_name, label="mock output")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(
                    json.dumps({"status": "mocked", "name": Path(raw).name}, indent=2) + "\n",
                    encoding="utf-8",
                )
            files.append(path)
            outputs[raw] = path.as_posix()
            outputs[path.name] = path.as_posix()
    return {"result": result, "files": files, "outputs": outputs}


def fixture_stage_executor(inputs: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Copy fixture files into the step output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = inputs.get("fixtures")
    if not isinstance(fixtures, dict) or not fixtures:
        raise ValueError("fixture_stage requires inputs.fixtures as a non-empty object")

    staged: dict[str, str] = {}
    files: list[Path] = []
    for role, source in fixtures.items():
        source_path = Path(str(source)).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Fixture missing for '{role}': {source_path}")
        destination = ensure_within_directory(
            output_dir,
            source_path.name,
            label="fixture destination",
        )
        shutil.copy2(source_path, destination)
        staged[role] = destination.as_posix()
        files.append(destination)

    index_path = ensure_within_directory(output_dir, "staged.json", label="fixture index")
    index_path.write_text(json.dumps({"staged": staged}, indent=2) + "\n", encoding="utf-8")
    files.append(index_path)
    return {
        "result": {"status": "staged", "staged": staged},
        "files": files,
        "outputs": staged,
    }


DEFAULT_EXECUTORS = {
    "pdx.fixture_stage": fixture_stage_executor,
}
