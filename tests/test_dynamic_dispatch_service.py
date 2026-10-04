from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest
import rfc8785
from pdx_artifact_engine.dynamic_dispatch import (
    DispatchTool,
    DispatchToolRegistry,
    DynamicDispatchService,
)
from pdx_artifact_engine.internal_http import make_server
from pdx_artifact_engine.runtime_workflows import (
    RuntimeWorkflowError,
    RuntimeWorkflowService,
    RuntimeWorkflowStore,
)

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "docs" / "dynamic-dispatch"
ERRATUM = DISPATCH / "erratum-001"
SECRET = b"dynamic-dispatch-service-test-key-001"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value: object) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _services(tmp_path: Path) -> tuple[RuntimeWorkflowService, DynamicDispatchService]:
    store = RuntimeWorkflowStore(tmp_path / "workflow.sqlite3")
    workflow = RuntimeWorkflowService(store, SECRET)
    dispatch = DynamicDispatchService(store)
    workflow.create(
        _load(ERRATUM / "examples" / "workflow-create-request-v2.valid.json")
    )
    return workflow, dispatch


def _policy_request() -> dict:
    request = _load(DISPATCH / "examples" / "policy-register.valid.json")
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["expression"],
        "properties": {"expression": {"type": "string"}},
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["result"],
        "properties": {"result": {"type": "string"}},
    }
    request["allowed_tools"][0]["input_schema_digest"] = _digest(input_schema)
    request["allowed_tools"][0]["output_schema_digest"] = _digest(output_schema)
    deployment = request["allowed_tools"][0]["deployment"]
    deployment["identity_digest"] = _digest(
        {key: value for key, value in deployment.items() if key != "identity_digest"}
    )
    return request


def _registry(
    request: dict, *, executor=lambda arguments: {"result": "2"}
) -> DispatchToolRegistry:
    definition = deepcopy(request["allowed_tools"][0])
    input_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["expression"],
        "properties": {"expression": {"type": "string"}},
    }
    output_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["result"],
        "properties": {"result": {"type": "string"}},
    }
    return DispatchToolRegistry(
        [
            DispatchTool(
                frozen_definition=definition,
                input_schema=input_schema,
                output_schema=output_schema,
                executor=executor,
            )
        ]
    )


def _decision(policy: dict) -> dict:
    receipt = _load(DISPATCH / "examples" / "decision-receipt.valid.json")
    for key in (
        "workflow_job_id", "workflow_step_id", "dispatch_policy_id",
        "policy_revision_epoch", "policy_digest",
    ):
        receipt[key] = policy[key]
    proposal_schema = (
        DISPATCH / "schemas" / "pdx_dynamic_dispatch_tool_proposal_v1.schema.json"
    )
    receipt["proposal_schema_digest"] = hashlib.sha256(
        proposal_schema.read_bytes()
    ).hexdigest()
    receipt["arguments_digest"] = _digest(receipt["arguments"])
    receipt["canonical_proposal_digest"] = _digest(
        {
            "proposal_schema_id": receipt["proposal_schema_id"],
            "proposal_schema_digest": receipt["proposal_schema_digest"],
            "tool_name": receipt["tool_name"],
            "arguments": receipt["arguments"],
        }
    )
    receipt["decision_receipt_digest"] = _digest(
        {
            key: value
            for key, value in receipt.items()
            if key != "decision_receipt_digest"
        }
    )
    return {
        "schema_version": "pdx_dynamic_dispatch_decision_import_request_v1",
        "request_id": "request_decision_import_001",
        "workflow_job_id": receipt["workflow_job_id"],
        "workflow_step_id": receipt["workflow_step_id"],
        "source_manifest_artifact": receipt["source_manifest_artifact"],
        "decision_receipt": receipt,
        "caller_authority_id": "control-plane-01",
    }


