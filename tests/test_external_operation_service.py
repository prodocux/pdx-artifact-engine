"""Real SQLite and countable provider tests; no live external service."""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from pdx_artifact_engine.contracts.external_operations import validation as v
from pdx_artifact_engine.dynamic_dispatch import DynamicDispatchService
from pdx_artifact_engine.external_operations import (
    ExternalOperationService,
    Principal,
    ProviderAdapter,
)
from pdx_artifact_engine.runtime_workflows import (
    RuntimeWorkflowService,
    RuntimeWorkflowStore,
)

from tests.test_dynamic_dispatch_service import (
    ERRATUM,
    _decision,
    _load,
    _policy_request,
    _registry,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads(
    (ROOT / "docs/external-operations/shape-fixtures.json").read_text()
)
CONTROL = Principal("control-plane-01", "instance-controller")
ISSUER = Principal("issuer-001", "instance-issuer")
ADMIN = Principal("administrator-001", "instance-admin")
ADAPTER = Principal("adapter-001", "instance-adapter")
MANUAL = Principal("manual-001", "instance-manual")
READER = Principal("reader-001", "instance-reader")
SUPERVISOR = Principal("supervisor-001", "instance-supervisor")


def sample(kind):
    suffix = "#/$defs/" + kind
    return deepcopy(
        next(
            x["instance"]
            for x in FIXTURES
            if x["schema"].endswith(suffix) and x["valid"]
        )
    )


def setup(tmp_path, *, query_only=False, crash=False):
    store = RuntimeWorkflowStore(tmp_path / "workflow.sqlite3")
    workflow = RuntimeWorkflowService(store, b"01234567890123456789012345678901")
    policy_request = _policy_request()
    registry = _registry(policy_request)
    dispatch = DynamicDispatchService(store, registry)
    artifacts = {}

    def artifact(value):
        raw = __import__("rfc8785").dumps(value)
        digest = v.sha(raw)
        art = {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "art_" + digest,
            "uri": "artifact://evidence/" + digest,
            "sha256": digest,
            "size_bytes": len(raw),
            "media_type": "application/json",
        }
        artifacts[art["artifact_id"]] = raw
        return art

    roles = {
        "controller": CONTROL,
        "issuer": ISSUER,
        "administrator": ADMIN,
        "adapter": ADAPTER,
        "manual": MANUAL,
        "reader": READER,
        "supervisor": SUPERVISOR,
    }
    authority = sample("authority_config")
    authority.update(authority_id="authority-001", tenant_id="tenant-001")
    for role, principal in roles.items():
        authority[role + "_principals"] = [principal.name]
    count_path = tmp_path / "provider.sqlite3"
    with sqlite3.connect(count_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS submitted (key TEXT PRIMARY KEY)"
        )

    def submit(payload, key):
        with sqlite3.connect(count_path) as connection:
            connection.execute("INSERT INTO submitted VALUES (?)", (key,))
        if crash:
            os._exit(37)

    deployment = policy_request["allowed_tools"][0]["deployment"]
    lookup = (
        {
            "verified_artifact": artifact({"lookup": "client-key-query-demonstration"}),
            "verifier_id": "lookup-verifier-001",
            "verifier_contract_digest": v.digest({"contract": "client-key-query-v1"}),
        }
        if query_only
        else None
    )
    adapter = ProviderAdapter(
        deployment,
        deployment if query_only else None,
        submit,
        query=(lambda profile, key: None) if query_only else None,
        lookup_proof=lookup,
    )
    service = ExternalOperationService(
        store,
        [authority],
        lambda art: artifacts[art["artifact_id"]],
        {
            "urn:example:payload": registry.get(
                policy_request["allowed_tools"][0]["name"]
            ).input_schema
        },
        {"provider-001": adapter},
        dispatch=dispatch,
        observation_verifier=lambda body, context: {
            "provenance_verified": True,
            "manual_authority_fresh": True,
            "submitter_terminated": True,
            "definitive_nonexecution": True,
        },
    )
    provider = sample("provider_register")
    provider.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        request_id="register-provider-001",
        idempotency_key="provider-register-key-001",
        provider_profile_id="provider-001",
        revision=1,
        submit_deployment=deployment,
        query_deployment=deployment if query_only else None,
        recovery_mode="query_only" if query_only else "manual_only",
        lookup_proven=query_only,
        lookup_proof=lookup,
    )
    profile = service.register("provider_register", provider, ADMIN)
    payload = artifact({"expression": "1+1"})
    subject = sample("subject_register")
    subject.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        request_id="register-subject-001",
        idempotency_key="subject-register-key-001",
        operation_subject_id="subject-001",
    )
    subject["specification"].update(
        payload_artifact=payload,
        payload_schema_id="urn:example:payload",
        payload_schema_digest=v.digest(service.payload_schemas["urn:example:payload"]),
        evidence_artifacts=[],
        provider_profile_id=provider["provider_profile_id"],
        provider_profile_revision=provider["revision"],
        provider_profile_digest=profile["record_digest"],
        account_alias=provider["account_alias"],
        environment=provider["environment"],
        executor_identity_digest=deployment["identity_digest"],
        execution_policy_digest=provider["execution_policy_digest"],
    )
    service.register("subject_register", subject, CONTROL)
    now = time.time()
    freshness = sample("issuer_freshness")
    freshness.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        request_id="freshness-001",
        idempotency_key="freshness-key-001",
        issuer_id=ISSUER.name,
        issuer_epoch=1,
        observed_at=__import__("datetime")
        .datetime.fromtimestamp(now - 1, __import__("datetime").UTC)
        .isoformat(),
        valid_until=__import__("datetime")
        .datetime.fromtimestamp(now + 25, __import__("datetime").UTC)
        .isoformat(),
    )
    service.register("issuer_freshness", freshness, ISSUER)
    approval = sample("authorization_register")
    approval.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        request_id="authorization-001",
        idempotency_key="authorization-key-001",
        authorization_id="approval-001",
        issuer_id=ISSUER.name,
        actor_id="human-001",
        operation_subject_id="subject-001",
        operation_digest=v.digest(subject["specification"]),
        controller_principal=CONTROL.name,
        execution_policy_digest=provider["execution_policy_digest"],
        issued_at=freshness["observed_at"],
        expires_at=__import__("datetime")
        .datetime.fromtimestamp(now + 3600, __import__("datetime").UTC)
        .isoformat(),
        issuer_epoch=1,
    )
    service.register("authorization_register", approval, ISSUER)
    body = _load(ERRATUM / "examples/workflow-create-request-v2.valid.json")
    body["schema_version"] = "pdx_internal_runtime_provider_workflow_create_request_v3"
    plan = body["plan"]
    plan["schema_version"] = "pdx_runtime_provider_workflow_plan_v3"
    plan["budgets"]["max_external_calls"] = 100
    # An imported decision remains a real immutable dispatch record; the test
    # profile has no predecessor steps, so it can demonstrate terminal publication.
    step = deepcopy(plan["steps"][1])
    step["depends_on"] = []
    plan["steps"] = [step]
    plan["artifact_edges"] = []
    binding = sample("step_binding")
    binding.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        operation_subject_id="subject-001",
        operation_digest=approval["operation_digest"],
        provider_profile_digest=profile["record_digest"],
        authorization_id=approval["authorization_id"],
        issuer_id=ISSUER.name,
    )
    step["operation_digest"] = approval["operation_digest"]
    step["external_operation_binding"] = binding
    plan["plan_digest"] = v.digest(
        {k: x for k, x in plan.items() if k != "plan_digest"}
    )
    workflow.create(body)
    policy = dispatch.register_policy(
        plan["workflow_job_id"],
        step["workflow_step_id"],
        policy_request,
        authenticated_principal=CONTROL.name,
    )
    decision_request = _decision(policy)
    decision_record = decision_request["decision_receipt"]
    source_manifest = artifact(
        {
            "schema_version": "pdx_run_manifest_v0",
            "run_id": decision_record["source_run_id"],
            "request_id": "request-run-a",
            "status": "completed",
            "steps": [
                {
                    "step_id": decision_record["decision_step_id"],
                    "kind": "tool",
                    "name": "decide",
                    "status": "completed",
                }
            ],
            "verification": [],
            "artifact_manifest": "artifact_manifest.json",
        }
    )
    decision_request["source_manifest_artifact"] = source_manifest
    decision_record["source_manifest_artifact"] = source_manifest
    decision_record["decision_receipt_digest"] = v.digest(
        {k: x for k, x in decision_record.items() if k != "decision_receipt_digest"}
    )
    dispatch.import_decision(
        plan["workflow_job_id"],
        step["workflow_step_id"],
        decision_request,
        authenticated_principal=CONTROL.name,
    )
    activation = sample("activationRequest")
    activation.update(
        authority_id="authority-001",
        tenant_id="tenant-001",
        operation_subject_id="subject-001",
        operation_digest=approval["operation_digest"],
        authorization_id=approval["authorization_id"],
        issuer_id=ISSUER.name,
        workflow_job_id=plan["workflow_job_id"],
        workflow_step_id=step["workflow_step_id"],
        plan_digest=plan["plan_digest"],
        idempotency_key="activation-key-001",
    )
    return service, workflow, activation, artifact, count_path


