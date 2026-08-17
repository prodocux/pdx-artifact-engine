from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pdx_artifact_core import InMemoryEventSink
from pdx_artifact_engine import ArtifactRuntime
from pdx_artifact_engine.registry import SkillDefinition, SkillRegistry


class MemoryStorage:
    def __init__(self, uris: set[str]) -> None:
        self.uris = uris

    def exists(self, uri: str) -> bool:
        return uri in self.uris

    def resolve(self, uri: str) -> dict[str, str]:
        return {"uri": uri}


def _registry() -> SkillRegistry:
    return SkillRegistry(
        [
            SkillDefinition(
                name="emit",
                version="1",
                domain="test",
                description="test",
                entrypoint="test",
                inputs=(),
                outputs=(),
                artifacts=(),
                failure_codes=({"code": "X", "meaning": "x"},),
                verification_hooks=(),
            )
        ]
    )


def _plan() -> dict:
    return {
        "schema_version": "pdx_execution_plan_v1",
        "request_id": "req-events",
        "producer": {"type": "manual"},
        "steps": [{"id": "emit", "kind": "tool", "tool": "emit"}],
    }


def test_runtime_emits_bounded_start_and_finish_events(tmp_path: Path) -> None:
    sink = InMemoryEventSink()
    runtime = ArtifactRuntime(
        _registry(),
        executors={"emit": lambda inputs, out: {"outputs": {}}},
        event_sink=sink,
    )
    runtime.execute_plan(_plan(), tmp_path)
    assert [item["event_type"] for item in sink.events] == [
        "RUN_STARTED",
        "RUN_FINISHED",
    ]
    assert sink.events[-1]["status"] == "completed"


def test_runtime_checks_opaque_artifact_identity_with_storage(tmp_path: Path) -> None:
    uri = "artifact://run/output.json"
    identity = {
        "artifact_id": "output-json",
        "uri": uri,
        "sha256": "a" * 64,
        "size_bytes": 42,
        "media_type": "application/json",
        "created_at": datetime.now(UTC).isoformat(),
    }
    runtime = ArtifactRuntime(
        _registry(),
        executors={
            "emit": lambda inputs, out: {
                "outputs": {},
                "artifacts": [identity],
            }
        },
        storage=MemoryStorage({uri}),
    )
    result = runtime.execute_plan(_plan(), tmp_path)
    assert result["run_manifest"]["status"] == "completed"
    assert (
        result["artifact_manifest"]["provenance"][0]["outputs"]["artifacts"][0]["uri"]
        == uri
    )


def test_missing_or_signed_artifact_identity_fails_closed(tmp_path: Path) -> None:
    signed = "gs://bucket/object?X-Goog-Signature=secret"
    runtime = ArtifactRuntime(
        _registry(),
        executors={
            "emit": lambda inputs, out: {"outputs": {}, "artifacts": [{"uri": signed}]}
        },
        storage=MemoryStorage({signed}),
    )
    assert runtime.execute_plan(_plan(), tmp_path)["run_manifest"]["status"] == "failed"


def test_incomplete_artifact_identity_fails_closed(tmp_path: Path) -> None:
    uri = "artifact://run/output.json"
    runtime = ArtifactRuntime(
        _registry(),
        executors={
            "emit": lambda inputs, out: {
                "outputs": {},
                "artifacts": [{"uri": uri, "sha256": "a" * 64}],
            }
        },
        storage=MemoryStorage({uri}),
    )
    assert runtime.execute_plan(_plan(), tmp_path)["run_manifest"]["status"] == "failed"
