from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from pdx_artifact_engine.internal_http import make_server
from pdx_artifact_engine.runtime_workflows import (
    RuntimeWorkflowError,
    RuntimeWorkflowService,
    RuntimeWorkflowStore,
)
from pdx_artifact_engine.runtime_workflows.contracts import validate

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "runtime-provider-workflow"
SECRET = b"runtime-workflow-test-secret-value-0001"


def _load(name: str) -> dict:
    return json.loads((CONTRACT / "examples" / name).read_text(encoding="utf-8"))


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _service(tmp_path: Path) -> RuntimeWorkflowService:
    return RuntimeWorkflowService(RuntimeWorkflowStore(tmp_path / "workflow.sqlite3"), SECRET)


def _create(service: RuntimeWorkflowService) -> dict:
    plan = _load("workflow-plan.valid.json")
    body = {
        "schema_version": "pdx_internal_runtime_provider_workflow_create_request_v1",
        "request_id": "request_create_001", "correlation_id": "correlation_001",
        "idempotency_key": "workflow-create-0001", "operation_digest": "a" * 64,
        "plan": plan,
    }
    status, response = service.create(body)
    assert status == 202
    validate("pdx_runtime_provider_workflow_create_response_v1.schema.json", response)
    return body


def _provider_activation() -> dict:
    return deepcopy(_load("provider-activation.valid.json")["request"])


def _provider_update(claim: dict, sequence: int, kind: str = "event") -> dict:
    payload = (
        {"event_kind": "progress", "message": "working", "artifact_refs": []}
        if kind == "event"
        else {"terminal_outcome": "succeeded", "summary": "done", "artifact_refs": []}
    )
    return {
        "schema_version": "pdx_internal_runtime_provider_update_v1",
        **{key: claim[key] for key in (
            "workflow_job_id", "workflow_step_id", "step_kind", "claim_id",
            "lease_token", "invocation_id", "attempt_number", "operation_digest",
            "execution_constraints_digest", "idempotency_key",
        )},
        "record": {"schema_version": "pdx_runtime_provider_record_v1",
                   "record_id": f"provider_record_{sequence:03d}", "record_kind": kind,
                   "sequence": sequence, "payload": payload, "payload_digest": _digest(payload)},
    }


def _check_update(claim: dict, sequence: int, kind: str = "event") -> dict:
    artifact = {
        "schema_version": "prodocux_opaque_artifact_v1",
        "artifact_id": "artifact_check_report_001",
        "uri": "artifact://workflow/check-report.json", "sha256": "e" * 64,
        "size_bytes": 256, "media_type": "application/json",
    }
    payload = (
        {"message": "checking"}
        if kind == "event"
        else {"terminal_outcome": "succeeded", "summary": "checks passed",
              "report_artifact": artifact["uri"]}
    )
    result = {
        "schema_version": "pdx_internal_runtime_check_update_v1",
        **{key: claim[key] for key in (
            "workflow_job_id", "workflow_step_id", "step_kind", "claim_id",
            "lease_token", "attempt_number", "check_definition_digest",
            "execution_constraints_digest", "idempotency_key",
        )},
        "record": {"schema_version": "pdx_runtime_check_record_v1",
                   "record_id": f"check_record_{sequence:03d}", "record_kind": kind,
                   "sequence": sequence, "payload": payload, "payload_digest": _digest(payload)},
    }
    if kind == "outcome":
        result["verified_report_artifact"] = artifact
    return result


