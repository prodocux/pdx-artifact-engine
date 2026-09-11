"""Transactional service for the frozen runtime-provider workflow contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import validate
from .semantics import validate_plan
from .store import RuntimeWorkflowStore

ACTIVE_STATES = frozenset({"pending", "running"})
TERMINAL_STATES = frozenset(
    {"completed", "completed_with_review", "failed", "blocked", "cancelled", "timed_out"}
)
COUNTER_NAMES = (
    "provider_attempts", "check_attempts", "active_steps", "repair_iterations",
    "total_runtime_seconds", "total_event_bytes", "total_artifact_bytes",
    "cross_step_artifact_edges", "external_operations",
)


class RuntimeWorkflowError(Exception):
    def __init__(self, code: str, message: str, status: int, *, retryable: bool = False, commit_transaction: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.commit_transaction = commit_transaction

    def as_document(self) -> dict[str, Any]:
        return {
            "schema_version": "pdx_runtime_provider_workflow_error_v1",
            "code": self.code,
            "message": self.message[:1024],
            "retryable": self.retryable,
            "reconcile_required": self.code in {"CLAIM_STALE", "LEASE_EXPIRED"},
        }


def _now_iso(now: int | None = None) -> str:
    value = int(time.time() if now is None else now)
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _binding(request: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "request": {
            key: value for key, value in request.items()
            if key not in {"schema_version", "request_id"}
        },
    }


@dataclass
class RuntimeWorkflowService:
    store: RuntimeWorkflowStore
    hmac_secret: bytes | None = None
    hmac_keys: dict[str, bytes] | None = None
    active_hmac_key_id: str = "default"

    def __post_init__(self) -> None:
        keys = dict(self.hmac_keys or {})
        if self.hmac_secret is not None:
            keys.setdefault("default", self.hmac_secret)
        if self.active_hmac_key_id not in keys:
            raise ValueError("active PDX workflow HMAC key is unavailable")
        if any(len(secret) < 32 for secret in keys.values()):
            raise ValueError("PDX workflow HMAC secrets must contain at least 32 bytes")
        self.hmac_keys = keys

    def readiness(self) -> dict[str, Any]:
        with self.store.transaction() as connection:
            required = {
                row[0] for row in connection.execute(
                    "SELECT DISTINCT hmac_key_id FROM runtime_workflow_claims WHERE status = 'active'"
                ).fetchall()
            }
        missing = sorted(required - set(self.hmac_keys or {}))
        return {"ready": not missing, "active_hmac_key_id": self.active_hmac_key_id,
                "missing_active_claim_key_ids": missing}

    def _validate(self, schema: str, body: dict[str, Any]) -> None:
        try:
            validate(schema, body)
        except ValueError as exc:
            raise RuntimeWorkflowError("PAYLOAD_DIGEST_INVALID", str(exc), 400) from exc

    def _workflow(self, connection: Any, workflow_job_id: str) -> Any:
        row = connection.execute(
            "SELECT * FROM runtime_workflows WHERE workflow_job_id = ?", (workflow_job_id,)
        ).fetchone()
        if row is None:
            raise RuntimeWorkflowError("WORKFLOW_NOT_ACTIVE", "workflow not found", 404)
        return row

    def _state(self, row: Any) -> dict[str, Any]:
        result = {
            "schema_version": "pdx_runtime_provider_workflow_state_v1",
            "workflow_job_id": row["workflow_job_id"], "task_id": row["task_id"],
            "run_id": row["run_id"], "plan_digest": row["plan_digest"],
            "state": row["state"], "counters": json.loads(row["counters_json"]),
            "updated_at": row["updated_at"],
        }
        if row["terminal_error_json"]:
            result["terminal_error"] = json.loads(row["terminal_error_json"])
        return result

    def _budget_exhausted(
        self, connection: Any, workflow: Any, counters: dict[str, int],
        message: str, now_unix: int,
    ) -> None:
        error = {
            "schema_version": "pdx_runtime_provider_workflow_error_v1",
            "code": "WORKFLOW_BUDGET_EXHAUSTED", "message": message,
            "retryable": False, "reconcile_required": False,
        }
        now = _now_iso(now_unix)
        connection.execute(
            "UPDATE runtime_workflow_claims SET status = 'stale_rejected', updated_at = ? WHERE workflow_job_id = ? AND status = 'active'",
            (now, workflow["workflow_job_id"]),
        )
        counters["active_steps"] = 0
        connection.execute(
            "UPDATE runtime_workflows SET state = 'failed', counters_json = ?, terminal_error_json = ?, updated_at = ? WHERE workflow_job_id = ?",
            (_dump(counters), _dump(error), now, workflow["workflow_job_id"]),
        )
        self._freeze_receipt(connection, workflow["workflow_job_id"], now_unix)
        raise RuntimeWorkflowError(
            "WORKFLOW_BUDGET_EXHAUSTED", message, 409,
            commit_transaction=True,
        )

    def create(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self._validate("pdx_runtime_provider_workflow_create_request_v1.schema.json", body)
        plan = body["plan"]
        semantic_errors = validate_plan(
            plan, _digest({key: value for key, value in plan.items() if key != "plan_digest"})
        )
        if semantic_errors:
            raise RuntimeWorkflowError(
                "PAYLOAD_DIGEST_INVALID", ", ".join(semantic_errors), 400
            )
        now = _now_iso()
        counters = {name: 0 for name in COUNTER_NAMES}
        with self.store.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM runtime_workflows WHERE idempotency_key = ?",
                (body["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                if existing["operation_digest"] != body["operation_digest"] or existing["plan_digest"] != plan["plan_digest"]:
                    raise RuntimeWorkflowError("IDEMPOTENCY_CONFLICT", "create binding differs", 409)
                return 200, self._create_response(existing, body)
            connection.execute(
                """INSERT INTO runtime_workflows VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, ?, ?)""",
                (plan["workflow_job_id"], body["idempotency_key"], body["operation_digest"],
                 plan["plan_digest"], _dump(plan), plan["task_id"], plan["run_id"],
                 _dump(counters), now, now),
            )
            for step in plan["steps"]:
                connection.execute(
                    "INSERT INTO runtime_workflow_steps VALUES (?, ?, ?, 'pending', 0)",
                    (plan["workflow_job_id"], step["workflow_step_id"], step["step_kind"]),
                )
            row = self._workflow(connection, plan["workflow_job_id"])
            return 202, self._create_response(row, body)

    def _create_response(self, row: Any, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "pdx_internal_runtime_provider_workflow_create_response_v1",
            "request_id": body["request_id"], "correlation_id": body["correlation_id"],
            "workflow_job_id": row["workflow_job_id"], "task_id": row["task_id"],
            "run_id": row["run_id"], "plan_digest": row["plan_digest"], "state": "pending",
        }

    def get_state(self, workflow_job_id: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            return self._state(self._workflow(connection, workflow_job_id))

    def get_plan(self, workflow_job_id: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            return json.loads(self._workflow(connection, workflow_job_id)["plan_json"])

    def get_step_projection(
        self, workflow_job_id: str, *, authenticated_instance_id: str
    ) -> dict[str, Any]:
        """Return a bounded, non-authorizing projection for safe host recovery."""
        if not authenticated_instance_id:
            raise RuntimeWorkflowError(
                "ACTIVATION_AUTH_FORBIDDEN",
                "registered control-plane identity required",
                403,
            )
        with self.store.read_transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            plan = json.loads(workflow["plan_json"])
            rows = connection.execute(
                """SELECT * FROM runtime_workflow_claims
                   WHERE workflow_job_id = ?
                   ORDER BY workflow_step_id, attempt_number""",
                (workflow_job_id,),
            ).fetchall()
            latest_claims = {row["workflow_step_id"]: row for row in rows}
            step_rows = {
                row["workflow_step_id"]: row
                for row in connection.execute(
                    """SELECT * FROM runtime_workflow_steps
                       WHERE workflow_job_id = ?""",
                    (workflow_job_id,),
                ).fetchall()
            }
            steps: list[dict[str, Any]] = []
            for planned_step in plan["steps"]:
                step_id = planned_step["workflow_step_id"]
                step_row = step_rows.get(step_id)
                if step_row is None:
                    raise RuntimeWorkflowError(
                        "PAYLOAD_DIGEST_INVALID",
                        "durable workflow step is missing",
                        500,
                    )
                claim = latest_claims.get(step_id)
                item: dict[str, Any] = {
                    "workflow_step_id": step_id,
                    "step_kind": step_row["step_kind"],
                    "state": step_row["state"],
                    "latest_attempt_number": (
                        claim["attempt_number"] if claim is not None else None
                    ),
                    "active_claim": bool(
                        claim is not None and claim["status"] == "active"
                    ),
                    "terminal_record_identity": None,
                }
                if claim is not None and claim["terminal_record_json"] is not None:
                    terminal = connection.execute(
                        """SELECT record_id, payload_digest, record_json
                           FROM runtime_workflow_records
                           WHERE claim_id = ? ORDER BY sequence DESC LIMIT 1""",
                        (claim["claim_id"],),
                    ).fetchone()
                    if terminal is None:
                        raise RuntimeWorkflowError(
                            "PAYLOAD_DIGEST_INVALID",
                            "terminal record identity is unavailable",
                            500,
                        )
                    record = json.loads(terminal["record_json"])
                    if record.get("record_kind") != "outcome":
                        raise RuntimeWorkflowError(
                            "PAYLOAD_DIGEST_INVALID",
                            "terminal record is not an outcome",
                            500,
                        )
                    item["terminal_record_identity"] = {
                        "record_id": terminal["record_id"],
                        "record_schema_id": record["schema_version"],
                        "payload_digest": terminal["payload_digest"],
                    }
                steps.append(item)
            result = {
                "schema_version": "pdx_runtime_provider_step_projection_v1",
                "workflow_job_id": workflow_job_id,
                "plan_digest": workflow["plan_digest"],
                "workflow_state": workflow["state"],
                "recorded_at": _now_iso(),
                "steps": steps,
            }
            self._validate(
                "pdx_runtime_provider_step_projection_v1.schema.json", result
            )
            return result

    def _token(self, claim_id: str, attempt: int, binding: dict[str, Any], key_id: str) -> str:
        message = _dump({"claim_id": claim_id, "attempt_number": attempt, "binding": binding}).encode()
        return hmac.new(self.hmac_keys[key_id], message, hashlib.sha256).hexdigest()

    def _meter_runtime(
        self, connection: Any, workflow: Any, claim: Any,
        counters: dict[str, int], now_unix: int,
    ) -> None:
        elapsed = max(0, now_unix - claim["started_unix"])
        delta = max(0, elapsed - claim["runtime_accounted_seconds"])
        if not delta:
            return
        plan = json.loads(workflow["plan_json"])
        if counters["total_runtime_seconds"] + delta > plan["budgets"]["max_total_runtime_seconds"]:
            self._budget_exhausted(
                connection, workflow, counters, "runtime budget exhausted", now_unix
            )
        counters["total_runtime_seconds"] += delta
        connection.execute(
            "UPDATE runtime_workflow_claims SET runtime_accounted_seconds = ? WHERE claim_id = ? AND status = 'active'",
            (elapsed, claim["claim_id"]),
        )

    def activate_provider(self, workflow_job_id: str, body: dict[str, Any], *, authenticated_instance_id: str) -> dict[str, Any]:
        self._validate("pdx_runtime_provider_claim_request_v2.schema.json", body)
        return self._activate(workflow_job_id, body, "provider", authenticated_instance_id)

    def activate_check(self, workflow_job_id: str, body: dict[str, Any], *, authenticated_instance_id: str) -> dict[str, Any]:
        self._validate("pdx_runtime_check_claim_request_v2.schema.json", body)
        return self._activate(workflow_job_id, body, "check", authenticated_instance_id)

    def _activate(self, workflow_job_id: str, body: dict[str, Any], kind: str, authenticated_instance_id: str) -> dict[str, Any]:
        if not authenticated_instance_id:
            raise RuntimeWorkflowError("ACTIVATION_AUTH_REQUIRED", "authenticated control plane required", 401)
        if body["control_plane_instance_id"] != authenticated_instance_id:
            raise RuntimeWorkflowError("ACTIVATION_PRINCIPAL_MISMATCH", "control-plane instance mismatch", 403)
        binding = _binding(body, kind)
        now_unix = int(time.time())
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            if workflow["state"] not in ACTIVE_STATES:
                raise RuntimeWorkflowError("WORKFLOW_NOT_ACTIVE", "workflow is terminal", 410)
            existing = connection.execute(
                """SELECT * FROM runtime_workflow_claims
                   WHERE workflow_job_id = ? AND step_kind = ? AND activation_idempotency_key = ?""",
                (workflow_job_id, "check" if kind == "check" else body.get("step_kind", "provider"), body["idempotency_key"]),
            ).fetchone()
            if existing is None:
                existing = connection.execute(
                    "SELECT * FROM runtime_workflow_claims WHERE workflow_job_id = ? AND activation_idempotency_key = ?",
                    (workflow_job_id, body["idempotency_key"]),
                ).fetchone()
            if existing is not None:
                if json.loads(existing["binding_json"]) != binding:
                    raise RuntimeWorkflowError("ACTIVATION_BINDING_CONFLICT", "activation binding differs", 409)
                return self._claim_document(workflow, existing, binding)
            if kind == "provider":
                invocation = connection.execute(
                    "SELECT * FROM runtime_workflow_claims WHERE workflow_job_id = ? AND invocation_id = ?",
                    (workflow_job_id, body["invocation_id"]),
                ).fetchone()
                if invocation is not None:
                    raise RuntimeWorkflowError(
                        "ACTIVATION_BINDING_CONFLICT",
                        "invocation ID is already bound to another activation",
                        409,
                    )
            plan = json.loads(workflow["plan_json"])
            step = next((item for item in plan["steps"] if item["workflow_step_id"] == body["workflow_step_id"]), None)
            if step is None:
                raise RuntimeWorkflowError("STEP_NOT_READY", "step does not exist", 409)
            expected_check = step["step_kind"] == "check"
            if expected_check != (kind == "check"):
                raise RuntimeWorkflowError("STEP_KIND_MISMATCH", "step kind does not match activation route", 409)
            step_row = connection.execute(
                "SELECT * FROM runtime_workflow_steps WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (workflow_job_id, body["workflow_step_id"]),
            ).fetchone()
            dependencies = step.get("depends_on", [])
            ready = step_row["state"] == "pending"
            if dependencies:
                placeholders = ",".join("?" for _ in dependencies)
                rows = connection.execute(
                    f"SELECT workflow_step_id, state FROM runtime_workflow_steps WHERE workflow_job_id = ? AND workflow_step_id IN ({placeholders})",
                    (workflow_job_id, *dependencies),
                ).fetchall()
                ready = ready and len(rows) == len(dependencies) and all(row["state"] == "succeeded" for row in rows)
            if not ready:
                raise RuntimeWorkflowError("STEP_NOT_READY", "step dependencies are not satisfied", 409)
            active = connection.execute(
                "SELECT COUNT(*) FROM runtime_workflow_claims WHERE workflow_job_id = ? AND status = 'active'",
                (workflow_job_id,),
            ).fetchone()[0]
            counters = json.loads(workflow["counters_json"])
            budget = plan["budgets"]
            counter = "check_attempts" if kind == "check" else "provider_attempts"
            maximum = budget["max_check_attempts" if kind == "check" else "max_provider_attempts"]
            if counters[counter] >= maximum or active >= budget["max_concurrent_steps"] or step_row["attempt_count"] >= step["max_attempts"]:
                self._budget_exhausted(
                    connection, workflow, counters, "attempt budget exhausted", now_unix
                )
            attempt = step_row["attempt_count"] + 1
            claim_id = f"claim_{uuid.uuid4().hex}"
            token = self._token(claim_id, attempt, binding, self.active_hmac_key_id)
            expires = now_unix + body["lease_seconds"]
            now = _now_iso(now_unix)
            step_kind = step["step_kind"]
            connection.execute(
                """INSERT INTO runtime_workflow_claims(
                    claim_id, workflow_job_id, workflow_step_id, step_kind, attempt_number,
                    activation_idempotency_key, binding_json, invocation_id, provider_id,
                    provider_instance_id, execution_constraints_digest, workspace_ref,
                    operation_digest, check_definition_digest, hmac_key_id, lease_token_digest,
                    started_unix, runtime_accounted_seconds, lease_expires_unix,
                    status, next_sequence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'active', 0, ?, ?)""",
                (claim_id, workflow_job_id, body["workflow_step_id"], step_kind, attempt,
                 body["idempotency_key"], _dump(binding), body.get("invocation_id"),
                 body.get("provider_id"), body.get("provider_instance_id"),
                 body["execution_constraints_digest"], body["workspace_ref"],
                 step.get("operation_digest"), step.get("check_definition_digest"), self.active_hmac_key_id,
                 hashlib.sha256(token.encode()).hexdigest(), now_unix, expires, now, now),
            )
            counters[counter] += 1
            counters["active_steps"] += 1
            if step_kind == "repair":
                counters["repair_iterations"] += 1
            connection.execute(
                "UPDATE runtime_workflow_steps SET state = 'running', attempt_count = ? WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (attempt, workflow_job_id, body["workflow_step_id"]),
            )
            connection.execute(
                "UPDATE runtime_workflows SET state = 'running', counters_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                (_dump(counters), now, workflow_job_id),
            )
            claim = connection.execute("SELECT * FROM runtime_workflow_claims WHERE claim_id = ?", (claim_id,)).fetchone()
            return self._claim_document(workflow, claim, binding)

    def _claim_document(self, workflow: Any, claim: Any, binding: dict[str, Any]) -> dict[str, Any]:
        request = binding["request"]
        key_id = claim["hmac_key_id"]
        if key_id not in self.hmac_keys:
            raise RuntimeWorkflowError("ACTIVATION_AUTH_FORBIDDEN", "claim HMAC key is unavailable", 503)
        token = self._token(claim["claim_id"], claim["attempt_number"], binding, key_id)
        result = {
            "schema_version": "pdx_internal_runtime_check_claim_v1" if claim["step_kind"] == "check" else "pdx_internal_runtime_provider_claim_v1",
            "workflow_job_id": workflow["workflow_job_id"], "workflow_step_id": claim["workflow_step_id"],
            "step_kind": claim["step_kind"], "task_id": workflow["task_id"], "run_id": workflow["run_id"],
            "claim_id": claim["claim_id"], "lease_token": token,
            "lease_expires_at": _now_iso(claim["lease_expires_unix"]),
            "attempt_number": claim["attempt_number"],
            "execution_constraints_digest": request["execution_constraints_digest"],
            "idempotency_key": request["idempotency_key"], "workspace_ref": request["workspace_ref"],
        }
        if claim["step_kind"] == "check":
            result["check_definition_digest"] = claim["check_definition_digest"]
        else:
            result.update({"invocation_id": request["invocation_id"], "provider_id": request["provider_id"],
                           "provider_instance_id": request["provider_instance_id"], "operation_digest": claim["operation_digest"]})
        return result

    def renew(self, workflow_job_id: str, body: dict[str, Any], kind: str, *, now: int | None = None) -> dict[str, Any]:
        schema = "pdx_runtime_check_lease_renew_v1.schema.json" if kind == "check" else "pdx_runtime_provider_lease_renew_v1.schema.json"
        self._validate(schema, body)
        now_unix = int(time.time() if now is None else now)
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            claim = self._checked_claim(connection, workflow, body, kind, now_unix)
            counters = json.loads(workflow["counters_json"])
            self._meter_runtime(connection, workflow, claim, counters, now_unix)
            expires = now_unix + body["lease_seconds"]
            connection.execute(
                "UPDATE runtime_workflow_claims SET lease_expires_unix = ?, updated_at = ? WHERE claim_id = ? AND status = 'active'",
                (expires, _now_iso(now_unix), claim["claim_id"]),
            )
            connection.execute(
                "UPDATE runtime_workflows SET counters_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                (_dump(counters), _now_iso(now_unix), workflow_job_id),
            )
            return {"schema_version": "pdx_internal_runtime_lease_renew_response_v1",
                    "workflow_job_id": workflow_job_id, "workflow_step_id": claim["workflow_step_id"],
                    "claim_id": claim["claim_id"], "attempt_number": claim["attempt_number"],
                    "lease_expires_at": _now_iso(expires)}

    def _checked_claim(self, connection: Any, workflow: Any, body: dict[str, Any], kind: str, now_unix: int) -> Any:
        if workflow["state"] not in ACTIVE_STATES:
            raise RuntimeWorkflowError("POST_TERMINAL_ACTIVITY_REJECTED", "workflow is terminal", 410)
        claim = connection.execute("SELECT * FROM runtime_workflow_claims WHERE claim_id = ?", (body["claim_id"],)).fetchone()
        if claim is None or claim["workflow_job_id"] != workflow["workflow_job_id"] or claim["status"] != "active":
            raise RuntimeWorkflowError("CLAIM_STALE", "claim is not active", 409)
        if (claim["step_kind"] == "check") != (kind == "check"):
            raise RuntimeWorkflowError("CLAIM_STALE", "claim kind mismatch", 409)
        digest = hashlib.sha256(body["lease_token"].encode()).hexdigest()
        if not hmac.compare_digest(digest, claim["lease_token_digest"]):
            raise RuntimeWorkflowError("CLAIM_STALE", "lease token rejected", 409)
        if claim["lease_expires_unix"] < now_unix:
            raise RuntimeWorkflowError("LEASE_EXPIRED", "lease expired", 410, retryable=True)
        fields = ("workflow_step_id", "attempt_number", "execution_constraints_digest")
        if any(body.get(field) != claim[field] for field in fields):
            raise RuntimeWorkflowError("CLAIM_STALE", "claim binding mismatch", 409)
        if kind == "check":
            if body.get("check_definition_digest") != claim["check_definition_digest"]:
                raise RuntimeWorkflowError("CLAIM_STALE", "check digest mismatch", 409)
        elif body.get("invocation_id") != claim["invocation_id"] or body.get("operation_digest") != claim["operation_digest"]:
            raise RuntimeWorkflowError("CLAIM_STALE", "provider binding mismatch", 409)
        if "idempotency_key" in body and body["idempotency_key"] != claim["activation_idempotency_key"]:
            raise RuntimeWorkflowError("CLAIM_STALE", "idempotency binding mismatch", 409)
        return claim

    def update(self, workflow_job_id: str, body: dict[str, Any], kind: str, *, now: int | None = None) -> dict[str, Any]:
        if kind == "check" and body.get("schema_version") == "pdx_internal_runtime_check_update_v2":
            schema = "pdx_runtime_check_update_v2.schema.json"
        else:
            schema = "pdx_runtime_check_update_v1.schema.json" if kind == "check" else "pdx_runtime_provider_update_v1.schema.json"
        self._validate(schema, body)
        now_unix = int(time.time() if now is None else now)
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            claim = self._checked_claim(connection, workflow, body, kind, now_unix)
            record = body["record"]
            counters = json.loads(workflow["counters_json"])
            self._meter_runtime(connection, workflow, claim, counters, now_unix)
            if _digest(record["payload"]) != record["payload_digest"]:
                raise RuntimeWorkflowError("PAYLOAD_DIGEST_INVALID", "payload digest mismatch", 409)
            if "conformance_binding" in body:
                self._validate_conformance_binding(claim, body)
            prior = connection.execute(
                "SELECT * FROM runtime_workflow_records WHERE claim_id = ? AND record_id = ?",
                (claim["claim_id"], record["record_id"]),
            ).fetchone()
            if prior is not None:
                if prior["record_json"] != _dump(record):
                    raise RuntimeWorkflowError("SEQUENCE_CONFLICT", "record replay differs", 409)
                connection.execute(
                    "UPDATE runtime_workflows SET counters_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                    (_dump(counters), _now_iso(now_unix), workflow_job_id),
                )
                return self._state(self._workflow(connection, workflow_job_id))
            if record["sequence"] != claim["next_sequence"]:
                raise RuntimeWorkflowError("SEQUENCE_CONFLICT", "sequence is not contiguous", 409)
            plan = json.loads(workflow["plan_json"])
            record_bytes = len(_dump(record["payload"]).encode())
            if record["record_kind"] == "event":
                if counters["total_event_bytes"] + record_bytes > plan["budgets"]["max_total_event_bytes"]:
                    self._budget_exhausted(
                        connection, workflow, counters, "event byte budget exhausted", now_unix
                    )
                counters["total_event_bytes"] += record_bytes
                if kind == "provider" and record["payload"].get("event_kind") == "tool_summary":
                    if counters["external_operations"] >= plan["budgets"]["max_external_operations"]:
                        self._budget_exhausted(
                            connection, workflow, counters,
                            "external operation budget exhausted", now_unix,
                        )
                    counters["external_operations"] += 1
            if kind == "check" and record["record_kind"] == "outcome" and (
                record["payload"]["terminal_outcome"] == "succeeded"
                or "conformance_binding" in body
            ):
                self._preflight_check_artifact(
                    connection, workflow, claim, body, counters, now_unix
                )
            connection.execute(
                "INSERT INTO runtime_workflow_records VALUES (?, ?, ?, ?, ?, ?)",
                (claim["claim_id"], record["record_id"], record["sequence"], _dump(record), record["payload_digest"], _now_iso(now_unix)),
            )
            terminal = record["record_kind"] == "outcome"
            if terminal:
                self._complete_attempt(connection, workflow, claim, body, counters, now_unix)
            else:
                connection.execute("UPDATE runtime_workflow_claims SET next_sequence = next_sequence + 1, updated_at = ? WHERE claim_id = ?",
                                   (_now_iso(now_unix), claim["claim_id"]))
                connection.execute("UPDATE runtime_workflows SET counters_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                                   (_dump(counters), _now_iso(now_unix), workflow_job_id))
            return self._state(self._workflow(connection, workflow_job_id))

    def _validate_conformance_binding(self, claim: Any, body: dict[str, Any]) -> None:
        record = body["record"]
        binding = body["conformance_binding"]
        if record["record_kind"] != "outcome":
            raise RuntimeWorkflowError(
                "PAYLOAD_DIGEST_INVALID", "conformance binding requires a terminal outcome", 400
            )
        if binding["payload_digest"] != claim["check_definition_digest"]:
            raise RuntimeWorkflowError(
                "PAYLOAD_DIGEST_INVALID", "conformance request digest mismatch", 409
            )
        if binding["execution_result"] != record["payload"]["terminal_outcome"]:
            raise RuntimeWorkflowError(
                "PAYLOAD_DIGEST_INVALID", "conformance execution result mismatch", 409
            )
        artifact = body["verified_report_artifact"]
        if binding["report_artifact"] != artifact or binding["report_digest"] != artifact["sha256"]:
            raise RuntimeWorkflowError(
                "CHECK_REPORT_UNVERIFIED", "conformance report identity mismatch", 409
            )
        outcome_error = record["payload"].get("safe_error")
        binding_error = binding.get("safe_error")
        if outcome_error is None:
            if binding_error is not None:
                raise RuntimeWorkflowError(
                    "PAYLOAD_DIGEST_INVALID", "unexpected conformance safe error", 409
                )
        elif binding_error != {
            key: outcome_error[key] for key in ("code", "message", "retryable")
        }:
            raise RuntimeWorkflowError(
                "PAYLOAD_DIGEST_INVALID", "conformance safe error mismatch", 409
            )

    def _complete_attempt(self, connection: Any, workflow: Any, claim: Any, body: dict[str, Any], counters: dict[str, int], now_unix: int) -> None:
        outcome = body["record"]["payload"]
        status = outcome["terminal_outcome"]
        counters["active_steps"] -= 1
        safe_error = outcome.get("safe_error")
        receipt = {"workflow_step_id": claim["workflow_step_id"], "step_kind": claim["step_kind"],
                   "attempt_number": claim["attempt_number"], "status": status,
                   "execution_constraints_digest": claim["execution_constraints_digest"]}
        if safe_error:
            receipt["safe_error"] = {**safe_error, "reconcile_required": False}
        if claim["step_kind"] == "check" and (
            status == "succeeded" or "conformance_binding" in body
        ):
            artifact = body["verified_report_artifact"]
            receipt["verified_check_report_artifact"] = artifact
            counters["total_artifact_bytes"] += artifact["size_bytes"]
            self._record_check_edge(
                connection, workflow, claim, artifact, counters
            )
        if claim["step_kind"] == "check" and "conformance_binding" in body:
            connection.execute(
                "INSERT INTO runtime_conformance_bindings VALUES (?, ?, ?, ?, ?, ?)",
                (workflow["workflow_job_id"], claim["workflow_step_id"],
                 claim["attempt_number"], claim["claim_id"],
                 _dump(body["conformance_binding"]), _now_iso(now_unix)),
            )
        connection.execute("UPDATE runtime_workflow_claims SET status = ?, next_sequence = next_sequence + 1, terminal_record_json = ?, updated_at = ? WHERE claim_id = ?",
                           (status, _dump(receipt), _now_iso(now_unix), claim["claim_id"]))
        connection.execute("UPDATE runtime_workflow_steps SET state = ? WHERE workflow_job_id = ? AND workflow_step_id = ?",
                           (status, workflow["workflow_job_id"], claim["workflow_step_id"]))
        workflow_state = "running"
        terminal_error = None
        if status != "succeeded":
            workflow_state = {"cancelled": "cancelled", "timed_out": "timed_out"}.get(status, "failed")
            terminal_error = {"schema_version": "pdx_runtime_provider_workflow_error_v1",
                              "code": safe_error["code"], "message": safe_error["message"],
                              "retryable": safe_error["retryable"], "reconcile_required": False}
        else:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM runtime_workflow_steps WHERE workflow_job_id = ? AND state != 'succeeded'",
                (workflow["workflow_job_id"],),
            ).fetchone()[0]
            if remaining == 0:
                workflow_state = "completed"
        connection.execute("UPDATE runtime_workflows SET state = ?, counters_json = ?, terminal_error_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                           (workflow_state, _dump(counters), _dump(terminal_error) if terminal_error else None, _now_iso(now_unix), workflow["workflow_job_id"]))
        if workflow_state in TERMINAL_STATES:
            self._freeze_receipt(connection, workflow["workflow_job_id"], now_unix)

    def _preflight_check_artifact(
        self, connection: Any, workflow: Any, claim: Any, body: dict[str, Any],
        counters: dict[str, int], now_unix: int,
    ) -> None:
        artifact = body["verified_report_artifact"]
        if body["record"]["payload"]["report_artifact"] != artifact["uri"]:
            raise RuntimeWorkflowError(
                "CHECK_REPORT_UNVERIFIED", "report identity does not match outcome", 409
            )
        plan = json.loads(workflow["plan_json"])
        edge = next(
            (item for item in plan["artifact_edges"]
             if item["producer_step_id"] == claim["workflow_step_id"]
             and item["artifact_role"] == "check_report"),
            None,
        )
        if edge is None:
            raise RuntimeWorkflowError(
                "ARTIFACT_EDGE_UNPLANNED", "check report edge is not planned", 409
            )
        if counters["total_artifact_bytes"] + artifact["size_bytes"] > plan["budgets"]["max_total_artifact_bytes"]:
            self._budget_exhausted(
                connection, workflow, counters, "artifact byte budget exhausted", now_unix
            )
        if counters["cross_step_artifact_edges"] >= plan["budgets"]["max_cross_step_artifact_edges"]:
            self._budget_exhausted(
                connection, workflow, counters, "artifact edge budget exhausted", now_unix
            )
        duplicate = connection.execute(
            "SELECT identity_digest FROM runtime_artifact_edges WHERE workflow_job_id = ? AND edge_id = ? AND artifact_id = ?",
            (workflow["workflow_job_id"], edge["edge_id"], artifact["artifact_id"]),
        ).fetchone()
        if duplicate is not None:
            raise RuntimeWorkflowError(
                "ARTIFACT_RECORD_CONFLICT", "artifact was already recorded", 409
            )

    def _record_check_edge(
        self, connection: Any, workflow: Any, claim: Any,
        artifact: dict[str, Any], counters: dict[str, int],
    ) -> None:
        plan = json.loads(workflow["plan_json"])
        edge = next((item for item in plan["artifact_edges"] if item["producer_step_id"] == claim["workflow_step_id"] and item["artifact_role"] == "check_report"), None)
        if edge is None:
            raise RuntimeWorkflowError("ARTIFACT_EDGE_UNPLANNED", "check report edge is not planned", 409)
        identity_digest = _digest(artifact)
        document = {"edge_id": edge["edge_id"], "artifact": artifact, "artifact_identity_digest": identity_digest,
                    "producer_step_id": claim["workflow_step_id"], "producer_attempt_number": claim["attempt_number"],
                    "consumer_step_id": edge["consumer_step_id"], "recorded_once": True}
        try:
            connection.execute("INSERT INTO runtime_artifact_edges VALUES (?, ?, ?, ?, ?)",
                               (workflow["workflow_job_id"], edge["edge_id"], artifact["artifact_id"], identity_digest, _dump(document)))
        except Exception as exc:
            raise RuntimeWorkflowError("ARTIFACT_RECORD_CONFLICT", "artifact was already recorded", 409) from exc
        counters["cross_step_artifact_edges"] += 1

    def cancel(self, workflow_job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self._validate("pdx_runtime_workflow_cancel_v1.schema.json", body)
        if body["workflow_job_id"] != workflow_job_id:
            raise RuntimeWorkflowError("PAYLOAD_DIGEST_INVALID", "path/body workflow mismatch", 400)
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            if workflow["state"] in TERMINAL_STATES:
                return self._state(workflow)
            counters = json.loads(workflow["counters_json"])
            counters["active_steps"] = 0
            error = {"schema_version": "pdx_runtime_provider_workflow_error_v1", "code": "WORKFLOW_NOT_ACTIVE",
                     "message": body["reason"], "retryable": False, "reconcile_required": False}
            now = _now_iso()
            connection.execute("UPDATE runtime_workflow_claims SET status = 'cancelled', updated_at = ? WHERE workflow_job_id = ? AND status = 'active'", (now, workflow_job_id))
            connection.execute("UPDATE runtime_workflows SET state = 'cancelled', counters_json = ?, terminal_error_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                               (_dump(counters), _dump(error), now, workflow_job_id))
            self._freeze_receipt(connection, workflow_job_id, int(time.time()))
            return self._state(self._workflow(connection, workflow_job_id))

    def reconcile(self, workflow_job_id: str, body: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
        self._validate("pdx_runtime_workflow_reconcile_v1.schema.json", body)
        if body["workflow_job_id"] != workflow_job_id:
            raise RuntimeWorkflowError("PAYLOAD_DIGEST_INVALID", "path/body workflow mismatch", 400)
        now_unix = int(time.time() if now is None else now)
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            if workflow["state"] in TERMINAL_STATES:
                return self._state(workflow)
            expired = connection.execute(
                "SELECT * FROM runtime_workflow_claims WHERE workflow_job_id = ? AND status = 'active' AND lease_expires_unix < ?",
                (workflow_job_id, now_unix),
            ).fetchall()
            counters = json.loads(workflow["counters_json"])
            for claim in expired:
                self._meter_runtime(connection, workflow, claim, counters, now_unix)
                updated = connection.execute(
                    "UPDATE runtime_workflow_claims SET status = 'stale_rejected', updated_at = ? WHERE claim_id = ? AND status = 'active' AND lease_token_digest = ? AND lease_expires_unix < ?",
                    (_now_iso(now_unix), claim["claim_id"], claim["lease_token_digest"], now_unix),
                )
                if updated.rowcount == 1:
                    counters["active_steps"] -= 1
                    connection.execute("UPDATE runtime_workflow_steps SET state = 'pending' WHERE workflow_job_id = ? AND workflow_step_id = ? AND state = 'running'",
                                       (workflow_job_id, claim["workflow_step_id"]))
            connection.execute("UPDATE runtime_workflows SET counters_json = ?, updated_at = ? WHERE workflow_job_id = ?",
                               (_dump(counters), _now_iso(now_unix), workflow_job_id))
            return self._state(self._workflow(connection, workflow_job_id))

    def get_receipt(self, workflow_job_id: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            workflow = self._workflow(connection, workflow_job_id)
            if not workflow["receipt_json"]:
                raise RuntimeWorkflowError("WORKFLOW_NOT_ACTIVE", "receipt is available only after terminal state", 410)
            return json.loads(workflow["receipt_json"])

    def get_conformance_binding(
        self, workflow_job_id: str, workflow_step_id: str
    ) -> dict[str, Any]:
        with self.store.transaction() as connection:
            self._workflow(connection, workflow_job_id)
            row = connection.execute(
                "SELECT binding_json FROM runtime_conformance_bindings "
                "WHERE workflow_job_id = ? AND workflow_step_id = ? "
                "ORDER BY attempt_number DESC LIMIT 1",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if row is None:
                raise RuntimeWorkflowError(
                    "WORKFLOW_NOT_ACTIVE", "conformance binding not found", 404
                )
            return json.loads(row["binding_json"])

    def _freeze_receipt(self, connection: Any, workflow_job_id: str, now_unix: int) -> None:
        workflow = self._workflow(connection, workflow_job_id)
        if workflow["receipt_json"]:
            return
        steps = [json.loads(row[0]) for row in connection.execute(
            "SELECT terminal_record_json FROM runtime_workflow_claims WHERE workflow_job_id = ? AND terminal_record_json IS NOT NULL ORDER BY rowid",
            (workflow_job_id,),
        ).fetchall()]
        edges = [json.loads(row[0]) for row in connection.execute(
            "SELECT receipt_json FROM runtime_artifact_edges WHERE workflow_job_id = ? ORDER BY rowid", (workflow_job_id,)
        ).fetchall()]
        receipt = {"schema_version": "pdx_runtime_provider_workflow_receipt_v1",
                   "receipt_id": f"receipt_{workflow_job_id}", "workflow_job_id": workflow_job_id,
                   "task_id": workflow["task_id"], "run_id": workflow["run_id"], "plan_digest": workflow["plan_digest"],
                   "status": workflow["state"], "step_receipts": steps, "artifact_edges": edges,
                   "authority_records": [], "final_counters": json.loads(workflow["counters_json"]), "recorded_at": _now_iso(now_unix)}
        if workflow["terminal_error_json"]:
            receipt["terminal_error"] = json.loads(workflow["terminal_error_json"])
        connection.execute("UPDATE runtime_workflows SET receipt_json = ? WHERE workflow_job_id = ?", (_dump(receipt), workflow_job_id))