def _allocated_dispatch(
    tmp_path: Path, *, executor=lambda arguments: {"result": "2"}
) -> tuple[RuntimeWorkflowService, DynamicDispatchService, dict, dict]:
    store = RuntimeWorkflowStore(tmp_path / "workflow.sqlite3")
    workflow = RuntimeWorkflowService(store, SECRET)
    workflow.create(
        _load(ERRATUM / "examples" / "workflow-create-request-v2.valid.json")
    )
    request = _policy_request()
    dispatch = DynamicDispatchService(store, _registry(request, executor=executor))
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    decision_request = _decision(policy)
    dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", decision_request,
        authenticated_principal="control-plane-01",
    )
    with store.transaction() as connection:
        connection.execute(
            """UPDATE runtime_workflow_steps SET state = 'succeeded', attempt_count = 1
               WHERE workflow_job_id = ? AND workflow_step_id = ?""",
            ("workflow_dispatch_001", "step_decision_001"),
        )
    activation = _load(DISPATCH / "examples" / "activation-request.valid.json")
    decision = decision_request["decision_receipt"]
    activation.update(
        {
            "source_run_id": decision["source_run_id"],
            "source_plan_digest": decision["source_plan_digest"],
            "decision_receipt_id": decision["decision_receipt_id"],
            "decision_receipt_digest": decision["decision_receipt_digest"],
            "dispatch_policy_id": policy["dispatch_policy_id"],
            "policy_digest_assertion": policy["policy_digest"],
            "policy_revision_epoch": policy["policy_revision_epoch"],
        }
    )
    allocated = dispatch.activate(
        "workflow_dispatch_001", "step_dispatch_001", activation,
        authenticated_principal="control-plane-01",
    )
    return workflow, dispatch, policy, allocated


def test_policy_registration_is_plan_bound_and_exact_retry_is_stable(
    tmp_path: Path,
) -> None:
    _, dispatch = _services(tmp_path)
    request = _policy_request()
    first = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    second = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    assert second == first
    assert first["registered_by"] == "control-plane-01"
    assert first["allowed_tool_names_digest"] == _digest(["calc"])

    mismatch = deepcopy(request)
    mismatch["run_a_plan_digest"] = "f" * 64
    with pytest.raises(RuntimeWorkflowError, match="frozen plan") as caught:
        dispatch.register_policy(
            "workflow_dispatch_001", "step_dispatch_001", mismatch,
            authenticated_principal="control-plane-01",
        )
    assert caught.value.code == "DISPATCH_POLICY_MISMATCH"


def test_policy_registration_rejects_transport_principal_mismatch(
    tmp_path: Path,
) -> None:
    _, dispatch = _services(tmp_path)
    with pytest.raises(RuntimeWorkflowError) as caught:
        dispatch.register_policy(
            "workflow_dispatch_001", "step_dispatch_001", _policy_request(),
            authenticated_principal="different-control-plane",
        )
    assert caught.value.code == "DISPATCH_CALLER_MISMATCH"


def test_policy_revocation_is_compare_and_set_and_exact_retry(tmp_path: Path) -> None:
    _, dispatch = _services(tmp_path)
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", _policy_request(),
        authenticated_principal="control-plane-01",
    )
    revoke = {
        "schema_version": "pdx_dynamic_dispatch_policy_revoke_v1",
        "request_id": "request_revoke_001",
        "dispatch_policy_id": policy["dispatch_policy_id"],
        "expected_policy_revision_epoch": policy["policy_revision_epoch"],
        "expected_policy_digest": policy["policy_digest"],
        "reason_code": "POLICY_WITHDRAWN",
        "reason": "policy withdrawn before activation",
        "caller_authority_id": "control-plane-01",
    }
    first = dispatch.revoke_policy(
        "workflow_dispatch_001", "step_dispatch_001", revoke,
        authenticated_principal="control-plane-01",
    )
    retry = dispatch.revoke_policy(
        "workflow_dispatch_001", "step_dispatch_001", revoke,
        authenticated_principal="control-plane-01",
    )
    assert first == retry
    assert first["policy"]["policy_status"] == "revoked"
    assert first["policy"]["policy_revision_epoch"] == 2


def test_imported_decision_is_digest_bound_and_advances_projection(
    tmp_path: Path,
) -> None:
    _, dispatch = _services(tmp_path)
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", _policy_request(),
        authenticated_principal="control-plane-01",
    )
    request = _decision(policy)
    projection = dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    assert projection["phase"] == "decision_recorded"
    assert dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    ) == projection

    forged = deepcopy(request)
    forged["decision_receipt"]["arguments"] = {"expression": "2+2"}
    with pytest.raises(RuntimeWorkflowError) as caught:
        dispatch.import_decision(
            "workflow_dispatch_001", "step_dispatch_001", forged,
            authenticated_principal="control-plane-01",
        )
    assert caught.value.code == "DISPATCH_DECISION_BINDING_MISMATCH"