def observation(
    service,
    activation,
    artifact,
    outcome="confirmed_succeeded",
    identity="observation-001",
):
    op = service.projection(activation["operation_id"], READER)
    value = sample("observationRequest")
    value.update(
        {
            k: op[k]
            for k in (
                "authority_id",
                "tenant_id",
                "operation_subject_id",
                "operation_id",
                "operation_digest",
                "provider_profile_digest",
                "account_alias",
                "environment",
                "provider_key_digest",
            )
        }
    )
    value.update(
        request_id="observe-request-001",
        observation_id=identity,
        channel="query_adapter",
        outcome=outcome,
        observed_at=__import__("datetime")
        .datetime.now(__import__("datetime").UTC)
        .isoformat(),
        provider_operation_id="remote-001",
        evidence_artifact=artifact({"provider_outcome": outcome}),
    )
    value.pop("manual_attestation", None)
    return value


def test_activation_submit_exact_retry_and_receipts(tmp_path):
    service, workflow, request, artifact, path = setup(tmp_path)
    first = service.activate(request, CONTROL)
    second = service.activate(request, CONTROL)
    assert (
        first["created"]
        and not second["created"]
        and first["operation_id"] == second["operation_id"]
    )
    service.submit(first["operation_id"], CONTROL)
    service.submit(first["operation_id"], CONTROL)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM submitted").fetchone()[0] == 1
    before = service.projection(first["operation_id"], READER)
    assert before["provider_outcome"] == "unknown" and before["reconciliation_required"]
    obs = observation(service, first, artifact)
    accepted = service.observe(obs, ADAPTER)
    assert service.observe(obs, ADAPTER) == accepted
    receipt = workflow.get_receipt(request["workflow_job_id"])
    assert receipt["status"] == "completed"
    v.shape("urn:pdx:draft:er003:parent:receipt:3", receipt)
    projection = service.projection(first["operation_id"], READER)
    assert projection["parent_terminal_receipt_artifact"] is not None
    assert service.activate(request, CONTROL)["operation_id"] == first["operation_id"]


