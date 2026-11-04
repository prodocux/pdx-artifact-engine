"""Contract validation against independently derived runtime context.

Wire fields are never authority for authentication, parser or storage facts.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent


class Invalid(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Invalid(code)


def ijson(value, depth=0):
    require(depth <= 64, "REQUEST_INVALID")
    if isinstance(value, str):
        require(not any(0xD800 <= ord(ch) <= 0xDFFF for ch in value), "REQUEST_INVALID")
    elif isinstance(value, float):
        require(math.isfinite(value), "REQUEST_INVALID")
    elif isinstance(value, int) and not isinstance(value, bool):
        require(abs(value) <= 9007199254740991, "REQUEST_INVALID")
    elif isinstance(value, list):
        for item in value:
            ijson(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            ijson(key, depth + 1)
            ijson(item, depth + 1)


def parse(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, "REQUEST_INVALID")
            result[k] = v
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Invalid("REQUEST_INVALID")),
        )
        ijson(value)
        return value
    except (ValueError, UnicodeError, OverflowError, RecursionError) as e:
        raise Invalid("REQUEST_INVALID") from e


def digest(value):
    ijson(value)
    try:
        return hashlib.sha256(rfc8785.dumps(value)).hexdigest()
    except (ValueError, UnicodeError) as e:
        raise Invalid("REQUEST_INVALID") from e


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def material(value):
    return {
        k: v
        for k, v in value.items()
        if k not in ("schema_version", "request_id", "idempotency_key")
    }


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "REQUEST_INVALID")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as e:
        raise Invalid("REQUEST_INVALID") from e


def load_schemas():
    schemas = {}
    for folder in ("dependencies", "schemas"):
        for p in sorted((ROOT / folder).glob("*.json")):
            value = json.loads(p.read_text(encoding="utf-8"))
            if "$id" in value:
                schemas[value["$id"]] = value
    registry = Registry()
    for key, value in schemas.items():
        registry = registry.with_resource(key, Resource.from_contents(value))
    return schemas, registry


SCHEMAS, REGISTRY = load_schemas()


def shape(schema_ref, value):
    ijson(value)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": schema_ref,
    }
    require(
        Draft202012Validator(
            schema, registry=REGISTRY, format_checker=FormatChecker()
        ).is_valid(value),
        "REQUEST_INVALID",
    )


def artifacts(value, context):
    if isinstance(value, dict):
        if value.get("schema_version") == "prodocux_opaque_artifact_v1":
            raw = context.get("authorized_artifact_bytes", {}).get(value["artifact_id"])
            require(
                isinstance(raw, bytes)
                and len(raw) == value["size_bytes"]
                and sha(raw) == value["sha256"],
                "EVIDENCE_INVALID",
            )
            require(
                context.get("authorized_artifact_identities", {}).get(
                    value["artifact_id"]
                )
                == value,
                "EVIDENCE_INVALID",
            )
        else:
            for v in value.values():
                artifacts(v, context)
    elif isinstance(value, list):
        for v in value:
            artifacts(v, context)


def auth(value, context, role):
    require(
        context is not None and context.get("authenticated") is True, "UNAUTHENTICATED"
    )
    require(context.get("role") in role.split("|"), "AUTHORITY_FORBIDDEN")
    require(
        value["authority_id"] == context.get("authority_id")
        and value["tenant_id"] == context.get("tenant_id"),
        "RECORD_NOT_FOUND",
    )


def activation_binding(request, context, include_key=True):
    value = {
        k: v for k, v in request.items() if k not in ("request_id", "schema_version")
    }
    if not include_key:
        value.pop("idempotency_key", None)
    return digest(
        {
            **value,
            "authenticated_principal": context["principal"],
            "control_plane_instance_id": context["instance_id"],
        }
    )


def engine_activation(value, context):
    shape("urn:pdx:draft:er003:core:1#/$defs/activationRequest", value)
    auth(value, context, "controller")
    require(context.get("principal") and context.get("instance_id"), "UNAUTHENTICATED")
    binding = activation_binding(value, context)
    if context.get("existing_idempotency") is not None:
        require(context["existing_idempotency"] == binding, "IDEMPOTENCY_CONFLICT")
        return "existing"
    if context.get("existing_subject_binding") is not None:
        require(
            context["existing_subject_binding"]
            == activation_binding(value, context, False),
            "SUBJECT_ALREADY_BOUND",
        )
        return "existing"
    require(not context.get("authorization_used"), "AUTHORIZATION_ALREADY_USED")
    require(not context.get("subject_used"), "SUBJECT_ALREADY_BOUND")
    require(
        context.get("parent_active") and context.get("step_ready"), "PARENT_NOT_READY"
    )
    approval = context["approval"]
    subject = context["subject"]
    for key in ("authority_id", "tenant_id"):
        require(
            approval[key] == value[key] and subject[key] == value[key],
            "OPERATION_BINDING_MISMATCH",
        )
    for key in ("operation_subject_id", "operation_digest"):
        require(
            value[key] == approval[key] == subject[key], "OPERATION_BINDING_MISMATCH"
        )
    for key in ("authorization_id", "issuer_id"):
        require(value[key] == approval[key], "OPERATION_BINDING_MISMATCH")
    require(
        approval["controller_principal"] == context["principal"], "AUTHORITY_FORBIDDEN"
    )
    require(
        approval["execution_policy_digest"] == subject["execution_policy_digest"],
        "OPERATION_BINDING_MISMATCH",
    )
    require(
        value["workflow_job_id"] == context["workflow_job_id"]
        and value["workflow_step_id"] == context["workflow_step_id"]
        and value["plan_digest"] == context["plan_digest"],
        "OPERATION_BINDING_MISMATCH",
    )
    now = timestamp(context["now"])
    fresh = context["freshness"]
    require(
        fresh["issuer_id"] == approval["issuer_id"], "AUTHORITY_FRESHNESS_UNAVAILABLE"
    )
    issued = timestamp(approval["issued_at"])
    expires = timestamp(approval["expires_at"])
    require(issued <= now < expires, "AUTHORIZATION_EXPIRED")
    require(
        not context.get("revoked")
        and approval["issuer_epoch"] == context["issuer_epoch"],
        "AUTHORIZATION_REVOKED",
    )
    require(
        fresh["issuer_epoch"] == context["issuer_epoch"],
        "AUTHORITY_FRESHNESS_UNAVAILABLE",
    )
    require(
        timestamp(fresh["observed_at"]) <= now < timestamp(fresh["valid_until"])
        and 0
        < (
            timestamp(fresh["valid_until"]) - timestamp(fresh["observed_at"])
        ).total_seconds()
        <= 30,
        "AUTHORITY_FRESHNESS_UNAVAILABLE",
    )
    require(approval["max_operations"] == 1, "AUTHORIZATION_ALREADY_USED")
    return "new"


def observation(value, context):
    shape("urn:pdx:draft:er003:core:1#/$defs/observationRequest", value)
    role = "adapter" if value["channel"] == "query_adapter" else "manual"
    auth(value, context, role)
    op = context["operation"]
    for key in (
        "operation_subject_id",
        "operation_id",
        "operation_digest",
        "provider_profile_digest",
        "account_alias",
        "environment",
        "provider_key_digest",
    ):
        require(value[key] == op[key], "OPERATION_BINDING_MISMATCH")
    if op.get("provider_operation_id") is not None:
        require(
            value["provider_operation_id"] == op["provider_operation_id"],
            "OPERATION_BINDING_MISMATCH",
        )
    artifacts(value, context)
    require(context.get("provenance_verified") is True, "EVIDENCE_INVALID")
    if context.get("existing_observation_digest") is not None:
        d = digest(
            {
                **{k: x for k, x in value.items() if k != "request_id"},
                "authenticated_principal": context["principal"],
            }
        )
        require(context["existing_observation_digest"] == d, "OBSERVATION_CONFLICT")
        return "existing"
    if value["channel"] == "manual_authority":
        require(
            context.get("manual_authority_fresh") is True,
            "AUTHORITY_FRESHNESS_UNAVAILABLE",
        )
        require(
            context.get("case_registered") == value["manual_attestation"]["case_id"],
            "EVIDENCE_INVALID",
        )
        if value["outcome"] == "confirmed_not_executed":
            require(
                context.get("submitter_terminated") is True
                and context.get("definitive_nonexecution") is True,
                "EVIDENCE_INVALID",
            )
    previous = context.get("confirmed_outcome")
    if previous and value["outcome"] != previous:
        return (
            "conflict"
            if value["outcome"].startswith("confirmed_")
            else "retain_confirmed"
        )
    return "accepted"


def parent_plan(plan):
    shape("urn:pdx:draft:er003:parent:plan:3", plan)
    require(
        plan["plan_digest"]
        == digest({k: v for k, v in plan.items() if k != "plan_digest"}),
        "OPERATION_BINDING_MISMATCH",
    )
    steps = plan["steps"]
    by_id = {s["workflow_step_id"]: s for s in steps}
    require(len(by_id) == len(steps), "REQUEST_INVALID")
    visited = set()
    visiting = set()
    subjects = set()
    approvals = set()

    def visit(key):
        require(key in by_id and key not in visiting, "REQUEST_INVALID")
        if key in visited:
            return
        visiting.add(key)
        for dep in by_id[key]["depends_on"]:
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for step in steps:
        visit(step["workflow_step_id"])
        b = step.get("external_operation_binding")
        if b:
            require(
                step["step_kind"] == "dispatch"
                and step["operation_digest"] == b["operation_digest"],
                "OPERATION_BINDING_MISMATCH",
            )
            subject = (b["authority_id"], b["tenant_id"], b["operation_subject_id"])
            approval = (
                b["authority_id"],
                b["tenant_id"],
                b["issuer_id"],
                b["authorization_id"],
            )
            require(
                subject not in subjects and approval not in approvals,
                "AUTHORIZATION_ALREADY_USED",
            )
            subjects.add(subject)
            approvals.add(approval)
    for edge in plan["artifact_edges"]:
        require(
            edge["producer_step_id"] in by_id and edge["consumer_step_id"] in by_id,
            "REQUEST_INVALID",
        )
        if edge["artifact_role"] == "external_operation_receipt":
            require(
                "external_operation_binding" in by_id[edge["producer_step_id"]],
                "OPERATION_BINDING_MISMATCH",
            )
    require(
        len(subjects) <= plan["budgets"]["max_external_operations"],
        "RECOVERY_BUDGET_EXHAUSTED",
    )


def route_mapping(mapping, expected):
    shape("urn:pdx:contracts:engine:routes:1", mapping)
    actual = {r["operation"]: r for r in mapping["routes"]}
    require(
        len(actual) == len(mapping["routes"])
        and actual == {r["operation"]: r for r in expected["routes"]},
        "REQUEST_INVALID",
    )
    require(mapping["errors"] == expected["errors"], "REQUEST_INVALID")


def parent_receipt(receipt, plan, context):
    shape("urn:pdx:draft:er003:parent:receipt:3", receipt)
    parent_plan(plan)
    require(
        receipt["workflow_job_id"] == plan["workflow_job_id"]
        and receipt["plan_digest"] == plan["plan_digest"],
        "OPERATION_BINDING_MISMATCH",
    )
    by_id = {s["workflow_step_id"]: s for s in plan["steps"]}
    seen = set()
    for row in receipt["step_receipts"]:
        key = row["workflow_step_id"]
        require(key in by_id and key not in seen, "REQUEST_INVALID")
        seen.add(key)
        step = by_id[key]
        require(row["step_kind"] == step["step_kind"], "OPERATION_BINDING_MISMATCH")
        if "external_operation_binding" not in step:
            continue
        require(
            row.get("receipt_profile") == "external_operation",
            "OPERATION_BINDING_MISMATCH",
        )
        if not row["operation_allocated"]:
            require(row["status"] != "succeeded", "OPERATION_BINDING_MISMATCH")
            continue
        art = row["external_operation_receipt_artifact"]
        artifacts(art, context)
        operation = parse(context["authorized_artifact_bytes"][art["artifact_id"]])
        supporting("receipt", operation)
        binding = step["external_operation_binding"]
        for field in (
            "authority_id",
            "tenant_id",
            "operation_subject_id",
            "operation_digest",
            "provider_profile_digest",
            "authorization_id",
            "issuer_id",
        ):
            require(operation[field] == binding[field], "OPERATION_BINDING_MISMATCH")
        if row["status"] == "succeeded" or receipt["status"] == "completed":
            require(
                operation["provider_outcome"] == "confirmed_succeeded"
                and not operation["reconciliation_required"],
                "OPERATION_BINDING_MISMATCH",
            )
    if receipt["status"] == "completed":
        require(
            seen == set(by_id)
            and all(s["status"] == "succeeded" for s in receipt["step_receipts"]),
            "OPERATION_BINDING_MISMATCH",
        )


def parent_state(state, plan):
    shape("urn:pdx:draft:er003:parent:state:3", state)
    parent_plan(plan)
    require(
        state["workflow_job_id"] == plan["workflow_job_id"]
        and state["plan_digest"] == plan["plan_digest"],
        "OPERATION_BINDING_MISMATCH",
    )
    counters = state["counters"]
    budgets = plan["budgets"]
    for counter, budget in [
        ("external_calls", "max_external_calls"),
        ("external_operations", "max_external_operations"),
        ("dispatch_attempts", "max_dispatch_attempts"),
    ]:
        require(counters[counter] <= budgets[budget], "RECOVERY_BUDGET_EXHAUSTED")
    require(
        counters["recovery_query_calls"] <= counters["external_calls"],
        "OPERATION_BINDING_MISMATCH",
    )


def supporting(kind, value, context=None):
    shape("urn:pdx:draft:er003:support:2#/$defs/" + kind, value)
    if kind == "authority_config":
        return
    if kind in (
        "projection",
        "receipt",
        "activation_response",
        "registration_response",
        "reconcile_response",
        "observation_response",
        "submit_permit_record",
        "query_claim_record",
        "step_binding",
        "operation_specification",
    ):
        if kind in ("projection", "receipt"):
            require(
                value["submit_permits"] <= 1
                and value["subject_reserved"]
                and not value["resubmission_allowed"],
                "OPERATION_BINDING_MISMATCH",
            )
            require(
                value["submission_evidence"] != "not_started"
                or value["submit_permits"] == 0,
                "OPERATION_BINDING_MISMATCH",
            )
            require(
                value["submission_evidence"] == "not_started"
                or value["submit_permits"] == 1,
                "OPERATION_BINDING_MISMATCH",
            )
            require(
                not (
                    value["provider_outcome"] in ("unknown", "pending")
                    and not value["reconciliation_required"]
                ),
                "OPERATION_BINDING_MISMATCH",
            )
            require(
                value["conflict_count"] == 0 or value["reconciliation_required"],
                "OPERATION_BINDING_MISMATCH",
            ) if kind == "projection" else None
            cases = value["manual_cases"]
            require(len({c["case_id"] for c in cases}) == len(cases), "REQUEST_INVALID")
            if kind == "receipt":
                require(
                    value["receipt_digest"]
                    == digest(
                        {k: v for k, v in value.items() if k != "receipt_digest"}
                    ),
                    "EVIDENCE_INVALID",
                )
                require(
                    value["previous_receipt_digest"] is None
                    if value["sequence"] == 1
                    else value["previous_receipt_digest"] is not None,
                    "EVIDENCE_INVALID",
                )
                if context is not None and context.get("previous_receipt"):
                    previous = context["previous_receipt"]
                    require(
                        value["previous_receipt_digest"] == previous["receipt_digest"]
                        and value["sequence"] == previous["sequence"] + 1,
                        "EVIDENCE_INVALID",
                    )
                    for key in (
                        "operation_id",
                        "operation_subject_id",
                        "operation_digest",
                        "provider_key_digest",
                        "authorization_id",
                        "issuer_id",
                        "workflow_job_id",
                        "workflow_step_id",
                        "authority_id",
                        "tenant_id",
                    ):
                        require(
                            value[key] == previous[key], "OPERATION_BINDING_MISMATCH"
                        )
                    require(
                        all(
                            value["consumed"][key] >= count
                            for key, count in previous["consumed"].items()
                        ),
                        "EVIDENCE_INVALID",
                    )
                    if previous["provider_outcome"].startswith("confirmed_"):
                        require(
                            value["provider_outcome"] == previous["provider_outcome"],
                            "OPERATION_BINDING_MISMATCH",
                        )
                    if previous["parent_terminal_receipt_artifact"] is not None:
                        require(
                            value["parent_terminal_receipt_artifact"]
                            == previous["parent_terminal_receipt_artifact"],
                            "OPERATION_BINDING_MISMATCH",
                        )
        return
    roles = {
        "provider_register": "administrator",
        "subject_register": "controller",
        "authorization_register": "issuer",
        "authorization_revoke": "issuer",
        "issuer_freshness": "issuer",
        "reconcile_request": "supervisor",
    }
    auth(value, context, roles[kind])
    artifacts(value, context)
    if kind == "provider_register":
        proven = (
            value["lookup_proven"]
            and value["lookup_proof"] is not None
            and value["query_deployment"] is not None
        )
        require(
            value["recovery_mode"] == "manual_only" or proven,
            "PROVIDER_PROFILE_UNSUPPORTED",
        )
        require(
            not value["lookup_proven"]
            or (proven and context.get("lookup_proof_verified") is True),
            "EVIDENCE_INVALID",
        )
        require(
            value["lookup_proven"] or value["lookup_proof"] is None, "EVIDENCE_INVALID"
        )
    if kind == "subject_register":
        spec = value["specification"]
        ids = [digest(a) for a in spec["evidence_artifacts"]]
        require(ids == sorted(set(ids)), "EVIDENCE_INVALID")
        require(
            spec["provider_profile_digest"] == context["provider_profile_digest"],
            "OPERATION_BINDING_MISMATCH",
        )
        require(
            context.get("provider_profile") is not None, "OPERATION_BINDING_MISMATCH"
        )
        for key in (
            "provider_profile_id",
            "provider_profile_revision",
            "account_alias",
            "environment",
            "executor_identity_digest",
            "execution_policy_digest",
        ):
            require(
                spec[key] == context["provider_profile"][key],
                "OPERATION_BINDING_MISMATCH",
            )
        require(
            context.get("payload_schema") is not None
            and digest(context["payload_schema"]) == spec["payload_schema_digest"],
            "EVIDENCE_INVALID",
        )
        require(
            spec["payload_schema_id"] == context.get("payload_schema_id"),
            "EVIDENCE_INVALID",
        )
        raw = context["authorized_artifact_bytes"][
            spec["payload_artifact"]["artifact_id"]
        ]
        require(
            Draft202012Validator(context["payload_schema"]).is_valid(parse(raw)),
            "EVIDENCE_INVALID",
        )
    if kind == "authorization_register":
        require(value["issuer_id"] == context["issuer_id"], "AUTHORITY_FORBIDDEN")
        require(
            timestamp(value["issued_at"])
            <= timestamp(context["now"])
            < timestamp(value["expires_at"]),
            "AUTHORIZATION_EXPIRED",
        )
        require(
            value["issuer_epoch"] == context["issuer_epoch"], "AUTHORIZATION_REVOKED"
        )
        require(context.get("subject") is not None, "OPERATION_BINDING_MISMATCH")
        for key in (
            "operation_subject_id",
            "operation_digest",
            "execution_policy_digest",
        ):
            require(value[key] == context["subject"][key], "OPERATION_BINDING_MISMATCH")
    if kind == "authorization_revoke":
        require(
            value["issuer_id"] == context["issuer_id"]
            and value["issuer_epoch"] > context["issuer_epoch"],
            "AUTHORIZATION_REVOKED",
        )
    if kind == "issuer_freshness":
        require(
            value["issuer_id"] == context["issuer_id"]
            and value["issuer_epoch"] >= context["issuer_epoch"],
            "AUTHORITY_FORBIDDEN",
        )
        observed, until, now = map(
            timestamp, (value["observed_at"], value["valid_until"], context["now"])
        )
        require(
            observed <= now < until and 0 < (until - observed).total_seconds() <= 30,
            "AUTHORITY_FRESHNESS_UNAVAILABLE",
        )
        require(
            observed
            >= timestamp(context.get("last_observed_at", value["observed_at"])),
            "AUTHORITY_FRESHNESS_UNAVAILABLE",
        )
    if kind == "reconcile_request":
        for key in ("operation_id", "operation_digest", "provider_profile_digest"):
            require(
                value[key] == context["operation"][key], "OPERATION_BINDING_MISMATCH"
            )
        require(
            value["expected_sequence"] == context["sequence"], "STALE_EXECUTION_CLAIM"
        )
        if context["recovery_mode"] == "manual_only":
            return "manual_required"
        require(
            context["query_calls"] < 20
            and context["query_execution_ms"] < 600000
            and context["scheduling_elapsed_seconds"] < 86400,
            "RECOVERY_BUDGET_EXHAUSTED",
        )
    return "valid"
