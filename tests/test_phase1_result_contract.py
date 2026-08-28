"""Phase 1 additive /result and /results exact response contracts."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, RefResolver
from pdx_artifact_engine.jobs import JobStore
from pdx_artifact_engine.jobs.service import JobService
from pdx_artifact_engine.staging import StagingStore
from pdx_artifact_engine.worker import JobWorker

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
PHASE1 = ROOT / "docs" / "phase1"


def _schema(name: str) -> dict:
    return json.loads((PHASE1 / "schemas" / name).read_text(encoding="utf-8"))


def _validator(schema: dict) -> Draft202012Validator:
    store = {
        schema["$id"]: schema
        for schema in (
            _schema("pdx_internal_job_result_v1.schema.json"),
            _schema("pdx_internal_job_results_v1.schema.json"),
        )
    }
    resolver = RefResolver.from_schema(schema, store=store)
    return Draft202012Validator(
        schema, format_checker=FormatChecker(), resolver=resolver
    )


def test_job_result_example_matches_frozen_phase1_schema() -> None:
    example = json.loads(
        (PHASE1 / "examples" / "job_result.materialized_source.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(_validator(_schema("pdx_internal_job_result_v1.schema.json")).iter_errors(example))
    assert errors == []
    assert example["kind"] == "materialized_source"
    assert example["artifact"]["artifact_id"] in example["artifact"]["uri"]
    assert example["artifact"]["uri"].startswith("artifact://intake/")


def test_processing_output_and_results_list_match_schemas() -> None:
    processing = json.loads(
        (PHASE1 / "examples" / "job_result.processing_output.json").read_text(
            encoding="utf-8"
        )
    )
    results = json.loads(
        (PHASE1 / "examples" / "job_results.list.json").read_text(encoding="utf-8")
    )
    assert (
        list(
            _validator(_schema("pdx_internal_job_result_v1.schema.json")).iter_errors(
                processing
            )
        )
        == []
    )
    assert (
        list(
            _validator(_schema("pdx_internal_job_results_v1.schema.json")).iter_errors(
                results
            )
        )
        == []
    )
    assert processing["kind"] == "processing_output"
    assert processing["artifact"]["uri"].startswith("artifact://derived/")


def test_worker_result_matches_frozen_contract(tmp_path: Path) -> None:
    from tests.test_phase1_dock_worker import FakeKernel, _live_create_body

    store = JobStore(tmp_path / "jobs.sqlite3")
    staging = StagingStore(tmp_path / "staging")
    service = JobService(store=store, staging=staging, contract_root=PHASE0)
    body = _live_create_body()
    service.create(body)
    worker = JobWorker(
        store=store,
        staging=staging,
        service=service,
        kernel=FakeKernel(),
        owner="result-contract",
    )
    finished = worker.run_once()
    assert finished is not None
    assert finished.state == "completed"
    result = service.get_result(body["job_id"])
    errors = list(
        _validator(_schema("pdx_internal_job_result_v1.schema.json")).iter_errors(result)
    )
    assert errors == []
    assert result["kind"] == "materialized_source"
    # Explicit: not extract-blocks output.
    assert "blocks" not in result
    assert "content" not in result
    status = service.get(body["job_id"])
    assert "result" not in status
    assert status["schema_version"] == "pdx_internal_job_status_v1"
    results = service.get_results(body["job_id"])
    assert (
        list(
            _validator(_schema("pdx_internal_job_results_v1.schema.json")).iter_errors(
                results
            )
        )
        == []
    )
    assert [item["kind"] for item in results["results"]] == [
        "materialized_source",
        "processing_output",
    ]