def test_create_activation_retry_is_durable_and_concurrent_safe(tmp_path: Path) -> None:
    service = _service(tmp_path)
    create = _create(service)
    status, replay = service.create(create)
    assert status == 200
    request = _provider_activation()
    first = service.activate_provider("workflow_job_001", request, authenticated_instance_id="hub_control_001")
    retry_a = service.activate_provider("workflow_job_001", {**request, "request_id": "request_provider_002"}, authenticated_instance_id="hub_control_001")
    retry_b = service.activate_provider("workflow_job_001", {**request, "request_id": "request_provider_003"}, authenticated_instance_id="hub_control_001")
    assert first == retry_a == retry_b
    assert replay["workflow_job_id"] == first["workflow_job_id"]
    service.store.close()

    restarted = _service(tmp_path)
    after_restart = restarted.activate_provider(
        "workflow_job_001", request, authenticated_instance_id="hub_control_001"
    )
    assert after_restart == first
    with restarted.store.transaction() as connection:
        row = connection.execute("SELECT * FROM runtime_workflow_claims").fetchone()
        assert row["lease_token_digest"] == hashlib.sha256(first["lease_token"].encode()).hexdigest()
        assert first["lease_token"] not in row["binding_json"]


def test_two_connections_concurrently_activate_one_attempt(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    first_service = RuntimeWorkflowService(RuntimeWorkflowStore(database), SECRET)
    _create(first_service)
    second_service = RuntimeWorkflowService(RuntimeWorkflowStore(database), SECRET)
    request = _provider_activation()

    def activate(service: RuntimeWorkflowService, request_id: str) -> dict:
        return service.activate_provider(
            "workflow_job_001", {**request, "request_id": request_id},
            authenticated_instance_id="hub_control_001",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(activate, first_service, "request_provider_002"),
            executor.submit(activate, second_service, "request_provider_003"),
        ]
    left, right = (future.result() for future in futures)
    assert left == right
    assert first_service.get_state("workflow_job_001")["counters"] == {
        "provider_attempts": 1, "check_attempts": 0, "active_steps": 1,
        "repair_iterations": 0, "total_runtime_seconds": 0,
        "total_event_bytes": 0, "total_artifact_bytes": 0,
        "cross_step_artifact_edges": 0, "external_operations": 0,
    }


def test_hmac_key_rotation_retains_active_claim_recovery_and_readiness(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    old = b"old-runtime-workflow-key-material-0001"
    new = b"new-runtime-workflow-key-material-0002"
    service = RuntimeWorkflowService(
        RuntimeWorkflowStore(database), hmac_keys={"old": old},
        active_hmac_key_id="old",
    )
    _create(service)
    request = _provider_activation()
    first = service.activate_provider(
        "workflow_job_001", request, authenticated_instance_id="hub_control_001"
    )
    service.store.close()

    incomplete = RuntimeWorkflowService(
        RuntimeWorkflowStore(database), hmac_keys={"new": new},
        active_hmac_key_id="new",
    )
    assert incomplete.readiness()["missing_active_claim_key_ids"] == ["old"]
    with pytest.raises(RuntimeWorkflowError):
        incomplete.activate_provider(
            "workflow_job_001", request,
            authenticated_instance_id="hub_control_001",
        )
    incomplete.store.close()

    rotated = RuntimeWorkflowService(
        RuntimeWorkflowStore(database), hmac_keys={"old": old, "new": new},
        active_hmac_key_id="new",
    )
    assert rotated.readiness()["ready"] is True
    replay = rotated.activate_provider(
        "workflow_job_001", request, authenticated_instance_id="hub_control_001"
    )
    assert replay["lease_token"] == first["lease_token"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("control_plane_instance_id", "hub_control_002"),
        ("correlation_id", "correlation_002"),
        ("lease_seconds", 120),
        ("workspace_ref", "workspace://root/other"),
        ("execution_constraints_digest", "f" * 64),
        ("provider_instance_id", "provider_instance_002"),
    ],
)
def test_activation_binding_conflicts_do_not_mutate_counters(
    tmp_path: Path, field: str, value: object
) -> None:
    service = _service(tmp_path)
    _create(service)
    request = _provider_activation()
    service.activate_provider("workflow_job_001", request, authenticated_instance_id="hub_control_001")
    before = service.get_state("workflow_job_001")["counters"]
    changed = {**request, field: value}
    with pytest.raises(RuntimeWorkflowError) as caught:
        service.activate_provider(
            "workflow_job_001", changed,
            authenticated_instance_id=str(changed["control_plane_instance_id"]),
        )
    assert caught.value.code == "ACTIVATION_BINDING_CONFLICT"
    assert service.get_state("workflow_job_001")["counters"] == before


def test_transport_principal_mismatch_and_not_ready_are_fail_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    provider = _provider_activation()
    with pytest.raises(RuntimeWorkflowError) as mismatch:
        service.activate_provider("workflow_job_001", provider, authenticated_instance_id="other_control_001")
    assert mismatch.value.code == "ACTIVATION_PRINCIPAL_MISMATCH"
    check = deepcopy(_load("check-activation.valid.json")["request"])
    with pytest.raises(RuntimeWorkflowError) as not_ready:
        service.activate_check("workflow_job_001", check, authenticated_instance_id="hub_control_001")
    assert not_ready.value.code == "STEP_NOT_READY"
    assert service.get_state("workflow_job_001")["counters"]["active_steps"] == 0


def test_invocation_id_cannot_be_rebound_under_a_new_idempotency_key(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    request = _provider_activation()
    service.activate_provider(
        "workflow_job_001", request, authenticated_instance_id="hub_control_001"
    )
    changed = {
        **request, "request_id": "request_provider_002",
        "idempotency_key": "activate-provider-002",
        "provider_instance_id": "provider_instance_002",
    }
    with pytest.raises(RuntimeWorkflowError) as conflict:
        service.activate_provider(
            "workflow_job_001", changed,
            authenticated_instance_id="hub_control_001",
        )
    assert conflict.value.code == "ACTIVATION_BINDING_CONFLICT"
    assert service.get_state("workflow_job_001")["counters"]["provider_attempts"] == 1


def test_sequence_digest_lease_and_reconcile_are_cas_fenced(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    claim = service.activate_provider("workflow_job_001", _provider_activation(), authenticated_instance_id="hub_control_001")
    bad = _provider_update(claim, 0)
    bad["record"]["payload_digest"] = "f" * 64
    with pytest.raises(RuntimeWorkflowError) as digest_error:
        service.update("workflow_job_001", bad, "provider")
    assert digest_error.value.code == "PAYLOAD_DIGEST_INVALID"
    service.update("workflow_job_001", _provider_update(claim, 0), "provider")
    with pytest.raises(RuntimeWorkflowError) as sequence_error:
        service.update("workflow_job_001", _provider_update(claim, 2), "provider")
    assert sequence_error.value.code == "SEQUENCE_CONFLICT"
    with service.store.transaction() as connection:
        connection.execute("UPDATE runtime_workflow_claims SET lease_expires_unix = 1 WHERE claim_id = ?", (claim["claim_id"],))
    reconcile = {"schema_version": "pdx_internal_runtime_workflow_reconcile_v1",
                 "request_id": "request_reconcile_001", "correlation_id": "correlation_001",
                 "workflow_job_id": "workflow_job_001"}
    state = service.reconcile("workflow_job_001", reconcile, now=2)
    assert state["counters"]["active_steps"] == 0
    with pytest.raises(RuntimeWorkflowError) as stale:
        service.update("workflow_job_001", _provider_update(claim, 1), "provider", now=2)
    assert stale.value.code == "CLAIM_STALE"


def test_runtime_budget_failure_is_atomic_and_terminal(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    claim = service.activate_provider(
        "workflow_job_001", _provider_activation(),
        authenticated_instance_id="hub_control_001",
    )
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE runtime_workflow_claims SET started_unix = 1, lease_expires_unix = 5000 WHERE claim_id = ?",
            (claim["claim_id"],),
        )
    renew = {
        "schema_version": "pdx_internal_runtime_provider_lease_renew_v1",
        **{key: claim[key] for key in (
            "workflow_job_id", "workflow_step_id", "step_kind", "claim_id",
            "lease_token", "invocation_id", "attempt_number", "operation_digest",
            "execution_constraints_digest",
        )},
        "lease_seconds": 60,
    }
    with pytest.raises(RuntimeWorkflowError) as exhausted:
        service.renew("workflow_job_001", renew, "provider", now=2000)
    assert exhausted.value.code == "WORKFLOW_BUDGET_EXHAUSTED"
    state = service.get_state("workflow_job_001")
    assert state["state"] == "failed"
    assert state["counters"]["active_steps"] == 0
    receipt = service.get_receipt("workflow_job_001")
    assert receipt["terminal_error"]["code"] == "WORKFLOW_BUDGET_EXHAUSTED"
    validate("pdx_runtime_provider_workflow_receipt_v1.schema.json", receipt)


def test_terminal_cancel_freezes_schema_valid_receipt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    claim = service.activate_provider("workflow_job_001", _provider_activation(), authenticated_instance_id="hub_control_001")
    service.update("workflow_job_001", _provider_update(claim, 0), "provider")
    cancel = {"schema_version": "pdx_internal_runtime_workflow_cancel_v1",
              "request_id": "request_cancel_001", "correlation_id": "correlation_001",
              "workflow_job_id": "workflow_job_001", "reason": "operator cancelled"}
    state = service.cancel("workflow_job_001", cancel)
    assert state["state"] == "cancelled"
    receipt = service.get_receipt("workflow_job_001")
    validate("pdx_runtime_provider_workflow_receipt_v1.schema.json", receipt)
    with pytest.raises(RuntimeWorkflowError) as terminal:
        service.update("workflow_job_001", _provider_update(claim, 1), "provider")
    assert terminal.value.code == "POST_TERMINAL_ACTIVITY_REJECTED"


def test_provider_then_verified_check_persists_relationship_receipt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    provider = service.activate_provider(
        "workflow_job_001", _provider_activation(),
        authenticated_instance_id="hub_control_001",
    )
    service.update("workflow_job_001", _provider_update(provider, 0), "provider")
    service.update("workflow_job_001", _provider_update(provider, 1, "outcome"), "provider")
    check_request = deepcopy(_load("check-activation.valid.json")["request"])
    check = service.activate_check(
        "workflow_job_001", check_request,
        authenticated_instance_id="hub_control_001",
    )
    service.update("workflow_job_001", _check_update(check, 0), "check")
    state = service.update("workflow_job_001", _check_update(check, 1, "outcome"), "check")
    assert state["counters"]["total_artifact_bytes"] == 256
    assert state["counters"]["cross_step_artifact_edges"] == 1
    cancel = {"schema_version": "pdx_internal_runtime_workflow_cancel_v1",
              "request_id": "request_cancel_001", "correlation_id": "correlation_001",
              "workflow_job_id": "workflow_job_001", "reason": "candidate test complete"}
    service.cancel("workflow_job_001", cancel)
    receipt = service.get_receipt("workflow_job_001")
    assert receipt["artifact_edges"][0]["artifact"]["artifact_id"] == "artifact_check_report_001"
    assert receipt["step_receipts"][1]["verified_check_report_artifact"]["size_bytes"] == 256
    validate("pdx_runtime_provider_workflow_receipt_v1.schema.json", receipt)


def test_private_http_requires_registered_control_plane_for_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "control-plane-test-token"
    monkeypatch.setenv("PDX_ENGINE_AUTH_PROFILE", "self_hosted")
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", token)
    monkeypatch.setenv(
        "PDX_ENGINE_CONTROL_PLANE_BINDINGS",
        json.dumps({"hub_control_001": token}),
    )
    monkeypatch.setenv("PDX_ENGINE_WORKFLOW_HMAC_SECRET", "h" * 32)
    server = make_server(
        host="127.0.0.1", port=0, db_path=tmp_path / "http.sqlite3",
        staging_root=tmp_path / "staging",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path: str, body: dict, bearer: str = token) -> tuple[int, dict]:
        request = urllib.request.Request(
            base + path, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        plan = _load("workflow-plan.valid.json")
        create = {"schema_version": "pdx_internal_runtime_provider_workflow_create_request_v1",
                  "request_id": "request_create_001", "correlation_id": "correlation_001",
                  "idempotency_key": "workflow-create-0001", "operation_digest": "a" * 64,
                  "plan": plan}
        assert post("/internal/v1/runtime-provider-workflows", create)[0] == 202
        status, claim = post(
            "/internal/v1/runtime-provider-workflows/workflow_job_001/provider-claims",
            _provider_activation(),
        )
        assert status == 200
        validate("pdx_runtime_provider_claim_v1.schema.json", claim)
        monkeypatch.setenv(
            "PDX_ENGINE_CONTROL_PLANE_BINDINGS",
            json.dumps({"other_control_001": token}),
        )
        status, error = post(
            "/internal/v1/runtime-provider-workflows/workflow_job_001/provider-claims",
            _provider_activation(),
        )
        assert (status, error["code"]) == (403, "ACTIVATION_PRINCIPAL_MISMATCH")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_step_projection_tracks_attempt_terminal_identity_and_reconcile(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _create(service)
    pristine = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )
    validate("pdx_runtime_provider_step_projection_v1.schema.json", pristine)
    assert [step["workflow_step_id"] for step in pristine["steps"]] == [
        "step_builder", "step_check", "step_reviewer", "step_repair_1"
    ]
    assert pristine["steps"][0] == {
        "workflow_step_id": "step_builder",
        "step_kind": "builder",
        "state": "pending",
        "latest_attempt_number": None,
        "active_claim": False,
        "terminal_record_identity": None,
    }

    claim = service.activate_provider(
        "workflow_job_001",
        _provider_activation(),
        authenticated_instance_id="hub_control_001",
    )
    active = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )["steps"][0]
    assert active["latest_attempt_number"] == 1
    assert active["active_claim"] is True
    assert "lease_token" not in json.dumps(active)
    assert "lease_token_digest" not in json.dumps(active)

    service.update(
        "workflow_job_001", _provider_update(claim, 0, "outcome"), "provider"
    )
    completed = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )["steps"][0]
    assert completed["state"] == "succeeded"
    assert completed["active_claim"] is False
    assert completed["terminal_record_identity"] == {
        "record_id": "provider_record_000",
        "record_schema_id": "pdx_runtime_provider_record_v1",
        "payload_digest": _provider_update(claim, 0, "outcome")["record"][
            "payload_digest"
        ],
    }

    check = service.activate_check(
        "workflow_job_001",
        deepcopy(_load("check-activation.valid.json")["request"]),
        authenticated_instance_id="hub_control_001",
    )
    with service.store.transaction() as connection:
        connection.execute(
            "UPDATE runtime_workflow_claims SET lease_expires_unix = 1 WHERE claim_id = ?",
            (check["claim_id"],),
        )
    reconcile = {
        "schema_version": "pdx_internal_runtime_workflow_reconcile_v1",
        "request_id": "request_reconcile_001",
        "correlation_id": "correlation_001",
        "workflow_job_id": "workflow_job_001",
    }
    service.reconcile("workflow_job_001", reconcile, now=2)
    recovered = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )["steps"][1]
    assert recovered["state"] == "pending"
    assert recovered["latest_attempt_number"] == 1
    assert recovered["active_claim"] is False
    assert recovered["terminal_record_identity"] is None

    cancel = {
        "schema_version": "pdx_internal_runtime_workflow_cancel_v1",
        "request_id": "request_cancel_001",
        "correlation_id": "correlation_001",
        "workflow_job_id": "workflow_job_001",
        "reason": "projection terminal-read test",
    }
    service.cancel("workflow_job_001", cancel)
    terminal = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )
    assert terminal["workflow_state"] == "cancelled"
    assert terminal["steps"][0]["terminal_record_identity"] is not None