def test_activation_allocates_once_after_authoritative_checks(tmp_path: Path) -> None:
    store = RuntimeWorkflowStore(tmp_path / "workflow.sqlite3")
    workflow = RuntimeWorkflowService(store, SECRET)
    workflow.create(
        _load(ERRATUM / "examples" / "workflow-create-request-v2.valid.json")
    )
    request = _policy_request()
    dispatch = DynamicDispatchService(store, _registry(request))
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    decision_request = _decision(policy)
    dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", decision_request,
        authenticated_principal="control-plane-01",
    )
    with store.transaction() as connection:
        connection.execute(
            """UPDATE runtime_workflow_steps SET state = 'succeeded', attempt_count = 1
               WHERE workflow_job_id = ? AND workflow_step_id = ?""",
            ("workflow_dispatch_001", "step_decision_001"),
        )
    activation = _load(DISPATCH / "examples" / "activation-request.valid.json")
    receipt = decision_request["decision_receipt"]
    activation.update(
        {
            "source_run_id": receipt["source_run_id"],
            "source_plan_digest": receipt["source_plan_digest"],
            "decision_receipt_id": receipt["decision_receipt_id"],
            "decision_receipt_digest": receipt["decision_receipt_digest"],
            "dispatch_policy_id": policy["dispatch_policy_id"],
            "policy_digest_assertion": policy["policy_digest"],
            "policy_revision_epoch": policy["policy_revision_epoch"],
        }
    )
    first = dispatch.activate(
        "workflow_dispatch_001", "step_dispatch_001", activation,
        authenticated_principal="control-plane-01",
    )
    retry = dispatch.activate(
        "workflow_dispatch_001", "step_dispatch_001", activation,
        authenticated_principal="control-plane-01",
    )
    assert first["result"] == "created"
    assert retry["result"] == "exact_retry"
    assert retry["authoritative_activation_id"] == first["authoritative_activation_id"]
    state = workflow.get_state("workflow_dispatch_001")
    assert state["counters"]["dispatch_attempts"] == 1
    assert state["counters"]["active_dispatches"] == 1

    terminal = dispatch.execute_activation(first["authoritative_activation_id"])
    assert terminal["status"] == "completed"
    assert terminal["receipt_cas_published"] is True
    assert terminal["executor_output_artifacts_published"] is True
    assert dispatch.execute_activation(first["authoritative_activation_id"]) == terminal
    projection = dispatch.get_projection(
        "workflow_dispatch_001", "step_dispatch_001"
    )
    assert projection["phase"] == "terminal"
    assert projection["terminal_receipt"]["receipt_digest"] == terminal["receipt_digest"]
    state = workflow.get_state("workflow_dispatch_001")
    assert state["counters"]["active_dispatches"] == 0


def test_output_schema_failure_publishes_receipt_but_suppresses_output(
    tmp_path: Path,
) -> None:
    store = RuntimeWorkflowStore(tmp_path / "workflow.sqlite3")
    workflow = RuntimeWorkflowService(store, SECRET)
    workflow.create(
        _load(ERRATUM / "examples" / "workflow-create-request-v2.valid.json")
    )
    request = _policy_request()
    dispatch = DynamicDispatchService(
        store, _registry(request, executor=lambda arguments: {"wrong": "2"})
    )
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    decision_request = _decision(policy)
    dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", decision_request,
        authenticated_principal="control-plane-01",
    )
    with store.transaction() as connection:
        connection.execute(
            """UPDATE runtime_workflow_steps SET state = 'succeeded', attempt_count = 1
               WHERE workflow_job_id = ? AND workflow_step_id = ?""",
            ("workflow_dispatch_001", "step_decision_001"),
        )
    activation = _load(DISPATCH / "examples" / "activation-request.valid.json")
    decision = decision_request["decision_receipt"]
    activation.update(
        {
            "source_run_id": decision["source_run_id"],
            "source_plan_digest": decision["source_plan_digest"],
            "decision_receipt_id": decision["decision_receipt_id"],
            "decision_receipt_digest": decision["decision_receipt_digest"],
            "dispatch_policy_id": policy["dispatch_policy_id"],
            "policy_digest_assertion": policy["policy_digest"],
            "policy_revision_epoch": policy["policy_revision_epoch"],
        }
    )
    allocated = dispatch.activate(
        "workflow_dispatch_001", "step_dispatch_001", activation,
        authenticated_principal="control-plane-01",
    )
    terminal = dispatch.execute_activation(allocated["authoritative_activation_id"])
    assert terminal["status"] == "executed_output_invalid"
    assert terminal["receipt_cas_published"] is True
    assert terminal["executor_output_artifacts_published"] is False
    assert terminal["artifact_identities"] == []
    parent = workflow.get_receipt("workflow_dispatch_001")
    assert parent["schema_version"] == "pdx_runtime_provider_workflow_receipt_v2"
    assert parent["status"] == "failed"


