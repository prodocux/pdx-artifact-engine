"""Transactional approval use, one-shot submission and query-only recovery.

Only deployment-owned principals, adapters and artifact resolvers establish trust.
All durable records share RuntimeWorkflowStore and its BEGIN IMMEDIATE boundary.
No provider call runs inside a database transaction.
"""

from __future__ import annotations

import json
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator

from pdx_artifact_engine.contracts.external_operations import validation as v
from pdx_artifact_engine.runtime_workflows.service import RuntimeWorkflowService
from pdx_artifact_engine.runtime_workflows.store import RuntimeWorkflowStore


@dataclass(frozen=True)
class Principal:
    """Created by authenticated transport, never deserialized from a body."""

    name: str
    instance_id: str


@dataclass(frozen=True)
class ProviderAdapter:
    """Deployment-registered implementation and independently verified identities."""

    submit_deployment: dict
    query_deployment: dict | None
    submit: Callable[[dict, str], None]
    query: Callable[[dict, str], dict | None] | None = None
    lookup_proof: dict | None = None
    query_timeout_seconds: int = 30
    principal: Principal | None = None


def _id(prefix):
    return prefix + "_" + uuid.uuid4().hex


def _iso(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


@dataclass
class ExternalOperationService:
    store: RuntimeWorkflowStore
    authorities: list[dict]
    artifact_resolver: Callable[[dict], bytes]
    payload_schemas: dict[str, dict]
    adapters: dict[str, ProviderAdapter] = field(default_factory=dict)
    clock: Callable[[], float] = time.time
    dispatch: Any = None
    observation_verifier: Callable[[dict, dict], dict] | None = None

    def __post_init__(self):
        self.store.external_operations = self
        self.authorities = json.loads(_json(self.authorities))
        for config in self.authorities:
            v.supporting("authority_config", config)
        with self.store.transaction() as c:
            # Additive tables in the existing workflow database, not another store.
            for sql in (
                "CREATE TABLE IF NOT EXISTS external_records (namespace TEXT, kind TEXT, record_id TEXT, body TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(namespace,kind,record_id))",
                "CREATE TABLE IF NOT EXISTS external_idempotency (namespace TEXT, kind TEXT, key TEXT, binding TEXT NOT NULL, record_id TEXT NOT NULL, PRIMARY KEY(namespace,kind,key))",
                "CREATE TABLE IF NOT EXISTS external_operations (operation_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, subject TEXT NOT NULL, authorization TEXT NOT NULL, workflow_job_id TEXT NOT NULL, workflow_step_id TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(namespace,subject), UNIQUE(namespace,authorization), UNIQUE(workflow_job_id,workflow_step_id))",
                "CREATE TABLE IF NOT EXISTS external_observations (operation_id TEXT, observation_id TEXT, binding TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(operation_id,observation_id))",
            ):
                c.execute(sql)

    def _ns(self, body):
        return _json([body["authority_id"], body["tenant_id"]])

    def authorize_parent(self, plan, principal, role):
        bindings = [
            s["external_operation_binding"]
            for s in plan["steps"]
            if "external_operation_binding" in s
        ]
        v.require(bool(bindings), "OPERATION_BINDING_MISMATCH")
        for binding in bindings:
            self._auth(binding, principal, role)

    def validate_parent_bindings(self, connection, plan):
        for step in plan["steps"]:
            binding = step.get("external_operation_binding")
            if binding is None:
                continue
            subject = self._get(
                connection,
                self._ns(binding),
                "subject_register",
                binding["operation_subject_id"],
            )
            approval = self._get(
                connection,
                self._ns(binding),
                "authorization_register",
                binding["authorization_id"],
            )
            for key in ("operation_subject_id", "operation_digest", "issuer_id"):
                v.require(binding[key] == approval[key], "OPERATION_BINDING_MISMATCH")
            v.require(
                v.digest(subject["specification"]) == binding["operation_digest"]
                and subject["specification"]["provider_profile_digest"]
                == binding["provider_profile_digest"],
                "OPERATION_BINDING_MISMATCH",
            )

    def _auth(self, body, principal, role):
        v.require(
            isinstance(principal, Principal)
            and principal.name
            and principal.instance_id,
            "UNAUTHENTICATED",
        )
        config = next(
            (
                x
                for x in self.authorities
                if x["authority_id"] == body["authority_id"]
                and x["tenant_id"] == body["tenant_id"]
            ),
            None,
        )
        v.require(config is not None, "RECORD_NOT_FOUND")
        roles = role.split("|")
        v.require(
            any(principal.name in config[r + "_principals"] for r in roles),
            "AUTHORITY_FORBIDDEN",
        )
        chosen = next(r for r in roles if principal.name in config[r + "_principals"])
        return {
            "authenticated": True,
            "role": chosen,
            "principal": principal.name,
            "instance_id": principal.instance_id,
            "authority_id": body["authority_id"],
            "tenant_id": body["tenant_id"],
            "now": _iso(self.clock()),
        }

    def _get(self, c, namespace, kind, record_id):
        row = c.execute(
            "SELECT body FROM external_records WHERE namespace=? AND kind=? AND record_id=?",
            (namespace, kind, record_id),
        ).fetchone()
        v.require(row is not None, "RECORD_NOT_FOUND")
        return json.loads(row[0])

    def _put(self, c, namespace, kind, record_id, body):
        row = c.execute(
            "SELECT body FROM external_records WHERE namespace=? AND kind=? AND record_id=?",
            (namespace, kind, record_id),
        ).fetchone()
        if row:
            v.require(json.loads(row[0]) == body, "IDEMPOTENCY_CONFLICT")
            return
        c.execute(
            "INSERT INTO external_records VALUES (?,?,?,?,?)",
            (namespace, kind, record_id, _json(body), v.digest(body)),
        )

    def _artifacts(self, value):
        context = {
            "authorized_artifact_bytes": {},
            "authorized_artifact_identities": {},
        }

        def visit(x):
            if isinstance(x, dict):
                if x.get("schema_version") == "prodocux_opaque_artifact_v1":
                    try:
                        raw = self.artifact_resolver(x)
                    except Exception as exc:
                        raise v.Invalid("EVIDENCE_INVALID") from exc
                    v.require(
                        isinstance(raw, bytes)
                        and v.sha(raw) == x["sha256"]
                        and len(raw) == x["size_bytes"],
                        "EVIDENCE_INVALID",
                    )
                    context["authorized_artifact_bytes"][x["artifact_id"]] = raw
                    context["authorized_artifact_identities"][x["artifact_id"]] = x
                else:
                    for child in x.values():
                        visit(child)
            elif isinstance(x, list):
                for child in x:
                    visit(child)

        visit(value)
        return context

    def _idempotency(self, c, ns, kind, body, principal):
        binding = v.digest(
            {
                **{k: x for k, x in body.items() if k != "request_id"},
                "principal": principal.name,
                "instance": principal.instance_id,
            }
        )
        row = c.execute(
            "SELECT binding,record_id FROM external_idempotency WHERE namespace=? AND kind=? AND key=?",
            (ns, kind, body["idempotency_key"]),
        ).fetchone()
        if row:
            v.require(row["binding"] == binding, "IDEMPOTENCY_CONFLICT")
        return binding, row["record_id"] if row else None

    def _record_idempotency(self, c, ns, kind, body, binding, record_id):
        c.execute(
            "INSERT INTO external_idempotency VALUES (?,?,?,?,?)",
            (ns, kind, body["idempotency_key"], binding, record_id),
        )

    def register(self, kind, body, principal):
        roles = {
            "provider_register": "administrator",
            "subject_register": "controller",
            "authorization_register": "issuer",
            "authorization_revoke": "issuer",
            "issuer_freshness": "issuer",
        }
        v.shape("urn:pdx:draft:er003:support:2#/$defs/" + kind, body)
        context = self._auth(body, principal, roles[kind])
        context.update(self._artifacts(body))
        ns = self._ns(body)
        with self.store.transaction() as c:
            binding, existing = self._idempotency(c, ns, kind, body, principal)
            if existing:
                record = self._get(c, ns, kind, existing)
                return self._registration(body, existing, v.digest(record), False)
            if kind == "provider_register":
                adapter = self.adapters.get(body["provider_profile_id"])
                v.require(
                    adapter is not None
                    and adapter.submit_deployment == body["submit_deployment"]
                    and adapter.query_deployment == body["query_deployment"],
                    "PROVIDER_PROFILE_UNSUPPORTED",
                )
                for dep in (body["submit_deployment"], body["query_deployment"]):
                    if dep:
                        v.require(
                            dep["identity_digest"]
                            == v.digest(
                                {k: x for k, x in dep.items() if k != "identity_digest"}
                            ),
                            "EVIDENCE_INVALID",
                        )
                context["lookup_proof_verified"] = (
                    adapter.lookup_proof == body["lookup_proof"]
                    and adapter.query is not None
                )
                record_id = body["provider_profile_id"] + ":" + str(body["revision"])
            elif kind == "subject_register":
                spec = body["specification"]
                profile = self._get(
                    c,
                    ns,
                    "provider_register",
                    spec["provider_profile_id"]
                    + ":"
                    + str(spec["provider_profile_revision"]),
                )
                context["provider_profile_digest"] = v.digest(profile)
                context["provider_profile"] = {
                    **profile,
                    "provider_profile_id": profile["provider_profile_id"],
                    "provider_profile_revision": profile["revision"],
                    "executor_identity_digest": profile["submit_deployment"][
                        "identity_digest"
                    ],
                }
                context["payload_schema_id"] = spec["payload_schema_id"]
                context["payload_schema"] = self.payload_schemas.get(
                    spec["payload_schema_id"]
                )
                record_id = body["operation_subject_id"]
            else:
                context["issuer_id"] = body["issuer_id"]
                # The registered issuer identity, not its body label, is authority.
                v.require(principal.name == body["issuer_id"], "AUTHORITY_FORBIDDEN")
                row = c.execute(
                    "SELECT body FROM external_records WHERE namespace=? AND kind=? AND record_id=?",
                    (ns, "issuer_state", body["issuer_id"]),
                ).fetchone()
                state = json.loads(row[0]) if row else {"issuer_epoch": 0}
                context["issuer_epoch"] = state["issuer_epoch"]
                if kind == "authorization_register":
                    subject = self._get(
                        c, ns, "subject_register", body["operation_subject_id"]
                    )
                    context["subject"] = {
                        **subject,
                        "operation_digest": v.digest(subject["specification"]),
                        "execution_policy_digest": subject["specification"][
                            "execution_policy_digest"
                        ],
                    }
                    record_id = body["authorization_id"]
                else:
                    if kind == "authorization_revoke":
                        approval = self._get(
                            c, ns, "authorization_register", body["authorization_id"]
                        )
                        v.require(
                            approval["issuer_id"] == body["issuer_id"],
                            "AUTHORITY_FORBIDDEN",
                        )
                        record_id = body["revocation_id"]
                    else:
                        # The authority's clock must lie inside the asserted freshness.
                        context["last_observed_at"] = state.get(
                            "observed_at", body["observed_at"]
                        )
                        record_id = _id("freshness")
            v.supporting(kind, body, context)
            if kind in ("issuer_freshness", "authorization_revoke"):
                next_state = {**state, "issuer_epoch": body["issuer_epoch"]}
                if kind == "issuer_freshness":
                    next_state.update(
                        {
                            k: body[k]
                            for k in ("issuer_id", "observed_at", "valid_until")
                        }
                    )
                c.execute(
                    "INSERT OR REPLACE INTO external_records VALUES (?,?,?,?,?)",
                    (
                        ns,
                        "issuer_state",
                        body["issuer_id"],
                        _json(next_state),
                        v.digest(next_state),
                    ),
                )
            record = {
                k: x
                for k, x in body.items()
                if k not in ("request_id", "idempotency_key")
            }
            self._put(c, ns, kind, record_id, record)
            self._record_idempotency(c, ns, kind, body, binding, record_id)
            return self._registration(body, record_id, v.digest(record), True)

    def _registration(self, body, record_id, digest, created):
        result = {
            "schema_version": "pdx_er003_registration_response_draft_v2",
            **{k: body[k] for k in ("authority_id", "tenant_id", "request_id")},
            "record_id": record_id,
            "record_digest": digest,
            "created": created,
        }
        v.supporting("registration_response", result)
        return result

    def _operation(self, c, operation_id, principal, role):
        row = c.execute(
            "SELECT body FROM external_operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        v.require(row is not None, "RECORD_NOT_FOUND")
        op = json.loads(row[0])
        self._auth(op, principal, role)
        return op

    def _save(self, c, op):
        c.execute(
            "UPDATE external_operations SET body=? WHERE operation_id=?",
            (_json(op), op["operation_id"]),
        )

    def _cas(self, c, body):
        raw = __import__("rfc8785").dumps(body)
        v.require(self.dispatch is not None, "STORAGE_UNAVAILABLE")
        return self.dispatch._cas_put(c, raw, "application/json")

    def _snapshot(self, c, op):
        previous = op.get("latest_receipt")
        op["sequence"] += 1
        common = {
            k: op[k]
            for k in (
                "authority_id",
                "tenant_id",
                "operation_subject_id",
                "operation_id",
                "operation_digest",
                "workflow_job_id",
                "workflow_step_id",
                "plan_digest",
                "authorization_id",
                "issuer_id",
                "provider_profile_digest",
                "provider_key_digest",
                "account_alias",
                "environment",
                "submission_evidence",
                "provider_outcome",
                "reconciliation_required",
                "subject_reserved",
                "submit_permits",
                "resubmission_allowed",
            )
        }
        receipt = {
            "schema_version": "pdx_er003_receipt_draft_v2",
            **common,
            "receipt_id": _id("receipt"),
            "sequence": op["sequence"],
            "activation_id": op["activation_id"],
            "activation_binding_digest": op["activation_binding_digest"],
            "authorization_record_digest": op["authorization_record_digest"],
            "observation_artifacts": op["observations"],
            "conflict_artifacts": op["conflicts"],
            "consumed": op["consumed"],
            "manual_cases": op["manual_cases"],
            "recorded_at": _iso(self.clock()),
            "previous_receipt_digest": previous["receipt_digest"] if previous else None,
            "parent_terminal_receipt_artifact": op["parent_terminal_receipt_artifact"],
        }
        receipt["receipt_digest"] = v.digest(receipt)
        v.supporting("receipt", receipt, {"previous_receipt": previous})
        op["latest_receipt_artifact"] = self._cas(c, receipt)
        op["latest_receipt"] = receipt
        self._save(c, op)
        return op["latest_receipt_artifact"]

    def projection(self, operation_id, principal):
        with self.store.transaction() as c:
            return self._projection(
                self._operation(c, operation_id, principal, "reader")
            )

    def _projection(self, op):
        fields = v.SCHEMAS["urn:pdx:draft:er003:support:2"]["$defs"]["projection"][
            "required"
        ]
        result = {k: op[k] for k in fields if k != "schema_version"}
        result["schema_version"] = "pdx_er003_projection_draft_v2"
        v.supporting("projection", result)
        return result

    def receipt(self, operation_id, receipt_id, principal):
        with self.store.transaction() as c:
            self._operation(c, operation_id, principal, "reader")
            for row in c.execute(
                "SELECT content FROM dynamic_dispatch_cas WHERE media_type='application/json'"
            ):
                try:
                    item = v.parse(bytes(row[0]))
                except v.Invalid:
                    continue
                if not isinstance(item, dict):
                    continue
                if (
                    item.get("receipt_id") == receipt_id
                    and item.get("operation_id") == operation_id
                ):
                    return item
        raise v.Invalid("RECORD_NOT_FOUND")

    def _approval_context(self, c, op, principal):
        ns = self._ns(op)
        approval = self._get(c, ns, "authorization_register", op["authorization_id"])
        subject = self._get(c, ns, "subject_register", op["operation_subject_id"])
        state = self._get(c, ns, "issuer_state", op["issuer_id"])
        context = self._auth(op, principal, "controller")
        context.update(
            approval=approval,
            subject={
                **subject,
                "operation_digest": v.digest(subject["specification"]),
                "execution_policy_digest": subject["specification"][
                    "execution_policy_digest"
                ],
            },
            issuer_epoch=state["issuer_epoch"],
            freshness=state,
        )
        return context

    def activate(self, body, principal):
        v.shape("urn:pdx:draft:er003:core:1#/$defs/activationRequest", body)
        context = self._auth(body, principal, "controller")
        ns = self._ns(body)
        with self.store.transaction() as c:
            binding, existing_id = self._idempotency(
                c, ns, "activation", body, principal
            )
            if existing_id:
                op = self._operation(c, existing_id, principal, "controller")
                return self._activation_response(body, op, False)
            subject_existing = c.execute(
                "SELECT body FROM external_operations WHERE namespace=? AND subject=?",
                (ns, body["operation_subject_id"]),
            ).fetchone()
            if subject_existing:
                op = json.loads(subject_existing[0])
                v.require(
                    op["cross_key_binding"]
                    == v.activation_binding(body, context, False),
                    "SUBJECT_ALREADY_BOUND",
                )
                self._record_idempotency(
                    c, ns, "activation", body, binding, op["operation_id"]
                )
                return self._activation_response(body, op, False)
            context.update(self._approval_context(c, body, principal))
            used = c.execute(
                "SELECT 1 FROM external_operations WHERE namespace=? AND authorization=?",
                (ns, body["authorization_id"]),
            ).fetchone()
            context["authorization_used"] = bool(used)
            workflow = c.execute(
                "SELECT * FROM runtime_workflows WHERE workflow_job_id=?",
                (body["workflow_job_id"],),
            ).fetchone()
            v.require(
                workflow is not None and workflow["contract_version"] == 3,
                "PARENT_NOT_READY",
            )
            plan = json.loads(workflow["plan_json"])
            step = next(
                (
                    s
                    for s in plan["steps"]
                    if s["workflow_step_id"] == body["workflow_step_id"]
                ),
                None,
            )
            v.require(
                step is not None and "external_operation_binding" in step,
                "OPERATION_BINDING_MISMATCH",
            )
            for key, item in step["external_operation_binding"].items():
                if key in body and key != "schema_version":
                    v.require(body[key] == item, "OPERATION_BINDING_MISMATCH")
            row = c.execute(
                "SELECT * FROM runtime_workflow_steps WHERE workflow_job_id=? AND workflow_step_id=?",
                (body["workflow_job_id"], body["workflow_step_id"]),
            ).fetchone()
            ready = row is not None and row["state"] == "pending"
            for dependency in step["depends_on"]:
                dep = c.execute(
                    "SELECT state FROM runtime_workflow_steps WHERE workflow_job_id=? AND workflow_step_id=?",
                    (body["workflow_job_id"], dependency),
                ).fetchone()
                ready = ready and dep is not None and dep[0] == "succeeded"
            context.update(
                parent_active=workflow["state"] in ("pending", "running"),
                step_ready=ready,
                workflow_job_id=workflow["workflow_job_id"],
                workflow_step_id=step["workflow_step_id"],
                plan_digest=workflow["plan_digest"],
            )
            v.engine_activation(body, context)
            # A real frozen dispatch policy and stored immutable decision remain mandatory.
            v.require(
                self.dispatch is not None and self.dispatch.registry is not None,
                "PARENT_NOT_READY",
            )
            policy_row = c.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE dispatch_policy_id=? AND workflow_job_id=? AND workflow_step_id=?",
                (
                    step["dispatch_policy_id"],
                    body["workflow_job_id"],
                    body["workflow_step_id"],
                ),
            ).fetchone()
            decision_row = c.execute(
                "SELECT * FROM dynamic_dispatch_decisions WHERE workflow_job_id=? AND workflow_step_id=?",
                (body["workflow_job_id"], body["workflow_step_id"]),
            ).fetchone()
            v.require(
                policy_row is not None and decision_row is not None, "PARENT_NOT_READY"
            )
            policy = json.loads(policy_row["policy_json"])
            decision = json.loads(decision_row["receipt_json"])
            manifest_artifact = decision["source_manifest_artifact"]
            source = self._artifacts(manifest_artifact)["authorized_artifact_bytes"][
                manifest_artifact["artifact_id"]
            ]
            manifest = v.parse(source)
            v.require(
                isinstance(manifest, dict)
                and manifest.get("run_id") == decision["source_run_id"]
                and manifest.get("status") == "completed",
                "EVIDENCE_INVALID",
            )
            v.require(
                any(
                    s.get("step_id") == step["decision_step_id"]
                    and s.get("status") == "completed"
                    for s in manifest.get("steps", [])
                    if isinstance(s, dict)
                ),
                "EVIDENCE_INVALID",
            )
            v.require(
                decision["source_plan_digest"] == step["run_a_plan_digest"]
                and decision["decision_step_id"] == step["decision_step_id"],
                "OPERATION_BINDING_MISMATCH",
            )
            v.require(
                policy_row["policy_status"] == "active"
                and (
                    policy["expires_at"] is None
                    or v.timestamp(policy["expires_at"]).timestamp() > self.clock()
                ),
                "AUTHORIZATION_REVOKED",
            )
            tool = self.dispatch.registry.get(decision["tool_name"])
            expected = next(
                (
                    x
                    for x in policy["allowed_tools"]
                    if x["name"] == decision["tool_name"]
                ),
                None,
            )
            v.require(
                tool is not None
                and tool.frozen_definition == expected
                and decision["policy_digest"] == policy["policy_digest"],
                "OPERATION_BINDING_MISMATCH",
            )
            v.require(
                Draft202012Validator(tool.input_schema).is_valid(decision["arguments"]),
                "EVIDENCE_INVALID",
            )
            subject = context["subject"]
            spec = subject["specification"]
            payload = self._artifacts(spec)["authorized_artifact_bytes"][
                spec["payload_artifact"]["artifact_id"]
            ]
            v.require(
                v.parse(payload) == decision["arguments"], "OPERATION_BINDING_MISMATCH"
            )
            profile = self._get(
                c,
                ns,
                "provider_register",
                spec["provider_profile_id"]
                + ":"
                + str(spec["provider_profile_revision"]),
            )
            v.require(
                spec["provider_profile_digest"]
                == step["external_operation_binding"]["provider_profile_digest"]
                == v.digest(profile),
                "OPERATION_BINDING_MISMATCH",
            )
            v.require(
                expected["deployment"] == profile["submit_deployment"],
                "OPERATION_BINDING_MISMATCH",
            )
            counters = json.loads(workflow["counters_json"])
            budgets = plan["budgets"]
            v.require(
                counters["external_operations"] < budgets["max_external_operations"]
                and counters["dispatch_attempts"] < budgets["max_dispatch_attempts"]
                and counters["active_steps"] < budgets["max_concurrent_steps"]
                and row["attempt_count"] < step["max_attempts"],
                "RECOVERY_BUDGET_EXHAUSTED",
            )
            key = secrets.token_hex(16)
            op = {
                **{
                    k: body[k]
                    for k in (
                        "authority_id",
                        "tenant_id",
                        "operation_subject_id",
                        "operation_digest",
                        "workflow_job_id",
                        "workflow_step_id",
                        "plan_digest",
                        "authorization_id",
                        "issuer_id",
                    )
                },
                "operation_id": _id("operation"),
                "activation_id": _id("activation"),
                "activation_binding_digest": v.activation_binding(body, context),
                "cross_key_binding": v.activation_binding(body, context, False),
                "authorization_record_digest": v.digest(context["approval"]),
                "provider_profile_digest": v.digest(profile),
                "provider_profile": profile,
                "provider_key": key,
                "provider_key_digest": v.sha(key.encode()),
                "account_alias": profile["account_alias"],
                "environment": profile["environment"],
                "submission_evidence": "not_started",
                "provider_outcome": "unobserved",
                "reconciliation_required": False,
                "subject_reserved": True,
                "submit_permits": 0,
                "resubmission_allowed": False,
                "sequence": 0,
                "recovery_mode": profile["recovery_mode"],
                "provider_operation_id": None,
                "consumed": {
                    "query_calls": 0,
                    "query_execution_ms": 0,
                    "scheduling_elapsed_seconds": 0,
                    "observation_records": 0,
                    "evidence_bytes": 0,
                },
                "manual_cases": [],
                "latest_receipt_artifact": None,
                "parent_terminal_receipt_artifact": None,
                "conflict_count": 0,
                "observations": [],
                "conflicts": [],
                "created_at": self.clock(),
                "controller": principal.name,
                "controller_instance": principal.instance_id,
                "activation_request": body,
                "payload": v.parse(payload),
                "claim_fence": 0,
                "query_claim": None,
                "dispatch_policy_digest": policy["policy_digest"],
                "tool_name": decision["tool_name"],
            }
            c.execute(
                "INSERT INTO external_operations VALUES (?,?,?,?,?,?,?)",
                (
                    op["operation_id"],
                    ns,
                    body["operation_subject_id"],
                    body["authorization_id"],
                    body["workflow_job_id"],
                    body["workflow_step_id"],
                    _json(op),
                ),
            )
            self._record_idempotency(
                c, ns, "activation", body, binding, op["operation_id"]
            )
            for k in (
                "external_operations",
                "dispatch_attempts",
                "active_dispatches",
                "active_steps",
            ):
                counters[k] += 1
            c.execute(
                "UPDATE runtime_workflow_steps SET state='running',attempt_count=attempt_count+1 WHERE workflow_job_id=? AND workflow_step_id=?",
                (op["workflow_job_id"], op["workflow_step_id"]),
            )
            c.execute(
                "UPDATE runtime_workflows SET state='running', counters_json=? WHERE workflow_job_id=?",
                (_json(counters), op["workflow_job_id"]),
            )
            self._snapshot(c, op)
            return self._activation_response(body, op, True)

    def _activation_response(self, body, op, created):
        fields = v.SCHEMAS["urn:pdx:draft:er003:support:2"]["$defs"][
            "activation_response"
        ]["required"]
        result = {
            k: op[k]
            for k in fields
            if k not in ("schema_version", "request_id", "created")
        }
        result.update(
            schema_version="pdx_er003_activation_response_draft_v2",
            request_id=body["request_id"],
            created=created,
        )
        v.supporting("activation_response", result)
        return result

    def submit(self, operation_id, principal):
        """Internal worker entry. A lost response never leads to another submit."""
        with self.store.transaction() as c:
            op = self._operation(c, operation_id, principal, "controller")
            v.require(
                op["controller"] == principal.name
                and op["controller_instance"] == principal.instance_id,
                "AUTHORITY_FORBIDDEN",
            )
            if op["submit_permits"]:
                return self._projection(op)
            context = self._approval_context(c, op, principal)
            context.update(
                parent_active=True,
                step_ready=True,
                workflow_job_id=op["workflow_job_id"],
                workflow_step_id=op["workflow_step_id"],
                plan_digest=op["plan_digest"],
            )
            v.engine_activation(op["activation_request"], context)
            workflow = c.execute(
                "SELECT * FROM runtime_workflows WHERE workflow_job_id=?",
                (op["workflow_job_id"],),
            ).fetchone()
            v.require(workflow["state"] in ("pending", "running"), "PARENT_NOT_READY")
            policy = c.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE workflow_job_id=? AND workflow_step_id=?",
                (op["workflow_job_id"], op["workflow_step_id"]),
            ).fetchone()
            v.require(
                policy["policy_status"] == "active"
                and policy["policy_digest"] == op["dispatch_policy_digest"],
                "AUTHORIZATION_REVOKED",
            )
            adapter = self.adapters.get(op["provider_profile"]["provider_profile_id"])
            v.require(
                adapter is not None
                and adapter.submit_deployment
                == op["provider_profile"]["submit_deployment"],
                "PROVIDER_PROFILE_UNSUPPORTED",
            )
            registered_tool = (
                self.dispatch.registry.get(op["tool_name"])
                if self.dispatch and self.dispatch.registry
                else None
            )
            policy_document = json.loads(policy["policy_json"])
            expected_tool = next(
                (
                    x
                    for x in policy_document["allowed_tools"]
                    if x["name"] == op["tool_name"]
                ),
                None,
            )
            v.require(
                registered_tool is not None
                and registered_tool.frozen_definition == expected_tool,
                "OPERATION_BINDING_MISMATCH",
            )
            v.require(
                policy_document["expires_at"] is None
                or v.timestamp(policy_document["expires_at"]).timestamp()
                > self.clock(),
                "AUTHORIZATION_EXPIRED",
            )
            counters = json.loads(workflow["counters_json"])
            budgets = json.loads(workflow["plan_json"])["budgets"]
            v.require(
                counters["external_calls"] < budgets["max_external_calls"],
                "RECOVERY_BUDGET_EXHAUSTED",
            )
            counters["external_calls"] += 1
            c.execute(
                "UPDATE runtime_workflows SET counters_json=? WHERE workflow_job_id=?",
                (_json(counters), op["workflow_job_id"]),
            )
            op.update(
                submit_permits=1,
                submission_evidence="possibly_submitted",
                provider_outcome="unknown",
                reconciliation_required=True,
                claim_fence=op["claim_fence"] + 1,
            )
            permit = {
                k: op[k]
                for k in (
                    "authority_id",
                    "tenant_id",
                    "operation_subject_id",
                    "operation_id",
                    "operation_digest",
                    "workflow_job_id",
                    "workflow_step_id",
                    "plan_digest",
                    "authorization_id",
                    "issuer_id",
                    "provider_profile_digest",
                    "provider_key_digest",
                    "account_alias",
                    "environment",
                )
            }
            permit.update(
                schema_version="pdx_er003_submit_permit_record_draft_v2",
                permit_id=_id("permit"),
                claim_id=_id("claim"),
                claim_fence=op["claim_fence"],
                permit_sequence=1,
                submission_evidence="possibly_submitted",
                issued_at=_iso(self.clock()),
            )
            permit["intent_digest"] = v.digest(permit)
            v.supporting("submit_permit_record", permit)
            self._put(c, self._ns(op), "submit_permit", op["operation_id"], permit)
            self._snapshot(c, op)
        try:
            adapter.submit(op["payload"], op["provider_key"])
        except Exception:  # noqa: BLE001 - registered adapter boundary
            # Do not serialize exception text, which may contain secrets or URLs.
            return self._projection(op)
        return self._projection(op)

    def register_manual_case(self, operation_id, case_id, principal):
        with self.store.transaction() as c:
            op = self._operation(c, operation_id, principal, "supervisor")
            if op["manual_cases"]:
                v.require(
                    op["manual_cases"][0]["case_id"] == case_id,
                    "RECOVERY_BUDGET_EXHAUSTED",
                )
                return self._projection(op)
            v.shape("urn:pdx:draft:er003:core:1#/$defs/id", case_id)
            op["manual_cases"] = [
                {"case_id": case_id, "records": 0, "evidence_bytes": 0}
            ]
            self._snapshot(c, op)
            return self._projection(op)

    def observe(self, body, principal, *, query_claim=None):
        v.shape("urn:pdx:draft:er003:core:1#/$defs/observationRequest", body)
        role = "adapter" if body["channel"] == "query_adapter" else "manual"
        context = self._auth(body, principal, role)
        context.update(self._artifacts(body))
        # Signature/provenance/termination facts come from a registered verifier.
        v.require(self.observation_verifier is not None, "EVIDENCE_INVALID")
        facts = self.observation_verifier(body, context)
        v.require(
            isinstance(facts, dict) and facts.get("provenance_verified") is True,
            "EVIDENCE_INVALID",
        )
        for key in (
            "provenance_verified",
            "manual_authority_fresh",
            "submitter_terminated",
            "definitive_nonexecution",
        ):
            context[key] = facts.get(key, False)
        with self.store.transaction() as c:
            op = self._operation(c, body["operation_id"], principal, role)
            context["operation"] = op
            if query_claim is not None:
                v.require(
                    op["query_claim"] is not None
                    and op["query_claim"]["claim_id"] == query_claim["claim_id"]
                    and op["query_claim"]["claim_fence"] == query_claim["claim_fence"]
                    and self.clock() < v.timestamp(query_claim["deadline"]).timestamp(),
                    "STALE_EXECUTION_CLAIM",
                )
            row = c.execute(
                "SELECT * FROM external_observations WHERE operation_id=? AND observation_id=?",
                (op["operation_id"], body["observation_id"]),
            ).fetchone()
            context["existing_observation_digest"] = row["binding"] if row else None
            context["confirmed_outcome"] = (
                op["provider_outcome"]
                if op["provider_outcome"].startswith("confirmed_")
                else None
            )
            context["case_registered"] = (
                op["manual_cases"][0]["case_id"] if op["manual_cases"] else None
            )
            disposition = v.observation(body, context)
            if row:
                response = json.loads(row["response"])
                response["request_id"] = body["request_id"]
                return response
            v.require(op["submit_permits"] == 1, "STALE_EXECUTION_CLAIM")
            sizes = sum(
                a["size_bytes"]
                for a in context["authorized_artifact_identities"].values()
            )
            if role == "manual":
                case = op["manual_cases"][0]
                v.require(
                    case["records"] < 16 and case["evidence_bytes"] + sizes <= 1048576,
                    "RECOVERY_BUDGET_EXHAUSTED",
                )
                case["records"] += 1
                case["evidence_bytes"] += sizes
            else:
                v.require(
                    op["consumed"]["observation_records"] < 64
                    and op["consumed"]["evidence_bytes"] + sizes <= 1048576,
                    "RECOVERY_BUDGET_EXHAUSTED",
                )
                op["consumed"]["observation_records"] += 1
                op["consumed"]["evidence_bytes"] += sizes
            art = self._cas(c, body)
            op["observations"].append(art)
            if disposition == "conflict":
                op["conflicts"].append(art)
                op["conflict_count"] += 1
                op["reconciliation_required"] = True
            elif disposition != "retain_confirmed":
                op["provider_outcome"] = body["outcome"]
                op["reconciliation_required"] = not body["outcome"].startswith(
                    "confirmed_"
                ) or bool(op["conflicts"])
            if body["provider_operation_id"] is not None:
                op["provider_operation_id"] = body["provider_operation_id"]
                op["submission_evidence"] = "provider_accepted"
            receipt = self._snapshot(c, op)
            response = {
                "schema_version": "pdx_er003_observation_response_draft_v2",
                **{
                    k: body[k]
                    for k in (
                        "authority_id",
                        "tenant_id",
                        "request_id",
                        "operation_id",
                        "observation_id",
                    )
                },
                "accepted": True,
                "conflict_recorded": disposition == "conflict",
                "receipt_artifact": receipt,
                "sequence": op["sequence"],
            }
            v.supporting("observation_response", response)
            binding = v.digest(
                {
                    **{k: x for k, x in body.items() if k != "request_id"},
                    "authenticated_principal": principal.name,
                }
            )
            c.execute(
                "INSERT INTO external_observations VALUES (?,?,?,?)",
                (op["operation_id"], body["observation_id"], binding, _json(response)),
            )
            self._advance_parent(c, op)
            return response

    def reconcile(self, body, principal):
        v.shape("urn:pdx:draft:er003:support:2#/$defs/reconcile_request", body)
        self._auth(body, principal, "supervisor")
        with self.store.transaction() as c:
            binding, existing = self._idempotency(
                c, self._ns(body), "reconcile_request", body, principal
            )
            op = self._operation(c, body["operation_id"], principal, "supervisor")
            if existing:
                return self._reconcile_response(
                    body, op, False, op["recovery_mode"] == "manual_only"
                )
            elapsed = min(86400, max(0, int(self.clock() - op["created_at"])))
            context = self._auth(body, principal, "supervisor")
            context.update(
                operation=op,
                sequence=op["sequence"],
                recovery_mode=op["recovery_mode"],
                query_calls=op["consumed"]["query_calls"],
                query_execution_ms=op["consumed"]["query_execution_ms"],
                scheduling_elapsed_seconds=elapsed,
            )
            v.supporting("reconcile_request", body, context)
            if (
                op["provider_outcome"].startswith("confirmed_")
                and not op["reconciliation_required"]
            ):
                return self._reconcile_response(body, op, False, False)
            v.require(op["submit_permits"] == 1, "STALE_EXECUTION_CLAIM")
            if op["recovery_mode"] == "manual_only":
                self._record_idempotency(
                    c,
                    self._ns(body),
                    "reconcile_request",
                    body,
                    binding,
                    op["operation_id"],
                )
                return self._reconcile_response(body, op, False, True)
            adapter = self.adapters.get(op["provider_profile"]["provider_profile_id"])
            v.require(
                adapter is not None
                and adapter.query is not None
                and adapter.query_deployment
                == op["provider_profile"]["query_deployment"],
                "PROVIDER_PROFILE_UNSUPPORTED",
            )
            v.require(
                op["consumed"]["observation_records"] < 64
                and op["consumed"]["evidence_bytes"] < 1048576,
                "RECOVERY_BUDGET_EXHAUSTED",
            )
            old = op["query_claim"]
            v.require(
                old is None or self.clock() >= v.timestamp(old["deadline"]).timestamp(),
                "STALE_EXECUTION_CLAIM",
            )
            workflow = c.execute(
                "SELECT * FROM runtime_workflows WHERE workflow_job_id=?",
                (op["workflow_job_id"],),
            ).fetchone()
            counters = json.loads(workflow["counters_json"])
            budgets = json.loads(workflow["plan_json"])["budgets"]
            v.require(
                counters["external_calls"] < budgets["max_external_calls"],
                "RECOVERY_BUDGET_EXHAUSTED",
            )
            counters["external_calls"] += 1
            counters["recovery_query_calls"] += 1
            c.execute(
                "UPDATE runtime_workflows SET counters_json=? WHERE workflow_job_id=?",
                (_json(counters), op["workflow_job_id"]),
            )
            reserve = min(
                30000,
                adapter.query_timeout_seconds * 1000,
                600000 - op["consumed"]["query_execution_ms"],
            )
            v.require(reserve > 0, "RECOVERY_BUDGET_EXHAUSTED")
            op["consumed"]["query_calls"] += 1
            # Reserve the whole call allowance so a killed worker cannot reset it.
            op["consumed"]["query_execution_ms"] += reserve
            op["consumed"]["scheduling_elapsed_seconds"] = elapsed
            op["claim_fence"] += 1
            claim = {
                k: op[k]
                for k in (
                    "authority_id",
                    "tenant_id",
                    "operation_subject_id",
                    "operation_id",
                    "operation_digest",
                    "workflow_job_id",
                    "workflow_step_id",
                    "plan_digest",
                    "authorization_id",
                    "issuer_id",
                    "provider_profile_digest",
                    "provider_key_digest",
                    "account_alias",
                    "environment",
                )
            }
            claim.update(
                schema_version="pdx_er003_query_claim_record_draft_v2",
                query_id=_id("query"),
                claim_id=_id("claim"),
                claim_fence=op["claim_fence"],
                deadline=_iso(self.clock() + reserve / 1000),
                reserved_runtime_ms=reserve,
                query_number=op["consumed"]["query_calls"],
            )
            v.supporting("query_claim_record", claim)
            op["query_claim"] = claim
            self._snapshot(c, op)
            self._record_idempotency(
                c,
                self._ns(body),
                "reconcile_request",
                body,
                binding,
                op["operation_id"],
            )
        # Read-only query; a timeout never permits resubmission. A late response is fenced.
        import queue
        import threading

        results = queue.Queue(maxsize=1)

        def query():
            try:
                results.put(adapter.query(op["provider_profile"], op["provider_key"]))
            except Exception:  # noqa: BLE001 - registered adapter boundary
                results.put(None)

        thread = threading.Thread(target=query, daemon=True)
        thread.start()
        try:
            observation = results.get(timeout=reserve / 1000)
        except queue.Empty:
            observation = None
        if observation is not None:
            # Adapter identity is deployment-owned; the response must still carry
            # independently verified, full evidence and match the stored operation.
            adapter_name = (
                adapter.principal.name if adapter.principal is not None else None
            )
            config = next(
                x
                for x in self.authorities
                if x["authority_id"] == op["authority_id"]
                and x["tenant_id"] == op["tenant_id"]
            )
            v.require(
                len(config["adapter_principals"]) == 1
                or adapter_name in config["adapter_principals"],
                "AUTHORITY_FORBIDDEN",
            )
            name = adapter_name or config["adapter_principals"][0]
            self.observe(
                observation,
                adapter.principal or Principal(name, "registered-query-worker"),
                query_claim=claim,
            )
        with self.store.transaction() as c:
            current = self._operation(c, op["operation_id"], principal, "supervisor")
            if (
                current["query_claim"]
                and current["query_claim"]["claim_id"] == claim["claim_id"]
            ):
                current["query_claim"] = None
                self._save(c, current)
            return self._reconcile_response(body, current, True, False)

    def _reconcile_response(self, body, op, scheduled, manual):
        result = {
            "schema_version": "pdx_er003_reconcile_response_draft_v2",
            **{
                k: body[k]
                for k in ("authority_id", "tenant_id", "request_id", "operation_id")
            },
            "query_scheduled": scheduled,
            "manual_required": manual,
            "projection": self._projection(op),
        }
        v.supporting("reconcile_response", result)
        return result

    def attach_parent_terminal(self, c, workflow_id, artifact):
        """Called once by the workflow terminal transaction after freezing bytes."""
        for row in c.execute(
            "SELECT body FROM external_operations WHERE workflow_job_id=?",
            (workflow_id,),
        ).fetchall():
            op = json.loads(row[0])
            if op["parent_terminal_receipt_artifact"] is not None:
                v.require(
                    op["parent_terminal_receipt_artifact"] == artifact,
                    "OPERATION_BINDING_MISMATCH",
                )
                continue
            op["parent_terminal_receipt_artifact"] = artifact
            self._snapshot(c, op)

    def parent_completion_ready(self, c, workflow_id):
        """Read current operation authority inside the terminal transaction."""
        plan = json.loads(
            c.execute(
                "SELECT plan_json FROM runtime_workflows WHERE workflow_job_id=?",
                (workflow_id,),
            ).fetchone()[0]
        )
        for step in plan["steps"]:
            if "external_operation_binding" not in step:
                continue
            row = c.execute(
                "SELECT body FROM external_operations WHERE workflow_job_id=? AND workflow_step_id=?",
                (workflow_id, step["workflow_step_id"]),
            ).fetchone()
            if row is None:
                return False
            op = json.loads(row[0])
            if (
                op["provider_outcome"] != "confirmed_succeeded"
                or op["reconciliation_required"]
                or op["conflict_count"]
            ):
                return False
        return True

    def validate_parent_receipt(self, c, receipt, plan):
        """Validate against immutable CAS bytes, never receipt assertions alone."""
        context = {
            "authorized_artifact_bytes": {},
            "authorized_artifact_identities": {},
        }

        def visit(value):
            if isinstance(value, dict):
                if value.get("schema_version") == "prodocux_opaque_artifact_v1":
                    row = c.execute(
                        "SELECT content,media_type FROM dynamic_dispatch_cas WHERE sha256=?",
                        (value["sha256"],),
                    ).fetchone()
                    if row is not None:
                        raw = bytes(row["content"])
                        identity = self.dispatch._cas_put(c, raw, row["media_type"])
                        v.require(identity == value, "EVIDENCE_INVALID")
                        context["authorized_artifact_bytes"][value["artifact_id"]] = raw
                        context["authorized_artifact_identities"][
                            value["artifact_id"]
                        ] = identity
                    else:
                        trusted = self._artifacts(value)
                        for key, values in context.items():
                            values.update(trusted[key])
                else:
                    for item in value.values():
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(receipt)
        v.parent_receipt(receipt, plan, context)

    def parent_step_receipts(self, c, workflow_id):
        rows = []
        for row in c.execute(
            "SELECT body FROM external_operations WHERE workflow_job_id=?",
            (workflow_id,),
        ).fetchall():
            op = json.loads(row[0])
            success = (
                op["provider_outcome"] == "confirmed_succeeded"
                and not op["reconciliation_required"]
            )
            attempt = c.execute(
                "SELECT attempt_count FROM runtime_workflow_steps WHERE workflow_job_id=? AND workflow_step_id=?",
                (workflow_id, op["workflow_step_id"]),
            ).fetchone()[0]
            result = {
                "workflow_step_id": op["workflow_step_id"],
                "step_kind": "dispatch",
                "attempt_number": attempt,
                "execution_constraints_digest": op["provider_profile"][
                    "execution_policy_digest"
                ],
                "status": "succeeded" if success else "failed",
                "receipt_profile": "external_operation",
                "operation_allocated": True,
                "external_operation_receipt_artifact": op["latest_receipt_artifact"],
            }
            if not success:
                result["safe_error"] = {
                    "code": "EXTERNAL_OUTCOME_UNRESOLVED",
                    "message": "provider outcome is not confirmed successful",
                    "retryable": False,
                    "reconcile_required": op["reconciliation_required"],
                }
            rows.append(result)
        plan = json.loads(
            c.execute(
                "SELECT plan_json FROM runtime_workflows WHERE workflow_job_id=?",
                (workflow_id,),
            ).fetchone()[0]
        )
        seen = {row["workflow_step_id"] for row in rows}
        for step in plan["steps"]:
            if (
                step["workflow_step_id"] in seen
                or "external_operation_binding" not in step
            ):
                continue
            binding = step["external_operation_binding"]
            subject = self._get(
                c,
                self._ns(binding),
                "subject_register",
                binding["operation_subject_id"],
            )
            rows.append(
                {
                    "workflow_step_id": step["workflow_step_id"],
                    "step_kind": "dispatch",
                    "attempt_number": 1,
                    "execution_constraints_digest": subject["specification"][
                        "execution_policy_digest"
                    ],
                    "status": "cancelled",
                    "receipt_profile": "external_operation",
                    "operation_allocated": False,
                    "safe_error": {
                        "code": "PARENT_NOT_READY",
                        "message": "operation was not allocated before parent terminalization",
                        "retryable": False,
                        "reconcile_required": False,
                    },
                }
            )
        return rows

    def _advance_parent(self, c, op):
        workflow = c.execute(
            "SELECT * FROM runtime_workflows WHERE workflow_job_id=?",
            (op["workflow_job_id"],),
        ).fetchone()
        if (
            workflow["state"] not in ("pending", "running")
            or not op["provider_outcome"].startswith("confirmed_")
            or op["reconciliation_required"]
        ):
            return
        status = (
            "succeeded" if op["provider_outcome"] == "confirmed_succeeded" else "failed"
        )
        old = c.execute(
            "SELECT state FROM runtime_workflow_steps WHERE workflow_job_id=? AND workflow_step_id=?",
            (op["workflow_job_id"], op["workflow_step_id"]),
        ).fetchone()[0]
        if old == "running":
            counters = json.loads(workflow["counters_json"])
            counters["active_steps"] -= 1
            counters["active_dispatches"] -= 1
            c.execute(
                "UPDATE runtime_workflow_steps SET state=? WHERE workflow_job_id=? AND workflow_step_id=?",
                (status, op["workflow_job_id"], op["workflow_step_id"]),
            )
            c.execute(
                "UPDATE runtime_workflows SET counters_json=? WHERE workflow_job_id=?",
                (_json(counters), op["workflow_job_id"]),
            )
        remaining = c.execute(
            "SELECT 1 FROM runtime_workflow_steps WHERE workflow_job_id=? AND state!='succeeded'",
            (op["workflow_job_id"],),
        ).fetchone()
        if status == "failed" or not remaining:
            error = (
                None
                if status == "succeeded"
                else _json(
                    {
                        "schema_version": "pdx_runtime_provider_workflow_error_v3",
                        "code": "EXTERNAL_OUTCOME_UNRESOLVED",
                        "message": "provider did not confirm success",
                        "retryable": False,
                        "reconcile_required": False,
                    }
                )
            )
            c.execute(
                "UPDATE runtime_workflows SET state=?,terminal_error_json=?,updated_at=? WHERE workflow_job_id=?",
                (
                    "completed" if status == "succeeded" else "failed",
                    error,
                    _iso(self.clock()),
                    op["workflow_job_id"],
                ),
            )
            # Reuse the existing terminal receipt transaction, not another workflow.
            service = RuntimeWorkflowService.__new__(RuntimeWorkflowService)
            service.store = self.store
            service._freeze_receipt(c, op["workflow_job_id"], int(self.clock()))
