"""Durable governed dynamic-dispatch authority built on the workflow store."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_engine.runtime_workflows import RuntimeWorkflowError
from pdx_artifact_engine.runtime_workflows.store import RuntimeWorkflowStore

from .contracts import validate
from .registry import DispatchToolRegistry


def _now_iso() -> str:
    return datetime.fromtimestamp(int(time.time()), tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _dump(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _without(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in keys}


def _require_principal(body: dict[str, Any], authenticated_principal: str) -> None:
    if not authenticated_principal:
        raise RuntimeWorkflowError(
            "DISPATCH_CALLER_UNAUTHORIZED", "authenticated control plane required", 401
        )
    asserted = body.get("caller_authority_id")
    if asserted is not None and asserted != authenticated_principal:
        raise RuntimeWorkflowError(
            "DISPATCH_CALLER_MISMATCH", "caller authority does not match transport", 403
        )


def _proposal_schema_digest() -> str:
    schema = resources.files(
        "pdx_artifact_engine.contracts.dynamic_dispatch"
    ).joinpath("pdx_dynamic_dispatch_tool_proposal_v1.schema.json")
    return hashlib.sha256(schema.read_bytes()).hexdigest()


def _validate_argument_bounds(value: Any, limits: dict[str, int]) -> None:
    total_keys = 0
    secret_refs = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal total_keys, secret_refs
        if depth > limits["max_depth"]:
            raise RuntimeWorkflowError(
                "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "argument depth exceeded", 400
            )
        if isinstance(item, str):
            item.encode("utf-8", "strict")
            secret_refs += int(item.startswith("secret-ref://"))
        elif isinstance(item, list):
            if len(item) > limits["max_array_length"]:
                raise RuntimeWorkflowError(
                    "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "array bound exceeded", 400
                )
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, dict):
            if len(item) > limits["max_properties_per_object"]:
                raise RuntimeWorkflowError(
                    "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "object bound exceeded", 400
                )
            total_keys += len(item)
            if total_keys > limits["max_total_keys"]:
                raise RuntimeWorkflowError(
                    "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "key bound exceeded", 400
                )
            for key, child in item.items():
                key.encode("utf-8", "strict")
                visit(child, depth + 1)
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise RuntimeWorkflowError(
                "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "argument type unsupported", 400
            )

    try:
        visit(value, 1)
        canonical = rfc8785.dumps(value)
    except (UnicodeError, ValueError, rfc8785.CanonicalizationError) as exc:
        raise RuntimeWorkflowError(
            "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "arguments are not I-JSON", 400
        ) from exc
    if (
        secret_refs > limits["max_secret_refs"]
        or len(canonical) > limits["max_canonical_bytes"]
    ):
        raise RuntimeWorkflowError(
            "DISPATCH_PROPOSAL_BOUNDS_EXCEEDED", "canonical argument bound exceeded", 400
        )


@dataclass
class DynamicDispatchService:
    store: RuntimeWorkflowStore
    registry: DispatchToolRegistry | None = None

    def _validate(self, schema: str, body: dict[str, Any]) -> None:
        try:
            validate(schema, body)
        except ValueError as exc:
            raise RuntimeWorkflowError(
                "DISPATCH_POLICY_MISMATCH", str(exc), 400
            ) from exc

    def _workflow_and_dispatch_step(
        self, connection: Any, workflow_job_id: str, workflow_step_id: str
    ) -> tuple[Any, dict[str, Any]]:
        workflow = connection.execute(
            "SELECT * FROM runtime_workflows WHERE workflow_job_id = ?",
            (workflow_job_id,),
        ).fetchone()
        if workflow is None or workflow["contract_version"] != 2:
            raise RuntimeWorkflowError(
                "DISPATCH_POLICY_MISMATCH", "v2 workflow not found", 404
            )
        plan = json.loads(workflow["plan_json"])
        step = next(
            (
                item
                for item in plan["steps"]
                if item["workflow_step_id"] == workflow_step_id
            ),
            None,
        )
        if step is None or step["step_kind"] != "dispatch":
            raise RuntimeWorkflowError(
                "DISPATCH_POLICY_MISMATCH", "step is not a dispatch step", 409
            )
        return workflow, step

    def register_policy(
        self,
        workflow_job_id: str,
        workflow_step_id: str,
        body: dict[str, Any],
        *,
        authenticated_principal: str,
    ) -> dict[str, Any]:
        self._validate("pdx_dynamic_dispatch_policy_register_request_v1.schema.json", body)
        _require_principal(body, authenticated_principal)
        if (
            body["workflow_job_id"] != workflow_job_id
            or body["workflow_step_id"] != workflow_step_id
        ):
            raise RuntimeWorkflowError(
                "DISPATCH_POLICY_MISMATCH", "path and policy binding differ", 409
            )
        tools = sorted(body["allowed_tools"], key=lambda item: item["name"])
        names = [tool["name"] for tool in tools]
        if len(set(names)) != len(names) or body["allowed_tool_names"] != names:
            raise RuntimeWorkflowError(
                "DISPATCH_POLICY_MISMATCH", "allowed tool order or identity differs", 409
            )
        for tool in tools:
            if tool["deployment"]["identity_digest"] != _digest(
                _without(tool["deployment"], "identity_digest")
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "deployment identity digest differs", 409
                )
        now = _now_iso()
        policy = {
            "schema_version": "pdx_dynamic_dispatch_policy_v1",
            "dispatch_policy_id": body["dispatch_policy_id"],
            "workflow_job_id": workflow_job_id,
            "workflow_step_id": workflow_step_id,
            "run_a_plan_digest": body["run_a_plan_digest"],
            "decision_step_id": body["decision_step_id"],
            "policy_status": "active",
            "policy_revision_epoch": body["policy_revision_epoch"],
            "allowed_tool_names": names,
            "allowed_tool_names_digest": _digest(names),
            "allowed_tools": tools,
            "frozen_tool_definitions_digest": _digest(tools),
            "proposal_limits": body["proposal_limits"],
            "expires_at": body.get("expires_at"),
            "revoked_at": None,
            "registered_by": authenticated_principal,
            "registered_at": now,
        }
        policy["policy_digest"] = _digest(policy)
        self._validate("pdx_dynamic_dispatch_policy_v1.schema.json", policy)
        with self.store.transaction() as connection:
            _, step = self._workflow_and_dispatch_step(
                connection, workflow_job_id, workflow_step_id
            )
            if (
                step["dispatch_policy_id"] != body["dispatch_policy_id"]
                or step["run_a_plan_digest"] != body["run_a_plan_digest"]
                or step["decision_step_id"] != body["decision_step_id"]
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "policy does not match frozen plan", 409
                )
            existing = connection.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if existing is not None:
                existing_policy = json.loads(existing["policy_json"])
                comparable = {**policy, "registered_at": existing_policy["registered_at"]}
                comparable["policy_digest"] = _digest(
                    _without(comparable, "policy_digest")
                )
                if comparable != existing_policy:
                    raise RuntimeWorkflowError(
                        "DISPATCH_POLICY_MISMATCH", "policy already registered", 409
                    )
                return existing_policy
            connection.execute(
                """INSERT INTO dynamic_dispatch_policies(
                    dispatch_policy_id, workflow_job_id, workflow_step_id,
                    policy_revision_epoch, policy_digest, policy_status,
                    policy_json, registered_by, registered_at,
                    revocation_binding_digest, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, NULL, ?)""",
                (
                    policy["dispatch_policy_id"], workflow_job_id, workflow_step_id,
                    policy["policy_revision_epoch"], policy["policy_digest"],
                    _dump(policy), authenticated_principal, now, now,
                ),
            )
        return policy

    def revoke_policy(
        self,
        workflow_job_id: str,
        workflow_step_id: str,
        body: dict[str, Any],
        *,
        authenticated_principal: str,
    ) -> dict[str, Any]:
        self._validate("pdx_dynamic_dispatch_policy_revoke_v1.schema.json", body)
        _require_principal(body, authenticated_principal)
        binding_digest = _digest(
            _without(body, "schema_version", "request_id", "caller_authority_id")
        )
        with self.store.transaction() as connection:
            self._workflow_and_dispatch_step(connection, workflow_job_id, workflow_step_id)
            row = connection.execute(
                """SELECT * FROM dynamic_dispatch_policies
                   WHERE dispatch_policy_id = ? AND workflow_job_id = ?
                   AND workflow_step_id = ?""",
                (body["dispatch_policy_id"], workflow_job_id, workflow_step_id),
            ).fetchone()
            if row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_NOT_FOUND", "dispatch policy not found", 404
                )
            if row["policy_status"] == "revoked":
                if row["revocation_binding_digest"] != binding_digest:
                    raise RuntimeWorkflowError(
                        "DISPATCH_POLICY_MISMATCH", "revocation binding differs", 409
                    )
                return self.get_projection(
                    workflow_job_id, workflow_step_id, connection=connection
                )
            if (
                row["policy_revision_epoch"] != body["expected_policy_revision_epoch"]
                or row["policy_digest"] != body["expected_policy_digest"]
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "revocation CAS failed", 409
                )
            active = connection.execute(
                """SELECT authoritative_activation_id, status
                   FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND workflow_step_id = ?
                   AND status IN ('activated', 'executing')""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if active is not None:
                connection.execute(
                    """UPDATE dynamic_dispatch_activations
                       SET cancellation_requested = 1,
                           status = 'cancellation_requested', updated_at = ?
                       WHERE authoritative_activation_id = ?""",
                    (_now_iso(), active["authoritative_activation_id"]),
                )
            policy = json.loads(row["policy_json"])
            policy["policy_status"] = "revoked"
            policy["policy_revision_epoch"] += 1
            policy["revoked_at"] = _now_iso()
            policy["policy_digest"] = _digest(_without(policy, "policy_digest"))
            self._validate("pdx_dynamic_dispatch_policy_v1.schema.json", policy)
            connection.execute(
                """UPDATE dynamic_dispatch_policies SET policy_revision_epoch = ?,
                   policy_digest = ?, policy_status = 'revoked', policy_json = ?,
                   revocation_binding_digest = ?, updated_at = ?
                   WHERE dispatch_policy_id = ?""",
                (
                    policy["policy_revision_epoch"], policy["policy_digest"],
                    _dump(policy), binding_digest, _now_iso(),
                    policy["dispatch_policy_id"],
                ),
            )
            return self.get_projection(
                workflow_job_id, workflow_step_id, connection=connection
            )

    def reconcile(
        self,
        workflow_job_id: str,
        workflow_step_id: str,
        body: dict[str, Any],
        *,
        authenticated_principal: str,
    ) -> dict[str, Any]:
        """Return durable authority without accepting caller-supplied outcomes."""
        self._validate("pdx_dynamic_dispatch_reconcile_v1.schema.json", body)
        _require_principal(body, authenticated_principal)
        with self.store.read_transaction() as connection:
            self._workflow_and_dispatch_step(
                connection, workflow_job_id, workflow_step_id
            )
            row = connection.execute(
                """SELECT dispatch_attempt_id FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND workflow_step_id = ?
                   ORDER BY rowid DESC LIMIT 1""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_NOT_FOUND", "dispatch attempt not found", 404
                )
            if row["dispatch_attempt_id"] != body["expected_dispatch_attempt_id"]:
                raise RuntimeWorkflowError(
                    "DISPATCH_IDEMPOTENCY_CONFLICT",
                    "expected dispatch attempt differs",
                    409,
                )
            return self.get_projection(
                workflow_job_id, workflow_step_id, connection=connection
            )

    def import_decision(
        self,
        workflow_job_id: str,
        workflow_step_id: str,
        body: dict[str, Any],
        *,
        authenticated_principal: str,
    ) -> dict[str, Any]:
        self._validate("pdx_dynamic_dispatch_decision_import_request_v1.schema.json", body)
        _require_principal(body, authenticated_principal)
        receipt = body["decision_receipt"]
        if (
            body["workflow_job_id"] != workflow_job_id
            or body["workflow_step_id"] != workflow_step_id
            or receipt["workflow_job_id"] != workflow_job_id
            or receipt["workflow_step_id"] != workflow_step_id
            or receipt["source_manifest_artifact"] != body["source_manifest_artifact"]
        ):
            raise RuntimeWorkflowError(
                "DISPATCH_DECISION_BINDING_MISMATCH", "decision binding differs", 409
            )
        with self.store.transaction() as connection:
            self._workflow_and_dispatch_step(connection, workflow_job_id, workflow_step_id)
            policy_row = connection.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE dispatch_policy_id = ?",
                (receipt["dispatch_policy_id"],),
            ).fetchone()
            if policy_row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_NOT_FOUND", "dispatch policy not found", 404
                )
            policy = json.loads(policy_row["policy_json"])
            for key in (
                "workflow_job_id", "workflow_step_id", "dispatch_policy_id",
                "policy_revision_epoch", "policy_digest",
            ):
                if receipt[key] != policy[key]:
                    raise RuntimeWorkflowError(
                        "DISPATCH_DECISION_BINDING_MISMATCH",
                        "decision does not match policy",
                        409,
                    )
            if receipt["tool_name"] not in policy["allowed_tool_names"]:
                raise RuntimeWorkflowError(
                    "DISPATCH_TOOL_NOT_ALLOWED", "tool is not allowed", 409
                )
            if receipt["proposal_schema_digest"] != _proposal_schema_digest():
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_BINDING_MISMATCH",
                    "proposal schema digest differs",
                    409,
                )
            _validate_argument_bounds(receipt["arguments"], policy["proposal_limits"])
            if receipt["arguments_digest"] != _digest(receipt["arguments"]):
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_BINDING_MISMATCH", "argument digest differs", 409
                )
            proposal = {
                "proposal_schema_id": receipt["proposal_schema_id"],
                "proposal_schema_digest": receipt["proposal_schema_digest"],
                "tool_name": receipt["tool_name"],
                "arguments": receipt["arguments"],
            }
            if receipt["canonical_proposal_digest"] != _digest(proposal):
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_BINDING_MISMATCH", "proposal digest differs", 409
                )
            if receipt["decision_receipt_digest"] != _digest(
                _without(receipt, "decision_receipt_digest")
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_BINDING_MISMATCH", "receipt digest differs", 409
                )
            existing = connection.execute(
                "SELECT * FROM dynamic_dispatch_decisions WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if existing is not None:
                if existing["decision_receipt_digest"] != receipt["decision_receipt_digest"]:
                    raise RuntimeWorkflowError(
                        "DISPATCH_DECISION_BINDING_MISMATCH",
                        "decision is already recorded",
                        409,
                    )
                return self.get_projection(
                    workflow_job_id, workflow_step_id, connection=connection
                )
            connection.execute(
                """INSERT INTO dynamic_dispatch_decisions(
                    decision_receipt_id, workflow_job_id, workflow_step_id,
                    dispatch_policy_id, decision_receipt_digest, receipt_json,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt["decision_receipt_id"], workflow_job_id,
                    workflow_step_id, receipt["dispatch_policy_id"],
                    receipt["decision_receipt_digest"], _dump(receipt), _now_iso(),
                ),
            )
            return self.get_projection(
                workflow_job_id, workflow_step_id, connection=connection
            )

    def get_projection(
        self, workflow_job_id: str, workflow_step_id: str, *, connection: Any | None = None
    ) -> dict[str, Any]:
        def build(active: Any) -> dict[str, Any]:
            workflow, _ = self._workflow_and_dispatch_step(
                active, workflow_job_id, workflow_step_id
            )
            policy_row = active.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            decision = active.execute(
                "SELECT 1 FROM dynamic_dispatch_decisions WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            step_row = active.execute(
                """SELECT attempt_count FROM runtime_workflow_steps
                   WHERE workflow_job_id = ? AND workflow_step_id = ?""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            activation = active.execute(
                """SELECT * FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND workflow_step_id = ?
                   ORDER BY rowid DESC LIMIT 1""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            policy = None
            phase = "policy_pending"
            if policy_row is not None:
                policy = {
                    key: policy_row[key]
                    for key in (
                        "dispatch_policy_id", "policy_revision_epoch",
                        "policy_digest", "policy_status",
                    )
                }
                phase = "decision_recorded" if decision is not None else "decision_pending"
            active_activation = None
            if activation is not None:
                if activation["terminal_receipt_json"]:
                    phase = "terminal"
                else:
                    phase = "executing" if activation["status"] == "executing" else "activated"
                    active_activation = {
                        "dispatch_attempt_id": activation["dispatch_attempt_id"],
                        "authoritative_activation_id": activation["authoritative_activation_id"],
                        "run_b_id": activation["run_b_id"],
                        "started_at": activation["created_at"],
                    }
            terminal_receipt = None
            if activation is not None and activation["terminal_receipt_json"]:
                terminal = json.loads(activation["terminal_receipt_json"])
                terminal_receipt = {
                    "receipt_id": terminal["receipt_id"],
                    "status": terminal["status"],
                    "receipt_digest": terminal["receipt_digest"],
                    "receipt_cas_published": terminal["receipt_cas_published"],
                }
            result = {
                "schema_version": "pdx_dynamic_dispatch_step_projection_v1",
                "workflow_job_id": workflow_job_id,
                "workflow_step_id": workflow_step_id,
                "plan_digest": workflow["plan_digest"],
                "policy": policy,
                "phase": phase,
                "attempt_count": step_row["attempt_count"],
                "active_activation": active_activation,
                "terminal_receipt": terminal_receipt,
                "reconciliation_required": bool(
                    terminal_receipt
                    and json.loads(activation["terminal_receipt_json"])[
                        "reconciliation_required"
                    ]
                ),
                "updated_at": workflow["updated_at"],
            }
            self._validate("pdx_dynamic_dispatch_step_projection_v1.schema.json", result)
            return result

        if connection is not None:
            return build(connection)
        with self.store.read_transaction() as active:
            return build(active)

    def get_receipt(
        self, workflow_job_id: str, workflow_step_id: str
    ) -> dict[str, Any]:
        with self.store.read_transaction() as connection:
            self._workflow_and_dispatch_step(connection, workflow_job_id, workflow_step_id)
            row = connection.execute(
                """SELECT terminal_receipt_json FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND workflow_step_id = ?
                   AND terminal_receipt_json IS NOT NULL ORDER BY rowid DESC LIMIT 1""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            if row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_NOT_TERMINAL",
                    "dispatch receipt is not available",
                    410,
                )
            return json.loads(row["terminal_receipt_json"])

    def activate(
        self,
        workflow_job_id: str,
        workflow_step_id: str,
        body: dict[str, Any],
        *,
        authenticated_principal: str,
    ) -> dict[str, Any]:
        self._validate("pdx_dynamic_dispatch_activation_request_v1.schema.json", body)
        _require_principal(body, authenticated_principal)
        if (
            body["workflow_job_id"] != workflow_job_id
            or body["workflow_step_id"] != workflow_step_id
        ):
            raise RuntimeWorkflowError(
                "DISPATCH_DECISION_BINDING_MISMATCH", "path binding differs", 409
            )
        with self.store.transaction() as connection:
            workflow, step = self._workflow_and_dispatch_step(
                connection, workflow_job_id, workflow_step_id
            )
            if workflow["state"] not in {"pending", "running"}:
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "workflow is terminal", 410
                )
            policy_row = connection.execute(
                "SELECT * FROM dynamic_dispatch_policies WHERE dispatch_policy_id = ?",
                (body["dispatch_policy_id"],),
            ).fetchone()
            if policy_row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_NOT_FOUND", "dispatch policy not found", 404
                )
            policy = json.loads(policy_row["policy_json"])
            if policy["policy_status"] != "active":
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_REVOKED", "dispatch policy is revoked", 410
                )
            if policy["expires_at"] is not None:
                expires = datetime.fromisoformat(policy["expires_at"])
                if expires <= datetime.now(tz=UTC):
                    raise RuntimeWorkflowError(
                        "DISPATCH_POLICY_EXPIRED", "dispatch policy expired", 410
                    )
            decision_row = connection.execute(
                "SELECT * FROM dynamic_dispatch_decisions WHERE decision_receipt_id = ?",
                (body["decision_receipt_id"],),
            ).fetchone()
            if decision_row is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_NOT_FOUND", "decision receipt not found", 404
                )
            decision = json.loads(decision_row["receipt_json"])
            for request_key, decision_key in (
                ("workflow_job_id", "workflow_job_id"),
                ("workflow_step_id", "workflow_step_id"),
                ("source_run_id", "source_run_id"),
                ("source_plan_digest", "source_plan_digest"),
                ("decision_receipt_id", "decision_receipt_id"),
                ("decision_receipt_digest", "decision_receipt_digest"),
            ):
                if body[request_key] != decision[decision_key]:
                    raise RuntimeWorkflowError(
                        "DISPATCH_DECISION_BINDING_MISMATCH",
                        "activation does not match decision",
                        409,
                    )
            if (
                body["policy_digest_assertion"] != policy["policy_digest"]
                or body["policy_revision_epoch"] != policy["policy_revision_epoch"]
                or step["dispatch_policy_id"] != policy["dispatch_policy_id"]
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "activation policy differs", 409
                )
            binding = {
                "workflow_job_id": workflow_job_id,
                "workflow_step_id": workflow_step_id,
                "source_run_id": body["source_run_id"],
                "source_plan_digest": body["source_plan_digest"],
                "decision_receipt_id": body["decision_receipt_id"],
                "decision_receipt_digest": body["decision_receipt_digest"],
                "dispatch_policy_id": policy["dispatch_policy_id"],
                "policy_digest": policy["policy_digest"],
                "policy_revision_epoch": policy["policy_revision_epoch"],
                "authenticated_principal": authenticated_principal,
            }
            binding_digest = _digest(binding)
            existing = connection.execute(
                """SELECT * FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND workflow_step_id = ? AND idempotency_key = ?""",
                (workflow_job_id, workflow_step_id, body["idempotency_key"]),
            ).fetchone()
            if existing is not None:
                if existing["idempotency_binding_digest"] != binding_digest:
                    raise RuntimeWorkflowError(
                        "DISPATCH_IDEMPOTENCY_CONFLICT",
                        "idempotency binding differs",
                        409,
                    )
                result = json.loads(existing["response_json"])
                result["result"] = "exact_retry"
                return result
            if self.registry is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_UNKNOWN_SKILL", "dispatch registry is unavailable", 409
                )
            tool = self.registry.get(decision["tool_name"])
            expected_tool = next(
                item for item in policy["allowed_tools"]
                if item["name"] == decision["tool_name"]
            )
            if tool is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_UNKNOWN_SKILL", "dispatch tool is not registered", 409
                )
            if tool.frozen_definition != expected_tool:
                raise RuntimeWorkflowError(
                    "DISPATCH_SKILL_DEFINITION_MISMATCH",
                    "live tool differs from frozen policy",
                    409,
                )
            input_error = next(
                iter(
                    Draft202012Validator(
                        tool.input_schema, format_checker=FormatChecker()
                    ).iter_errors(decision["arguments"])
                ),
                None,
            )
            if input_error is not None:
                raise RuntimeWorkflowError(
                    "DISPATCH_INPUT_SCHEMA_INVALID", input_error.message, 409
                )
            step_row = connection.execute(
                """SELECT * FROM runtime_workflow_steps
                   WHERE workflow_job_id = ? AND workflow_step_id = ?""",
                (workflow_job_id, workflow_step_id),
            ).fetchone()
            dependencies = step["depends_on"]
            placeholders = ",".join("?" for _ in dependencies)
            dependency_rows = connection.execute(
                f"""SELECT state FROM runtime_workflow_steps
                    WHERE workflow_job_id = ? AND workflow_step_id IN ({placeholders})""",
                (workflow_job_id, *dependencies),
            ).fetchall()
            if (
                step_row["state"] != "pending"
                or len(dependency_rows) != len(dependencies)
                or any(row["state"] != "succeeded" for row in dependency_rows)
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "dispatch step is not ready", 409
                )
            counters = json.loads(workflow["counters_json"])
            budgets = json.loads(workflow["plan_json"])["budgets"]
            if (
                counters["dispatch_attempts"] >= budgets["max_dispatch_attempts"]
                or counters["active_steps"] >= budgets["max_concurrent_steps"]
                or step_row["attempt_count"] >= step["max_attempts"]
            ):
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH", "dispatch attempt budget exhausted", 409
                )
            attempt_number = step_row["attempt_count"] + 1
            dispatch_attempt_id = f"dispatch_attempt_{uuid.uuid4().hex}"
            activation_id = f"activation_{uuid.uuid4().hex}"
            run_b_id = f"run_{uuid.uuid4().hex}"
            run_b_plan = {
                "schema_version": "pdx_execution_plan_v1",
                "request_id": run_b_id,
                "producer": {"type": "pdx.dynamic_dispatch", "name": "ER-002"},
                "steps": [
                    {
                        "id": "dispatch_tool",
                        "kind": "tool",
                        "tool": decision["tool_name"],
                        "inputs": decision["arguments"],
                    }
                ],
            }
            run_b_plan_digest = _digest(run_b_plan)
            now = _now_iso()
            response = {
                "schema_version": "pdx_dynamic_dispatch_activation_response_v1",
                "activation_request_id": body["activation_request_id"],
                "workflow_job_id": workflow_job_id,
                "workflow_step_id": workflow_step_id,
                "dispatch_attempt_id": dispatch_attempt_id,
                "authoritative_activation_id": activation_id,
                "run_b_id": run_b_id,
                "run_b_plan_digest": run_b_plan_digest,
                "idempotency_binding_digest": binding_digest,
                "result": "created",
                "created_at": now,
            }
            self._validate(
                "pdx_dynamic_dispatch_activation_response_v1.schema.json", response
            )
            connection.execute(
                """INSERT INTO dynamic_dispatch_activations(
                    authoritative_activation_id, activation_request_id,
                    workflow_job_id, workflow_step_id, dispatch_attempt_id,
                    run_b_id, run_b_plan_digest, idempotency_key,
                    idempotency_binding_digest, authenticated_principal,
                    policy_digest, decision_receipt_digest, activation_json,
                    run_b_plan_json, response_json, status,
                    cancellation_requested, execution_started_at, terminal_receipt_json,
                    parent_step_receipt_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'activated', 0, NULL, NULL, NULL, ?, ?)
                """,
                (
                    activation_id, body["activation_request_id"], workflow_job_id,
                    workflow_step_id, dispatch_attempt_id, run_b_id,
                    run_b_plan_digest, body["idempotency_key"], binding_digest,
                    authenticated_principal, policy["policy_digest"],
                    decision["decision_receipt_digest"], _dump(body),
                    _dump(run_b_plan), _dump(response), now, now,
                ),
            )
            counters["dispatch_attempts"] += 1
            counters["active_dispatches"] += 1
            counters["active_steps"] += 1
            connection.execute(
                """UPDATE runtime_workflow_steps SET state = 'running', attempt_count = ?
                   WHERE workflow_job_id = ? AND workflow_step_id = ?""",
                (attempt_number, workflow_job_id, workflow_step_id),
            )
            connection.execute(
                """UPDATE runtime_workflows SET state = 'running', counters_json = ?,
                   updated_at = ? WHERE workflow_job_id = ?""",
                (_dump(counters), now, workflow_job_id),
            )
            return response

    def execute_activation(self, authoritative_activation_id: str) -> dict[str, Any]:
        """Execute one allocated Run B from stored authority, never caller inputs."""
        with self.store.transaction() as connection:
            activation = connection.execute(
                "SELECT * FROM dynamic_dispatch_activations WHERE authoritative_activation_id = ?",
                (authoritative_activation_id,),
            ).fetchone()
            if activation is None:
                raise RuntimeWorkflowError(
                    "DISPATCH_DECISION_NOT_FOUND", "activation not found", 404
                )
            if activation["terminal_receipt_json"]:
                return json.loads(activation["terminal_receipt_json"])
            if activation["status"] == "cancellation_requested":
                decision_row = connection.execute(
                    "SELECT * FROM dynamic_dispatch_decisions WHERE decision_receipt_digest = ?",
                    (activation["decision_receipt_digest"],),
                ).fetchone()
                decision = json.loads(decision_row["receipt_json"])
                policy_row = connection.execute(
                    "SELECT * FROM dynamic_dispatch_policies WHERE dispatch_policy_id = ?",
                    (decision["dispatch_policy_id"],),
                ).fetchone()
                policy = json.loads(policy_row["policy_json"])
                cancel_before_start = True
            else:
                cancel_before_start = False
            if activation["status"] not in {"activated", "cancellation_requested"}:
                raise RuntimeWorkflowError(
                    "DISPATCH_POLICY_MISMATCH",
                    "activation is already executing or cannot execute",
                    409,
                )
            if not cancel_before_start:
                claimed = connection.execute(
                    """UPDATE dynamic_dispatch_activations
                       SET status = 'executing', execution_started_at = ?, updated_at = ?
                       WHERE authoritative_activation_id = ? AND status = 'activated'""",
                    (_now_iso(), _now_iso(), authoritative_activation_id),
                )
                if claimed.rowcount != 1:
                    raise RuntimeWorkflowError(
                        "DISPATCH_IDEMPOTENCY_CONFLICT",
                        "activation execution was claimed concurrently",
                        409,
                    )
                decision_row = connection.execute(
                    "SELECT * FROM dynamic_dispatch_decisions WHERE decision_receipt_digest = ?",
                    (activation["decision_receipt_digest"],),
                ).fetchone()
                decision = json.loads(decision_row["receipt_json"])
                policy_row = connection.execute(
                    "SELECT * FROM dynamic_dispatch_policies WHERE dispatch_policy_id = ?",
                    (decision["dispatch_policy_id"],),
                ).fetchone()
                policy = json.loads(policy_row["policy_json"])
        if cancel_before_start:
            return self._finish_activation(
                authoritative_activation_id,
                policy,
                decision,
                status="cancelled",
                error_code="DISPATCH_CANCELLED",
                output=None,
                execution_occurred=False,
                input_verified=False,
                reconciliation_required=False,
                cancellation={
                    "phase": "not_started",
                    "termination_result": "clean_abort_not_started",
                    "external_outcome": "none",
                },
            )
        if self.registry is None:
            raise RuntimeWorkflowError(
                "DISPATCH_UNKNOWN_SKILL", "dispatch registry is unavailable", 409
            )
        tool = self.registry.get(decision["tool_name"])
        if tool is None:
            return self._finish_activation(
                authoritative_activation_id,
                policy,
                decision,
                status="executor_failed",
                error_code="DISPATCH_UNKNOWN_SKILL",
                output=None,
                execution_occurred=False,
                input_verified=True,
            )
        try:
            output = tool.executor(decision["arguments"])
        except Exception:  # noqa: BLE001 - executor failures are terminal evidence
            return self._finish_activation(
                authoritative_activation_id,
                policy,
                decision,
                status="executor_failed",
                error_code="DISPATCH_EXECUTOR_FAILED",
                output=None,
                execution_occurred=True,
                input_verified=True,
            )
        with self.store.read_transaction() as connection:
            cancellation_requested = bool(
                connection.execute(
                    "SELECT cancellation_requested FROM dynamic_dispatch_activations WHERE authoritative_activation_id = ?",
                    (authoritative_activation_id,),
                ).fetchone()[0]
            )
        if cancellation_requested:
            read_only = tool.frozen_definition["idempotent_read_only"]
            return self._finish_activation(
                authoritative_activation_id,
                policy,
                decision,
                status="cancelled",
                error_code="DISPATCH_CANCELLED",
                output=None,
                execution_occurred=True,
                input_verified=True,
                reconciliation_required=not read_only,
                cancellation={
                    "phase": "running",
                    "termination_result": "cooperative_stop",
                    "external_outcome": (
                        "none" if read_only else "external_side_effects_possible"
                    ),
                },
            )
        output_error = next(
            iter(
                Draft202012Validator(
                    tool.output_schema, format_checker=FormatChecker()
                ).iter_errors(output)
            ),
            None,
        )
        if output_error is not None:
            return self._finish_activation(
                authoritative_activation_id,
                policy,
                decision,
                status="executed_output_invalid",
                error_code="DISPATCH_OUTPUT_SCHEMA_INVALID",
                output=None,
                execution_occurred=True,
                input_verified=True,
            )
        return self._finish_activation(
            authoritative_activation_id,
            policy,
            decision,
            status="completed",
            error_code=None,
            output=output,
            execution_occurred=True,
            input_verified=True,
        )

    def run_next_activation(self) -> dict[str, Any] | None:
        """Execute one durable pending activation; safe for competing workers."""
        with self.store.read_transaction() as connection:
            row = connection.execute(
                """SELECT authoritative_activation_id
                   FROM dynamic_dispatch_activations
                   WHERE terminal_receipt_json IS NULL
                   AND status IN ('activated', 'cancellation_requested')
                   ORDER BY rowid LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        try:
            return self.execute_activation(row["authoritative_activation_id"])
        except RuntimeWorkflowError as exc:
            if exc.code == "DISPATCH_IDEMPOTENCY_CONFLICT":
                return None
            raise

    def _cas_put(
        self, connection: Any, content: bytes, media_type: str
    ) -> dict[str, Any]:
        sha256 = hashlib.sha256(content).hexdigest()
        existing = connection.execute(
            "SELECT content, media_type FROM dynamic_dispatch_cas WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
        if existing is not None and (
            bytes(existing["content"]) != content or existing["media_type"] != media_type
        ):
            raise RuntimeWorkflowError(
                "DISPATCH_SYNTHESIS_FAILED", "CAS identity collision", 500
            )
        if existing is None:
            connection.execute(
                "INSERT INTO dynamic_dispatch_cas VALUES (?, ?, ?, ?, ?)",
                (sha256, media_type, len(content), content, _now_iso()),
            )
        return {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": f"dispatch_{sha256[:24]}",
            "uri": f"artifact://dispatch/{sha256}",
            "sha256": sha256,
            "size_bytes": len(content),
            "media_type": media_type,
        }

    def _finish_activation(
        self,
        authoritative_activation_id: str,
        policy: dict[str, Any],
        decision: dict[str, Any],
        *,
        status: str,
        error_code: str | None,
        output: dict[str, Any] | None,
        execution_occurred: bool,
        input_verified: bool,
        reconciliation_required: bool = False,
        cancellation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.store.transaction() as connection:
            activation = connection.execute(
                "SELECT * FROM dynamic_dispatch_activations WHERE authoritative_activation_id = ?",
                (authoritative_activation_id,),
            ).fetchone()
            if activation["terminal_receipt_json"]:
                return json.loads(activation["terminal_receipt_json"])
            output_identity = None
            if output is not None:
                output_identity = self._cas_put(
                    connection, rfc8785.dumps(output), "application/json"
                )
            receipt = {
                "schema_version": "pdx_dynamic_dispatch_receipt_v1",
                "receipt_id": f"dispatch_receipt_{activation['dispatch_attempt_id']}",
                "activation_request_id": activation["activation_request_id"],
                "authoritative_activation_id": activation["authoritative_activation_id"],
                "workflow_job_id": activation["workflow_job_id"],
                "workflow_step_id": activation["workflow_step_id"],
                "dispatch_attempt_id": activation["dispatch_attempt_id"],
                "run_b_id": activation["run_b_id"],
                "run_b_plan_digest": activation["run_b_plan_digest"],
                "idempotency_key_digest": _digest(activation["idempotency_key"]),
                "idempotency_binding_digest": activation["idempotency_binding_digest"],
                "dispatch_policy_id": policy["dispatch_policy_id"],
                "policy_revision_epoch": decision["policy_revision_epoch"],
                "policy_digest": activation["policy_digest"],
                "allowed_tool_names_digest": policy["allowed_tool_names_digest"],
                "frozen_tool_definitions_digest": policy["frozen_tool_definitions_digest"],
                "resolved_tool": decision["tool_name"],
                "arguments_digest": decision["arguments_digest"],
                "status": status,
                "error_code": error_code,
                "execution_occurred": execution_occurred,
                "input_schema_verified": input_verified,
                "output_schema_verified": output_identity is not None,
                "receipt_cas_published": True,
                "executor_output_artifacts_published": output_identity is not None,
                "artifact_identities": [] if output_identity is None else [output_identity],
                "reconciliation_required": reconciliation_required,
                "recorded_at": _now_iso(),
            }
            if cancellation is not None:
                receipt["cancellation"] = cancellation
            receipt["receipt_digest"] = _digest(receipt)
            self._validate("pdx_dynamic_dispatch_receipt_v1.schema.json", receipt)
            receipt_identity = self._cas_put(
                connection, rfc8785.dumps(receipt), "application/json"
            )
            workflow = connection.execute(
                "SELECT * FROM runtime_workflows WHERE workflow_job_id = ?",
                (activation["workflow_job_id"],),
            ).fetchone()
            plan = json.loads(workflow["plan_json"])
            counters = json.loads(workflow["counters_json"])
            counters["active_dispatches"] -= 1
            counters["active_steps"] -= 1
            if activation["execution_started_at"]:
                started = datetime.fromisoformat(activation["execution_started_at"])
                elapsed = max(0, int((datetime.now(tz=UTC) - started).total_seconds()))
                counters["dispatch_runtime_seconds"] += elapsed
                counters["total_runtime_seconds"] += elapsed
            counters["total_artifact_bytes"] += receipt_identity["size_bytes"]
            if output_identity is not None:
                counters["total_artifact_bytes"] += output_identity["size_bytes"]
            attempt_number = connection.execute(
                "SELECT attempt_count FROM runtime_workflow_steps WHERE workflow_job_id = ? AND workflow_step_id = ?",
                (activation["workflow_job_id"], activation["workflow_step_id"]),
            ).fetchone()[0]
            dispatch_step_receipt = {
                "workflow_step_id": activation["workflow_step_id"],
                "step_kind": "dispatch",
                "attempt_number": attempt_number,
                "status": (
                    "succeeded" if status == "completed"
                    else "cancelled" if status == "cancelled" else "failed"
                ),
                "execution_constraints_digest": _digest(
                    {"policy_digest": activation["policy_digest"]}
                ),
            }
            if status == "completed":
                dispatch_step_receipt["dispatch_receipt_artifact"] = receipt_identity
            else:
                dispatch_step_receipt["safe_error"] = {
                    "code": error_code,
                    "message": "governed dispatch did not complete",
                    "retryable": False,
                    "reconcile_required": False,
                }
            for role, artifact in (
                ("dispatch_receipt", receipt_identity),
                ("dispatch_output", output_identity),
            ):
                if artifact is None:
                    continue
                planned = next(
                    edge for edge in plan["artifact_edges"]
                    if edge["producer_step_id"] == activation["workflow_step_id"]
                    and edge["artifact_role"] == role
                )
                edge_document = {
                    "edge_id": planned["edge_id"],
                    "artifact_role": role,
                    "artifact": artifact,
                    "artifact_identity_digest": _digest(artifact),
                    "producer_step_id": activation["workflow_step_id"],
                    "producer_attempt_number": attempt_number,
                    "consumer_step_id": planned["consumer_step_id"],
                    "recorded_once": True,
                }
                connection.execute(
                    "INSERT INTO runtime_artifact_edges VALUES (?, ?, ?, ?, ?)",
                    (
                        activation["workflow_job_id"], planned["edge_id"],
                        artifact["artifact_id"], edge_document["artifact_identity_digest"],
                        _dump(edge_document),
                    ),
                )
                counters["cross_step_artifact_edges"] += 1
            parent_state = (
                "running" if status == "completed"
                else "cancelled" if status == "cancelled" else "failed"
            )
            terminal_error = None
            if status != "completed":
                parent_error_code = (
                    "PAYLOAD_DIGEST_INVALID"
                    if error_code == "DISPATCH_OUTPUT_SCHEMA_INVALID"
                    else "WORKFLOW_NOT_ACTIVE"
                )
                terminal_error = {
                    "schema_version": "pdx_runtime_provider_workflow_error_v1",
                    "code": parent_error_code,
                    "message": "governed dispatch did not complete",
                    "retryable": False,
                    "reconcile_required": False,
                }
            connection.execute(
                """UPDATE dynamic_dispatch_activations SET status = ?,
                   terminal_receipt_json = ?, parent_step_receipt_json = ?, updated_at = ?
                   WHERE authoritative_activation_id = ?""",
                (
                    status, _dump(receipt), _dump(dispatch_step_receipt),
                    _now_iso(), authoritative_activation_id,
                ),
            )
            connection.execute(
                """UPDATE runtime_workflow_steps SET state = ?
                   WHERE workflow_job_id = ? AND workflow_step_id = ?""",
                (
                    (
                        "succeeded"
                        if status == "completed"
                        else "cancelled" if status == "cancelled" else "failed"
                    ),
                    activation["workflow_job_id"], activation["workflow_step_id"],
                ),
            )
            connection.execute(
                """UPDATE runtime_workflows SET state = ?, counters_json = ?,
                   terminal_error_json = ?, updated_at = ? WHERE workflow_job_id = ?""",
                (
                    parent_state, _dump(counters),
                    None if terminal_error is None else _dump(terminal_error),
                    _now_iso(), activation["workflow_job_id"],
                ),
            )
            if parent_state in {"failed", "cancelled"}:
                self._freeze_parent_receipt(
                    connection, activation["workflow_job_id"], _now_iso()
                )
            return receipt

    def _freeze_parent_receipt(
        self, connection: Any, workflow_job_id: str, recorded_at: str
    ) -> None:
        workflow = connection.execute(
            "SELECT * FROM runtime_workflows WHERE workflow_job_id = ?",
            (workflow_job_id,),
        ).fetchone()
        if workflow["receipt_json"]:
            return
        provider_receipts = [
            json.loads(row[0])
            for row in connection.execute(
                """SELECT terminal_record_json FROM runtime_workflow_claims
                   WHERE workflow_job_id = ? AND terminal_record_json IS NOT NULL
                   ORDER BY rowid""",
                (workflow_job_id,),
            ).fetchall()
        ]
        dispatch_receipts = [
            json.loads(row[0])
            for row in connection.execute(
                """SELECT parent_step_receipt_json FROM dynamic_dispatch_activations
                   WHERE workflow_job_id = ? AND parent_step_receipt_json IS NOT NULL
                   ORDER BY rowid""",
                (workflow_job_id,),
            ).fetchall()
        ]
        edges = [
            json.loads(row[0])
            for row in connection.execute(
                """SELECT receipt_json FROM runtime_artifact_edges
                   WHERE workflow_job_id = ? ORDER BY rowid""",
                (workflow_job_id,),
            ).fetchall()
        ]
        parent = {
            "schema_version": "pdx_runtime_provider_workflow_receipt_v2",
            "receipt_id": f"receipt_{workflow_job_id}",
            "workflow_job_id": workflow_job_id,
            "task_id": workflow["task_id"],
            "run_id": workflow["run_id"],
            "plan_digest": workflow["plan_digest"],
            "status": workflow["state"],
            "step_receipts": [*provider_receipts, *dispatch_receipts],
            "artifact_edges": edges,
            "authority_records": [],
            "final_counters": json.loads(workflow["counters_json"]),
            "recorded_at": recorded_at,
        }
        if workflow["terminal_error_json"]:
            parent["terminal_error"] = json.loads(workflow["terminal_error_json"])
        self._validate("pdx_runtime_provider_workflow_receipt_v2.schema.json", parent)
        connection.execute(
            "UPDATE runtime_workflows SET receipt_json = ? WHERE workflow_job_id = ?",
            (_dump(parent), workflow_job_id),
        )