def test_step_projection_requires_registered_control_plane_and_known_workflow(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _create(service)
    with pytest.raises(RuntimeWorkflowError) as forbidden:
        service.get_step_projection(
            "workflow_job_001", authenticated_instance_id=""
        )
    assert (forbidden.value.status, forbidden.value.code) == (
        403,
        "ACTIVATION_AUTH_FORBIDDEN",
    )
    with pytest.raises(RuntimeWorkflowError) as missing:
        service.get_step_projection(
            "workflow_job_missing", authenticated_instance_id="hub_control_001"
        )
    assert missing.value.status == 404


def test_step_projection_http_route_is_control_plane_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "control-plane-test-token"
    monkeypatch.setenv("PDX_ENGINE_AUTH_PROFILE", "self_hosted")
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", token)
    monkeypatch.setenv(
        "PDX_ENGINE_CONTROL_PLANE_BINDINGS",
        json.dumps({"hub_control_001": token}),
    )
    monkeypatch.setenv("PDX_ENGINE_WORKFLOW_HMAC_SECRET", "h" * 32)
    server = make_server(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "http-projection.sqlite3",
        staging_root=tmp_path / "staging",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        value = urllib.request.Request(
            base + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(value) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        plan = _load("workflow-plan.valid.json")
        create = {
            "schema_version": "pdx_internal_runtime_provider_workflow_create_request_v1",
            "request_id": "request_create_001",
            "correlation_id": "correlation_001",
            "idempotency_key": "workflow-create-0001",
            "operation_digest": "a" * 64,
            "plan": plan,
        }
        assert request("POST", "/internal/v1/runtime-provider-workflows", create)[0] == 202
        status, projection = request(
            "GET", "/internal/v1/runtime-provider-workflows/workflow_job_001/steps"
        )
        assert status == 200
        validate("pdx_runtime_provider_step_projection_v1.schema.json", projection)

        monkeypatch.setenv("PDX_ENGINE_CONTROL_PLANE_BINDINGS", "{}")
        status, error = request(
            "GET", "/internal/v1/runtime-provider-workflows/workflow_job_001/steps"
        )
        assert (status, error["code"]) == (403, "ACTIVATION_AUTH_FORBIDDEN")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_additive_projection_schema_is_packaged_byte_identical() -> None:
    packaged = (
        ROOT
        / "runtime"
        / "pdx_artifact_engine"
        / "contracts"
        / "runtime_provider_workflow"
        / "pdx_runtime_provider_step_projection_v1.schema.json"
    )
    documented = (
        CONTRACT
        / "additive"
        / "pdx_runtime_provider_step_projection_v1.schema.json"
    )
    assert packaged.read_bytes() == documented.read_bytes()
    manifest = json.loads(
        (CONTRACT / "additive" / "step-projection-manifest.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["schema"]["sha256"] == hashlib.sha256(
        packaged.read_bytes()
    ).hexdigest()
    assert manifest["base_release"]["frozen_schemas_modified"] is False


def test_step_projection_schema_rejects_authority_leaks_and_invalid_binding(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    _create(service)
    projection = service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )
    leaked = deepcopy(projection)
    leaked["steps"][0]["lease_token"] = "secret"
    with pytest.raises(ValueError):
        validate("pdx_runtime_provider_step_projection_v1.schema.json", leaked)
    impossible = deepcopy(projection)
    impossible["steps"][0]["active_claim"] = True
    with pytest.raises(ValueError):
        validate("pdx_runtime_provider_step_projection_v1.schema.json", impossible)


def test_step_projection_read_does_not_mutate_durable_workflow(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _create(service)
    with service.store.read_transaction() as connection:
        before = tuple(
            connection.execute(
                """SELECT state, counters_json, updated_at, receipt_json
                   FROM runtime_workflows WHERE workflow_job_id = ?""",
                ("workflow_job_001",),
            ).fetchone()
        )
    service.get_step_projection(
        "workflow_job_001", authenticated_instance_id="hub_control_001"
    )
    with service.store.read_transaction() as connection:
        after = tuple(
            connection.execute(
                """SELECT state, counters_json, updated_at, receipt_json
                   FROM runtime_workflows WHERE workflow_job_id = ?""",
                ("workflow_job_001",),
            ).fetchone()
        )
    assert after == before