def test_revocation_cancels_allocated_attempt_before_execution(tmp_path: Path) -> None:
    workflow, dispatch, policy, allocated = _allocated_dispatch(tmp_path)
    revoke = {
        "schema_version": "pdx_dynamic_dispatch_policy_revoke_v1",
        "request_id": "request_revoke_after_activation_001",
        "dispatch_policy_id": policy["dispatch_policy_id"],
        "expected_policy_revision_epoch": policy["policy_revision_epoch"],
        "expected_policy_digest": policy["policy_digest"],
        "reason_code": "POLICY_WITHDRAWN",
        "reason": "policy withdrawn before execution",
        "caller_authority_id": "control-plane-01",
    }
    projection = dispatch.revoke_policy(
        "workflow_dispatch_001", "step_dispatch_001", revoke,
        authenticated_principal="control-plane-01",
    )
    assert projection["policy"]["policy_status"] == "revoked"
    terminal = dispatch.execute_activation(allocated["authoritative_activation_id"])
    assert terminal["status"] == "cancelled"
    assert terminal["execution_occurred"] is False
    assert terminal["cancellation"]["phase"] == "not_started"
    assert terminal["reconciliation_required"] is False
    assert workflow.get_receipt("workflow_dispatch_001")["status"] == "cancelled"