def test_concurrent_separate_connections_one_activation(tmp_path):
    service, workflow, request, _, _ = setup(tmp_path)

    def activate():
        store = RuntimeWorkflowStore(service.store.path)
        other = ExternalOperationService(
            store,
            service.authorities,
            service.artifact_resolver,
            service.payload_schemas,
            service.adapters,
            dispatch=service.dispatch,
            observation_verifier=service.observation_verifier,
        )
        try:
            return other.activate(request, CONTROL)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: activate(), range(2)))
    assert len({x["operation_id"] for x in results}) == 1
    assert sum(x["created"] for x in results) == 1
    assert (
        workflow.get_state(request["workflow_job_id"])["counters"][
            "external_operations"
        ]
        == 1
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_digest", "0" * 64),
        ("workflow_job_id", "another-workflow"),
        ("authorization_id", "other-approval"),
    ],
)
def test_material_retry_conflicts(tmp_path, field, value):
    service, _, request, _, _ = setup(tmp_path)
    service.activate(request, CONTROL)
    with pytest.raises(v.Invalid, match="IDEMPOTENCY_CONFLICT"):
        service.activate({**request, field: value}, CONTROL)


def test_expired_exact_recovery_does_not_grant_submit(tmp_path):
    service, _, request, _, _ = setup(tmp_path)
    first = service.activate(request, CONTROL)
    now = service.clock()
    service.clock = lambda: now + 4000
    assert not service.activate(request, CONTROL)["created"]
    with pytest.raises(v.Invalid, match="AUTHORIZATION_EXPIRED"):
        service.submit(first["operation_id"], CONTROL)
    assert service.projection(first["operation_id"], READER)["submit_permits"] == 0


