from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from pdx_artifact_engine.runtime_workflows import (
    RuntimeWorkflowError,
    RuntimeWorkflowService,
    RuntimeWorkflowStore,
)
from pdx_artifact_engine.runtime_workflows.contracts import validate

ROOT = Path(__file__).resolve().parents[1]
ERRATUM = ROOT / "docs" / "dynamic-dispatch" / "erratum-001"
PACKAGED = (
    ROOT
    / "runtime"
    / "pdx_artifact_engine"
    / "contracts"
    / "runtime_provider_workflow"
)
DISPATCH_PACKAGED = (
    ROOT / "runtime" / "pdx_artifact_engine" / "contracts" / "dynamic_dispatch"
)
SECRET = b"dynamic-dispatch-runtime-test-key-0001"


def _load(relative: str) -> dict:
    return json.loads((ERRATUM / relative).read_text(encoding="utf-8"))


def test_frozen_erratum_schemas_are_packaged_byte_identical() -> None:
    freeze = _load("erratum-freeze.v1.json")
    for filename in freeze["schemas"]:
        assert (PACKAGED / filename).read_bytes() == (
            ERRATUM / "schemas" / filename
        ).read_bytes()


def test_frozen_dispatch_schemas_are_packaged_byte_identical() -> None:
    freeze = json.loads(
        (ROOT / "docs" / "dynamic-dispatch" / "contract-freeze.v1.json").read_text(
            encoding="utf-8"
        )
    )
    for filename in freeze["schemas"]:
        assert (DISPATCH_PACKAGED / filename).read_bytes() == (
            ROOT / "docs" / "dynamic-dispatch" / "schemas" / filename
        ).read_bytes()


def test_v2_create_persists_contract_version_and_returns_v2_state(tmp_path: Path) -> None:
    service = RuntimeWorkflowService(
        RuntimeWorkflowStore(tmp_path / "workflow.sqlite3"), SECRET
    )
    body = _load("examples/workflow-create-request-v2.valid.json")

    status, response = service.create(body)

    assert status == 202
    assert response["workflow_job_id"] == body["plan"]["workflow_job_id"]
    state = service.get_state(body["plan"]["workflow_job_id"])
    plan = service.get_plan(body["plan"]["workflow_job_id"])
    validate("pdx_runtime_provider_workflow_state_v2.schema.json", state)
    validate("pdx_runtime_provider_workflow_plan_v2.schema.json", plan)
    assert state["counters"]["dispatch_attempts"] == 0
    assert state["counters"]["active_dispatches"] == 0
    assert state["counters"]["dispatch_runtime_seconds"] == 0
    with service.store.read_transaction() as connection:
        stored = connection.execute(
            "SELECT contract_version FROM runtime_workflows WHERE workflow_job_id = ?",
            (body["plan"]["workflow_job_id"],),
        ).fetchone()
    assert stored["contract_version"] == 2


def test_existing_database_migrates_to_v1_contract_version(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE runtime_workflows (
            workflow_job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
            operation_digest TEXT NOT NULL, plan_digest TEXT NOT NULL,
            plan_json TEXT NOT NULL, task_id TEXT NOT NULL, run_id TEXT NOT NULL,
            state TEXT NOT NULL, counters_json TEXT NOT NULL,
            terminal_error_json TEXT, receipt_json TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )"""
    )
    connection.commit()
    connection.close()

    store = RuntimeWorkflowStore(path)
    with store.read_transaction() as migrated:
        columns = {
            row[1]: row for row in migrated.execute(
                "PRAGMA table_info(runtime_workflows)"
            ).fetchall()
        }
    assert columns["contract_version"]["dflt_value"] == "1"


def test_dispatch_step_cannot_use_provider_claim_route(tmp_path: Path) -> None:
    service = RuntimeWorkflowService(
        RuntimeWorkflowStore(tmp_path / "workflow.sqlite3"), SECRET
    )
    body = _load("examples/workflow-create-request-v2.valid.json")
    service.create(body)
    activation = json.loads(
        (
            ROOT
            / "docs"
            / "runtime-provider-workflow"
            / "examples"
            / "provider-activation.valid.json"
        ).read_text(encoding="utf-8")
    )["request"]
    activation = deepcopy(activation)
    activation["workflow_step_id"] = "step_dispatch_001"

    try:
        service.activate_provider(
            "workflow_dispatch_001",
            activation,
            authenticated_instance_id=activation["control_plane_instance_id"],
        )
    except RuntimeWorkflowError as error:
        assert error.code == "STEP_KIND_MISMATCH"
    else:
        raise AssertionError("dispatch step was accepted by provider route")