def test_reconcile_is_attempt_bound_and_returns_durable_projection(
    tmp_path: Path,
) -> None:
    _, dispatch, _, allocated = _allocated_dispatch(tmp_path)
    request = {
        "schema_version": "pdx_dynamic_dispatch_reconcile_v1",
        "request_id": "request_reconcile_001",
        "expected_dispatch_attempt_id": allocated["dispatch_attempt_id"],
        "reason": "host_restart",
        "caller_authority_id": "control-plane-01",
    }
    projection = dispatch.reconcile(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    assert projection["active_activation"]["dispatch_attempt_id"] == allocated[
        "dispatch_attempt_id"
    ]
    request["expected_dispatch_attempt_id"] = "dispatch_attempt_wrong"
    with pytest.raises(RuntimeWorkflowError) as caught:
        dispatch.reconcile(
            "workflow_dispatch_001", "step_dispatch_001", request,
            authenticated_principal="control-plane-01",
        )
    assert caught.value.code == "DISPATCH_IDEMPOTENCY_CONFLICT"


def test_revocation_during_execution_preserves_running_cancellation_evidence(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocking_executor(arguments: dict) -> dict:
        entered.set()
        assert release.wait(5)
        return {"result": "2"}

    workflow, dispatch, policy, allocated = _allocated_dispatch(
        tmp_path, executor=blocking_executor
    )
    terminal: list[dict] = []
    worker = threading.Thread(
        target=lambda: terminal.append(
            dispatch.execute_activation(allocated["authoritative_activation_id"])
        )
    )
    worker.start()
    assert entered.wait(5)
    revoke = {
        "schema_version": "pdx_dynamic_dispatch_policy_revoke_v1",
        "request_id": "request_revoke_running_001",
        "dispatch_policy_id": policy["dispatch_policy_id"],
        "expected_policy_revision_epoch": policy["policy_revision_epoch"],
        "expected_policy_digest": policy["policy_digest"],
        "reason_code": "POLICY_WITHDRAWN",
        "reason": "policy withdrawn while executing",
        "caller_authority_id": "control-plane-01",
    }
    dispatch.revoke_policy(
        "workflow_dispatch_001", "step_dispatch_001", revoke,
        authenticated_principal="control-plane-01",
    )
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert terminal[0]["status"] == "cancelled"
    assert terminal[0]["execution_occurred"] is True
    assert terminal[0]["cancellation"]["phase"] == "running"
    assert terminal[0]["reconciliation_required"] is False
    assert workflow.get_receipt("workflow_dispatch_001")["status"] == "cancelled"


def test_competing_workers_execute_an_activation_only_once(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocking_executor(arguments: dict) -> dict:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(5)
        return {"result": "2"}

    _, dispatch, _, allocated = _allocated_dispatch(
        tmp_path, executor=blocking_executor
    )
    receipts: list[dict] = []
    first = threading.Thread(
        target=lambda: receipts.append(dispatch.run_next_activation())
    )
    first.start()
    assert entered.wait(5)
    assert dispatch.run_next_activation() is None
    release.set()
    first.join(5)
    assert calls == 1
    assert receipts[0]["status"] == "completed"
    assert dispatch.execute_activation(
        allocated["authoritative_activation_id"]
    ) == receipts[0]


def test_frozen_dispatch_http_routes_include_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "dispatch-control-plane-token"
    monkeypatch.setenv("PDX_ENGINE_AUTH_PROFILE", "self_hosted")
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", token)
    monkeypatch.setenv(
        "PDX_ENGINE_CONTROL_PLANE_BINDINGS",
        json.dumps({"control-plane-01": token}),
    )
    monkeypatch.setenv("PDX_ENGINE_WORKFLOW_HMAC_SECRET", "h" * 32)
    request = _policy_request()
    server = make_server(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "http.sqlite3",
        staging_root=tmp_path / "staging",
        dispatch_registry=_registry(request),
    )
    workflow = server.RequestHandlerClass.workflow_service
    dispatch = server.RequestHandlerClass.dispatch_service
    workflow.create(
        _load(ERRATUM / "examples" / "workflow-create-request-v2.valid.json")
    )
    policy = dispatch.register_policy(
        "workflow_dispatch_001", "step_dispatch_001", request,
        authenticated_principal="control-plane-01",
    )
    decision_request = _decision(policy)
    dispatch.import_decision(
        "workflow_dispatch_001", "step_dispatch_001", decision_request,
        authenticated_principal="control-plane-01",
    )
    with dispatch.store.transaction() as connection:
        connection.execute(
            """UPDATE runtime_workflow_steps SET state = 'succeeded', attempt_count = 1
               WHERE workflow_job_id = ? AND workflow_step_id = ?""",
            ("workflow_dispatch_001", "step_decision_001"),
        )
    activation = _load(DISPATCH / "examples" / "activation-request.valid.json")
    decision = decision_request["decision_receipt"]
    activation.update(
        {
            "source_run_id": decision["source_run_id"],
            "source_plan_digest": decision["source_plan_digest"],
            "decision_receipt_id": decision["decision_receipt_id"],
            "decision_receipt_digest": decision["decision_receipt_digest"],
            "dispatch_policy_id": policy["dispatch_policy_id"],
            "policy_digest_assertion": policy["policy_digest"],
            "policy_revision_epoch": policy["policy_revision_epoch"],
        }
    )
    allocated = dispatch.activate(
        "workflow_dispatch_001", "step_dispatch_001", activation,
        authenticated_principal="control-plane-01",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = {
            "schema_version": "pdx_dynamic_dispatch_reconcile_v1",
            "request_id": "request_http_reconcile_001",
            "expected_dispatch_attempt_id": allocated["dispatch_attempt_id"],
            "reason": "host_restart",
            "caller_authority_id": "control-plane-01",
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/internal/v1/"
            "runtime-provider-workflows/workflow_dispatch_001/steps/"
            "step_dispatch_001/dispatch/reconcile",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req) as response:
            projection = json.loads(response.read())
        assert projection["phase"] == "activated"
        assert projection["active_activation"]["dispatch_attempt_id"] == allocated[
            "dispatch_attempt_id"
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