def test_observation_replay_conflict_and_late_fact(tmp_path):
    service, workflow, request, artifact, _ = setup(tmp_path)
    first = service.activate(request, CONTROL)
    service.submit(first["operation_id"], CONTROL)
    obs = observation(service, first, artifact)
    service.observe(obs, ADAPTER)
    terminal = deepcopy(workflow.get_receipt(request["workflow_job_id"]))
    with pytest.raises(v.Invalid, match="OBSERVATION_CONFLICT"):
        service.observe({**obs, "outcome": "confirmed_failed"}, ADAPTER)
    late = observation(service, first, artifact, "unknown", "observation-002")
    service.observe(late, ADAPTER)
    assert (
        service.projection(first["operation_id"], READER)["provider_outcome"]
        == "confirmed_succeeded"
    )
    conflict = observation(
        service, first, artifact, "confirmed_failed", "observation-003"
    )
    service.observe(conflict, ADAPTER)
    projection = service.projection(first["operation_id"], READER)
    assert (
        projection["provider_outcome"] == "confirmed_succeeded"
        and projection["reconciliation_required"]
    )
    assert workflow.get_receipt(request["workflow_job_id"]) == terminal


def test_namespace_unauthorized_and_manual_case_budget(tmp_path):
    service, _, request, _artifact, _ = setup(tmp_path)
    with pytest.raises(v.Invalid, match="UNAUTHENTICATED"):
        service.activate(request, None)
    with pytest.raises(v.Invalid, match="AUTHORITY_FORBIDDEN"):
        service.activate(request, READER)
    with pytest.raises(v.Invalid, match="RECORD_NOT_FOUND"):
        service.activate({**request, "tenant_id": "other-tenant"}, CONTROL)
    first = service.activate(request, CONTROL)
    service.submit(first["operation_id"], CONTROL)
    service.register_manual_case(first["operation_id"], "case-001", SUPERVISOR)
    with pytest.raises(v.Invalid, match="RECOVERY_BUDGET_EXHAUSTED"):
        service.register_manual_case(first["operation_id"], "case-002", SUPERVISOR)


def test_no_bypass_via_ordinary_dispatch_activation(tmp_path):
    service, _, request, _, _ = setup(tmp_path)
    from tests.test_dynamic_dispatch_service import DISPATCH

    body = _load(DISPATCH / "examples/activation-request.valid.json")
    with pytest.raises(Exception, match="use governed"):
        service.dispatch.activate(
            request["workflow_job_id"],
            request["workflow_step_id"],
            body,
            authenticated_principal=CONTROL.name,
        )


def reopen(configuration, path, *, die=False):
    store = RuntimeWorkflowStore(path / "workflow.sqlite3")
    dispatch = DynamicDispatchService(store, _registry(_policy_request()))

    def submit(payload, key):
        with sqlite3.connect(path / "provider.sqlite3") as c:
            c.execute("INSERT INTO submitted VALUES (?)", (key,))
        if die:
            os._exit(37)

    profile = configuration["profile"]
    adapter = ProviderAdapter(
        profile["submit_deployment"],
        profile["query_deployment"],
        submit,
        query=(lambda profile, key: None)
        if profile["recovery_mode"] == "query_only"
        else None,
        lookup_proof=profile["lookup_proof"],
    )
    return ExternalOperationService(
        store,
        configuration["authorities"],
        lambda art: bytes.fromhex(configuration["artifacts"][art["artifact_id"]]),
        configuration["payload_schemas"],
        {"provider-001": adapter},
        dispatch=dispatch,
        observation_verifier=lambda body, context: {"provenance_verified": True},
    )


def configuration(service):
    with service.store.transaction() as c:
        rows = c.execute(
            "SELECT body FROM external_records WHERE kind IN ('subject_register','provider_register')"
        ).fetchall()
        decisions = c.execute(
            "SELECT receipt_json FROM dynamic_dispatch_decisions"
        ).fetchall()
    artifacts = {}
    for row in rows:
        artifacts.update(
            service._artifacts(json.loads(row[0]))["authorized_artifact_bytes"]
        )
    for row in decisions:
        artifacts.update(
            service._artifacts(json.loads(row[0])["source_manifest_artifact"])[
                "authorized_artifact_bytes"
            ]
        )
    return {
        "authorities": service.authorities,
        "payload_schemas": service.payload_schemas,
        "artifacts": {k: raw.hex() for k, raw in artifacts.items()},
        "profile": json.loads(
            next(
                row[0]
                for row in rows
                if "provider_profile_id" in json.loads(row[0])
                and "specification" not in json.loads(row[0])
            )
        ),
    }


def crash_worker(config, path, request):
    service = reopen(config, Path(path), die=True)
    activated = service.activate(request, CONTROL)
    service.submit(activated["operation_id"], CONTROL)


def activation_worker(config, path, request, queue):
    service = reopen(config, Path(path))
    try:
        queue.put(service.activate(request, CONTROL))
    finally:
        service.store.close()


def test_two_processes_activation_cas(tmp_path):
    service, _, request, _, _ = setup(tmp_path)
    config = configuration(service)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    children = [
        context.Process(
            target=activation_worker, args=(config, str(tmp_path), request, queue)
        )
        for _ in range(2)
    ]
    for child in children:
        child.start()
    for child in children:
        child.join(20)
        assert child.exitcode == 0
    rows = [queue.get(timeout=3) for _ in children]
    assert (
        len({r["operation_id"] for r in rows}) == 1
        and sum(r["created"] for r in rows) == 1
    )


def test_crash_after_provider_acceptance_restart_queries_only(tmp_path):
    service, _, request, _artifact, path = setup(tmp_path, query_only=True)
    config = configuration(service)
    child = multiprocessing.get_context("spawn").Process(
        target=crash_worker, args=(config, str(tmp_path), request)
    )
    child.start()
    child.join(20)
    assert child.exitcode == 37
    restarted = reopen(config, tmp_path)
    existing = restarted.activate(request, CONTROL)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM submitted").fetchone()[0] == 1
    # The restart cannot resubmit, even though the original response never landed.
    restarted.submit(existing["operation_id"], CONTROL)
    queries = []
    adapter = restarted.adapters["provider-001"]

    def query(profile, key):
        queries.append(key)

    restarted.adapters["provider-001"] = ProviderAdapter(
        adapter.submit_deployment,
        adapter.query_deployment,
        adapter.submit,
        query,
        adapter.lookup_proof,
    )
    rec = sample("reconcile_request")
    projection = restarted.projection(existing["operation_id"], READER)
    rec.update(
        {
            k: projection[k]
            for k in (
                "authority_id",
                "tenant_id",
                "operation_id",
                "operation_digest",
                "provider_profile_digest",
            )
        }
    )
    rec.update(
        expected_sequence=projection["sequence"], idempotency_key="recovery-key-001"
    )
    result = restarted.reconcile(rec, SUPERVISOR)
    assert result["query_scheduled"] and len(queries) == 1
    assert (
        result["projection"]["provider_outcome"] == "unknown"
        and result["projection"]["reconciliation_required"]
    )
    assert not restarted.reconcile(rec, SUPERVISOR)["query_scheduled"]
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM submitted").fetchone()[0] == 1


def test_parent_cancel_keeps_reserved_subject_and_receipts(tmp_path):
    service, workflow, request, _, _ = setup(tmp_path)
    activated = service.activate(request, CONTROL)
    cancel = {
        "schema_version": "pdx_internal_runtime_workflow_cancel_request_v1",
        "request_id": "request-cancel-001",
        "workflow_job_id": request["workflow_job_id"],
        "reason": "operator_cancelled",
    }
    from importlib.resources import files

    schema = json.loads(
        files("pdx_artifact_engine.contracts.runtime_provider_workflow")
        .joinpath("pdx_runtime_workflow_cancel_v1.schema.json")
        .read_text()
    )
    cancel["schema_version"] = schema["properties"]["schema_version"]["const"]
    cancel["correlation_id"] = "correlation-cancel-001"
    workflow.cancel(request["workflow_job_id"], cancel)
    receipt = workflow.get_receipt(request["workflow_job_id"])
    v.shape("urn:pdx:draft:er003:parent:receipt:3", receipt)
    with pytest.raises(v.Invalid, match="PARENT_NOT_READY"):
        service.submit(activated["operation_id"], CONTROL)
    changed = {
        **request,
        "idempotency_key": "new-key-001xxxxx",
        "workflow_job_id": "other-workflow",
    }
    with pytest.raises(v.Invalid, match="SUBJECT_ALREADY_BOUND"):
        service.activate(changed, CONTROL)


def test_subject_retained_after_manual_nonexecution(tmp_path):
    service, _, request, artifact, _ = setup(tmp_path)
    activated = service.activate(request, CONTROL)
    service.submit(activated["operation_id"], CONTROL)
    service.register_manual_case(activated["operation_id"], "case-001", SUPERVISOR)
    value = observation(service, activated, artifact, "confirmed_not_executed")
    art = artifact({"proof": "definitive nonexecution and terminated submitter"})
    value.update(
        channel="manual_authority",
        manual_attestation={
            "case_id": "case-001",
            "attestation_artifact": art,
            "submitter_termination_artifact": art,
            "definitive_nonexecution_artifact": art,
        },
    )
    service.observe(value, MANUAL)
    projection = service.projection(activated["operation_id"], READER)
    assert projection["subject_reserved"] and not projection["resubmission_allowed"]
    assert service.submit(activated["operation_id"], CONTROL)["submit_permits"] == 1
    bad = {
        **request,
        "idempotency_key": "different-activation-001",
        "operation_digest": "0" * 64,
    }
    with pytest.raises(v.Invalid, match="SUBJECT_ALREADY_BOUND"):
        service.activate(bad, CONTROL)


def test_query_budget_exhaustion_and_manual_only_do_not_submit(tmp_path):
    service, _, request, _, _ = setup(tmp_path, query_only=True)
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    rec = sample("reconcile_request")
    for i in range(20):
        projection = service.projection(activation["operation_id"], READER)
        rec.update(
            {
                k: projection[k]
                for k in (
                    "authority_id",
                    "tenant_id",
                    "operation_id",
                    "operation_digest",
                    "provider_profile_digest",
                )
            }
        )
        rec.update(
            expected_sequence=projection["sequence"],
            idempotency_key="reconcile-key-" + str(i).zfill(3),
        )
        assert service.reconcile(rec, SUPERVISOR)["query_scheduled"]
    projection = service.projection(activation["operation_id"], READER)
    rec.update(
        expected_sequence=projection["sequence"], idempotency_key="reconcile-key-999"
    )
    with pytest.raises(v.Invalid, match="RECOVERY_BUDGET_EXHAUSTED"):
        service.reconcile(rec, SUPERVISOR)
    assert service.projection(activation["operation_id"], READER)[
        "reconciliation_required"
    ]


def test_http_transport_principal_and_stored_v3_contract(tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request

    from pdx_artifact_engine.internal_http import make_server

    service, _workflow, request, _, _ = setup(tmp_path)
    activated = service.activate(request, CONTROL)
    tokens = {"test-reader-credential": READER, "test-controller-credential": CONTROL}
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", ",".join(tokens))
    monkeypatch.setenv(
        "PDX_ENGINE_WORKFLOW_HMAC_SECRET", "01234567890123456789012345678901"
    )

    def factory(store, dispatch):
        return ExternalOperationService(
            store,
            service.authorities,
            service.artifact_resolver,
            service.payload_schemas,
            service.adapters,
            dispatch=dispatch,
            observation_verifier=service.observation_verifier,
        )

    server = make_server(
        port=0,
        db_path=service.store.path,
        staging_root=tmp_path / "staging",
        external_service_factory=factory,
        external_principal_bindings=tokens,
        dispatch_registry=service.dispatch.registry,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path, token):
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}" + path,
            headers={"Authorization": "Bearer " + token},
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        status, result = get(
            "/internal/v1/external-operations/" + activated["operation_id"],
            "test-reader-credential",
        )
        assert status == 200
        v.supporting("projection", result)
        assert 'provider_key"' not in json.dumps(result)
        status, result = get(
            "/internal/v1/runtime-provider-workflows/" + request["workflow_job_id"],
            "test-reader-credential",
        )
        assert status == 200
        v.shape("urn:pdx:draft:er003:parent:state:3", result)
        status, result = get(
            "/internal/v1/external-operations/" + activated["operation_id"],
            "test-controller-credential",
        )
        assert status == 403 and result["code"] == "AUTHORITY_FORBIDDEN"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_revocation_before_submit_and_failed_validation_roll_back(tmp_path):
    service, workflow, request, _, _ = setup(tmp_path)
    before = workflow.get_state(request["workflow_job_id"])
    with pytest.raises(v.Invalid, match="OPERATION_BINDING_MISMATCH"):
        service.activate({**request, "operation_digest": "0" * 64}, CONTROL)
    assert workflow.get_state(request["workflow_job_id"]) == before
    activated = service.activate(request, CONTROL)
    revoke = sample("authorization_revoke")
    revoke.update(
        authority_id=request["authority_id"],
        tenant_id=request["tenant_id"],
        authorization_id=request["authorization_id"],
        issuer_id=ISSUER.name,
        issuer_epoch=2,
        revocation_id="revoke-001",
    )
    service.register("authorization_revoke", revoke, ISSUER)
    with pytest.raises(v.Invalid, match="AUTHORIZATION_REVOKED"):
        service.submit(activated["operation_id"], CONTROL)
    assert service.projection(activated["operation_id"], READER)["submit_permits"] == 0


def test_manual_proof_and_evidence_fail_closed(tmp_path):
    service, _, request, artifact, _ = setup(tmp_path)
    activated = service.activate(request, CONTROL)
    service.submit(activated["operation_id"], CONTROL)
    value = observation(service, activated, artifact)
    service.observation_verifier = None
    with pytest.raises(v.Invalid, match="EVIDENCE_INVALID"):
        service.observe(value, ADAPTER)
    service.observation_verifier = lambda *_: {
        "provenance_verified": True,
        "manual_authority_fresh": True,
        "submitter_terminated": False,
        "definitive_nonexecution": True,
    }
    service.register_manual_case(activated["operation_id"], "case-001", SUPERVISOR)
    proof = artifact({"proof": "not sufficient without independent termination"})
    value.update(
        channel="manual_authority",
        outcome="confirmed_not_executed",
        manual_attestation={
            "case_id": "case-001",
            "attestation_artifact": proof,
            "submitter_termination_artifact": proof,
            "definitive_nonexecution_artifact": proof,
        },
    )
    with pytest.raises(v.Invalid, match="EVIDENCE_INVALID"):
        service.observe(value, MANUAL)
    assert (
        service.projection(activated["operation_id"], READER)["manual_cases"][0][
            "records"
        ]
        == 0
    )


def test_packaged_frozen_schema_dependencies_and_jcs():
    package = Path(v.__file__).parent
    document = ROOT / "docs/external-operations"
    for folder in ("schemas", "dependencies"):
        for source in (document / folder).glob("*.json"):
            assert (package / folder / source.name).read_text(
                encoding="utf-8"
            ) == source.read_text(encoding="utf-8")
    vectors = json.loads((document / "canonical-vectors.json").read_text())
    for item in vectors["positive"]:
        assert len(v.digest(v.parse(item["raw"]))) == 64
    for item in vectors["negative"]:
        with pytest.raises(v.Invalid):
            v.digest(v.parse(item["raw"]))


def test_parent_semantics_reject_hash_valid_conflicting_snapshot(tmp_path):
    service, workflow, request, artifact, _ = setup(tmp_path)
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    service.observe(observation(service, activation, artifact), ADAPTER)
    parent = deepcopy(workflow.get_receipt(request["workflow_job_id"]))
    service.observe(
        observation(
            service, activation, artifact, "confirmed_failed", "contradiction-proof"
        ),
        ADAPTER,
    )
    parent["step_receipts"][0]["external_operation_receipt_artifact"] = (
        service.projection(activation["operation_id"], READER)[
            "latest_receipt_artifact"
        ]
    )
    # This artifact has valid CAS bytes/hash and schema; semantic authority fails.
    with (
        pytest.raises(v.Invalid, match="OPERATION_BINDING_MISMATCH"),
        service.store.transaction() as connection,
    ):
        plan = json.loads(
            connection.execute("SELECT plan_json FROM runtime_workflows").fetchone()[0]
        )
        service.validate_parent_receipt(connection, parent, plan)


def submit_worker(config, path, request, queue):
    service = reopen(config, Path(path))
    try:
        operation = service.activate(request, CONTROL)
        queue.put(service.submit(operation["operation_id"], CONTROL))
    finally:
        service.store.close()


@pytest.mark.parametrize("conflict", [False, True])
def test_reviewer_completion_rechecks_current_external_authority(tmp_path, conflict):
    from tests.test_runtime_workflow_service import (
        _provider_activation,
        _provider_update,
    )

    service, workflow, request, artifact, _ = setup(tmp_path)
    # Build the two-step fixture before activation; finish through real APIs.
    with service.store.transaction() as connection:
        plan = json.loads(
            connection.execute("SELECT plan_json FROM runtime_workflows").fetchone()[0]
        )
        plan["steps"].append(
            {
                "workflow_step_id": "review-later",
                "step_kind": "reviewer",
                "depends_on": [request["workflow_step_id"]],
                "max_attempts": 1,
                "operation_digest": "1" * 64,
            }
        )
        plan["plan_digest"] = v.digest(
            {k: x for k, x in plan.items() if k != "plan_digest"}
        )
        request["plan_digest"] = plan["plan_digest"]
        connection.execute(
            "UPDATE runtime_workflows SET plan_json=?,plan_digest=?",
            (json.dumps(plan), plan["plan_digest"]),
        )
        connection.execute(
            "INSERT INTO runtime_workflow_steps VALUES (?,?,?,'pending',0)",
            (request["workflow_job_id"], "review-later", "reviewer"),
        )
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    service.observe(observation(service, activation, artifact), ADAPTER)
    if conflict:
        service.observe(
            observation(
                service, activation, artifact, "confirmed_failed", "late-conflict"
            ),
            ADAPTER,
        )
    claim_request = _provider_activation()
    claim_request["workflow_step_id"] = "review-later"
    claim = workflow.activate_provider(
        request["workflow_job_id"],
        claim_request,
        authenticated_instance_id=claim_request["control_plane_instance_id"],
    )
    state = workflow.update(
        request["workflow_job_id"], _provider_update(claim, 0, "outcome"), "provider"
    )
    receipt = workflow.get_receipt(request["workflow_job_id"])
    assert (
        state["state"] == receipt["status"] == ("blocked" if conflict else "completed")
    )
    if conflict:
        assert receipt["terminal_error"]["code"] == "EXTERNAL_OUTCOME_UNRESOLVED"
        assert receipt["terminal_error"]["reconcile_required"] is True
    frozen = deepcopy(receipt)
    service.observe(
        observation(
            service, activation, artifact, "confirmed_failed", "post-terminal-conflict"
        ),
        ADAPTER,
    )
    assert workflow.get_receipt(request["workflow_job_id"]) == frozen


def test_two_processes_one_submit_permit(tmp_path):
    service, _, request, _, path = setup(tmp_path)
    config = configuration(service)
    service.activate(request, CONTROL)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(
            target=submit_worker, args=(config, str(tmp_path), request, queue)
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    for _ in processes:
        assert queue.get(timeout=3)["submit_permits"] == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM submitted").fetchone()[0] == 1


def test_manual_case_record_limit_is_durable(tmp_path):
    service, _, request, artifact, _ = setup(tmp_path)
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    service.register_manual_case(activation["operation_id"], "case-001", SUPERVISOR)
    for i in range(16):
        value = observation(
            service,
            activation,
            artifact,
            "confirmed_succeeded",
            "manual-observation-" + str(i).zfill(3),
        )
        value.update(
            channel="manual_authority",
            manual_attestation={
                "case_id": "case-001",
                "attestation_artifact": artifact({"manual_evidence": i}),
            },
        )
        service.observe(value, MANUAL)
    value["observation_id"] = "manual-observation-999"
    with pytest.raises(v.Invalid, match="RECOVERY_BUDGET_EXHAUSTED"):
        service.observe(value, MANUAL)
    assert (
        service.projection(activation["operation_id"], READER)["manual_cases"][0][
            "records"
        ]
        == 16
    )


def test_query_response_after_deadline_is_fenced(tmp_path):
    service, _, request, artifact, _ = setup(tmp_path, query_only=True)
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    adapter = service.adapters["provider-001"]
    now = service.clock()
    value = observation(service, activation, artifact)

    def late_query(profile, key):
        service.clock = lambda: now + 31
        return value

    service.adapters["provider-001"] = ProviderAdapter(
        adapter.submit_deployment,
        adapter.query_deployment,
        adapter.submit,
        late_query,
        adapter.lookup_proof,
    )
    projection = service.projection(activation["operation_id"], READER)
    request = sample("reconcile_request")
    request.update(
        {
            k: projection[k]
            for k in (
                "authority_id",
                "tenant_id",
                "operation_id",
                "operation_digest",
                "provider_profile_digest",
            )
        }
    )
    request.update(expected_sequence=projection["sequence"])
    with pytest.raises(v.Invalid, match="STALE_EXECUTION_CLAIM"):
        service.reconcile(request, SUPERVISOR)
    projection = service.projection(activation["operation_id"], READER)
    assert (
        projection["provider_outcome"] == "unknown"
        and projection["consumed"]["observation_records"] == 0
    )


def test_registered_query_principal_with_multiple_adapters(tmp_path):
    service, _, request, artifact, _ = setup(tmp_path, query_only=True)
    service.authorities[0]["adapter_principals"].append("adapter-other")
    activation = service.activate(request, CONTROL)
    service.submit(activation["operation_id"], CONTROL)
    value = observation(service, activation, artifact, "unknown")
    adapter = service.adapters["provider-001"]
    service.adapters["provider-001"] = ProviderAdapter(
        adapter.submit_deployment,
        adapter.query_deployment,
        adapter.submit,
        lambda *_: value,
        adapter.lookup_proof,
        principal=ADAPTER,
    )
    projection = service.projection(activation["operation_id"], READER)
    rec = sample("reconcile_request")
    rec.update(
        {
            k: projection[k]
            for k in (
                "authority_id",
                "tenant_id",
                "operation_id",
                "operation_digest",
                "provider_profile_digest",
            )
        }
    )
    rec["expected_sequence"] = projection["sequence"]
    result = service.reconcile(rec, SUPERVISOR)
    assert (
        result["query_scheduled"]
        and result["projection"]["consumed"]["observation_records"] == 1
    )
