"""Format-neutral state transitions for durable bounded extraction."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator

from pdx_artifact_core.approval import canonical_digest
from pdx_artifact_core.validate import load_schema


class ContinuableExtractionError(ValueError):
    """A range transition violated a durable extraction invariant."""


_VALIDATOR = Draft202012Validator(load_schema("continuable_extraction.v1.schema.json"))
_RECEIPT_VALIDATOR = Draft202012Validator(
    load_schema("continuable_extraction_receipt.v1.schema.json")
)


def validate_continuable_extraction(value: Mapping[str, Any]) -> list[str]:
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            _VALIDATOR.iter_errors(value), key=lambda item: list(item.path)
        )
    ]
    if errors:
        return errors
    ranges = value["accepted_ranges"]
    if [item["sequence"] for item in ranges] != list(range(1, len(ranges) + 1)):
        errors.append("accepted_ranges: sequence must be contiguous from one")
    consumed = value["consumed"]
    if consumed["ranges"] != len(ranges):
        errors.append("consumed/ranges: must equal accepted range count")
    for name in ("ranges", "blocks", "bytes", "retries"):
        if consumed[name] > value["limits"][name]:
            errors.append(f"consumed/{name}: exceeds limit")
    if value["state"] == "pending" and value["terminal_coverage"] is not None:
        errors.append("terminal_coverage: pending extraction cannot have terminal coverage")
    if value["capability_verified"] != (
        value["capability_authority"] == "kernel_adapter"
    ):
        errors.append(
            "capability_verified: must reflect Kernel adapter authority"
        )
    if value["state"] == "completed" and (
        not isinstance(value["terminal_coverage"], Mapping)
        or value["terminal_coverage"].get("disposition") != "complete"
    ):
        errors.append("terminal_coverage: completed extraction requires complete evidence")
    return errors


def validate_continuable_extraction_receipt(value: Mapping[str, Any]) -> list[str]:
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            _RECEIPT_VALIDATOR.iter_errors(value), key=lambda item: list(item.path)
        )
    ]
    if errors:
        return errors
    unsigned = deepcopy(dict(value))
    observed = unsigned.pop("receipt_digest")
    if canonical_digest(unsigned) != observed:
        errors.append("receipt_digest: does not match canonical receipt content")
    if value["state"] == "completed" and value["coverage"] != "complete":
        errors.append("coverage: completed receipt must be complete")
    if value["state"] != "completed" and value["coverage"] == "complete":
        errors.append("coverage: non-completed receipt cannot be complete")
    terminal_omissions = {
        "CANCELLED": "cancelled_before_completion",
        "TIME_LIMIT": "time_limit_exhausted",
        "RETRY_BUDGET_EXHAUSTED": "retry_budget_exhausted",
        "SOURCE_TOO_LARGE": "source_too_large",
    }
    natural_terminal_reasons = {"INCOMPLETE_PROJECTION", "UNSUPPORTED_PROJECTION"}
    if (
        value["state"] != "completed"
        and value["terminal_reason"] not in natural_terminal_reasons
    ):
        required = terminal_omissions.get(value["terminal_reason"], "unaccepted_ranges")
        if required not in value["omissions"]:
            errors.append(
                f"omissions: terminal reason requires {required}"
            )
    return errors


def create_continuable_extraction(
    *,
    operation_id: str,
    source_artifact_digest: str,
    source_sha256: str,
    media_type: str,
    parser_contract_name: str,
    parser_contract_version: str,
    capability_digest: str,
    capability_authority: str = "caller_assertion",
    capability_verified: bool = False,
    first_range: Mapping[str, Any],
    limits: Mapping[str, int],
) -> dict[str, Any]:
    result = {
        "schema_version": "pdx_continuable_extraction_v1",
        "operation_id": operation_id,
        "source_artifact_digest": source_artifact_digest,
        "source_sha256": source_sha256,
        "media_type": media_type,
        "parser_contract": {
            "name": parser_contract_name,
            "version": parser_contract_version,
        },
        "capability_digest": capability_digest,
        "capability_authority": capability_authority,
        "capability_verified": capability_verified,
        "state": "pending",
        "revision": 0,
        "next_range_descriptor": deepcopy(dict(first_range)),
        "next_range_digest": canonical_digest(first_range),
        "accepted_ranges": [],
        "aggregate_artifact_digest": canonical_digest({"artifacts": []}),
        "coverage_accumulator": {
            "disposition": "complete",
            "omissions": [],
            "ocr_disposition": "not_evaluated",
        },
        "terminal_coverage": None,
        "consumed": {"ranges": 0, "blocks": 0, "bytes": 0, "retries": 0},
        "limits": dict(limits),
    }
    errors = validate_continuable_extraction(result)
    if errors:
        raise ContinuableExtractionError(
            "invalid extraction state:\n" + "\n".join(errors)
        )
    return result


def accept_extraction_range(
    state: Mapping[str, Any],
    *,
    expected_revision: int,
    idempotency_key: str,
    request_range: Mapping[str, Any],
    result_artifact_digest: str,
    result_payload_digest: str,
    returned_blocks: int,
    returned_bytes: int,
    next_range: Mapping[str, Any] | None,
    response_range: Mapping[str, Any] | None = None,
    coverage_disposition: str | None = None,
    omissions: list[str] | tuple[str, ...] = (),
    semantic_validation_digest: str | None = None,
    ocr_disposition: str | None = None,
) -> dict[str, Any]:
    errors = validate_continuable_extraction(state)
    if errors:
        raise ContinuableExtractionError(
            "invalid extraction state:\n" + "\n".join(errors)
        )
    request_digest = canonical_digest(request_range)
    response_range_digest = canonical_digest(response_range or request_range)
    disposition = coverage_disposition or (
        "partial_known" if next_range is not None else "partial_unknown"
    )
    omission_list = list(omissions)
    record_identity = (
        request_digest,
        result_artifact_digest,
        result_payload_digest,
        response_range_digest,
        disposition,
        canonical_digest({"omissions": omission_list}),
        semantic_validation_digest,
    )
    for record in state["accepted_ranges"]:
        if record["idempotency_key"] == idempotency_key:
            existing = (
                record["request_range_digest"],
                record["result_artifact_digest"],
                record["result_payload_digest"],
                record["response_range_digest"],
                record["coverage_disposition"],
                canonical_digest({"omissions": record["omissions"]}),
                record["semantic_validation_digest"],
            )
            if existing != record_identity:
                raise ContinuableExtractionError(
                    "idempotency key conflicts with accepted range"
                )
            return deepcopy(dict(state))
    if state["state"] != "pending":
        raise ContinuableExtractionError("terminal extraction rejects range updates")
    if state["revision"] != expected_revision:
        raise ContinuableExtractionError("extraction revision conflict")
    if request_digest != state["next_range_digest"]:
        raise ContinuableExtractionError("range is not the expected next descriptor")
    if disposition == "complete":
        if next_range is not None or omission_list or semantic_validation_digest is None:
            raise ContinuableExtractionError(
                "complete coverage requires validated terminal Kernel evidence"
            )
    elif disposition not in {"partial_known", "partial_unknown", "unsupported"}:
        raise ContinuableExtractionError("unsupported coverage disposition")
    if next_range is not None and disposition == "complete":
        raise ContinuableExtractionError("complete coverage cannot continue")
    result = deepcopy(dict(state))
    next_digest = canonical_digest(next_range) if next_range is not None else None
    result["accepted_ranges"].append(
        {
            "sequence": len(result["accepted_ranges"]) + 1,
            "idempotency_key": idempotency_key,
            "request_range_digest": request_digest,
            "result_artifact_digest": result_artifact_digest,
            "result_payload_digest": result_payload_digest,
            "response_range_digest": response_range_digest,
            "coverage_disposition": disposition,
            "omissions": omission_list,
            "semantic_validation_digest": semantic_validation_digest,
            "ocr_disposition": ocr_disposition,
            "returned_blocks": returned_blocks,
            "returned_bytes": returned_bytes,
            "next_range_digest": next_digest,
            "terminal": next_range is None,
        }
    )
    result["revision"] += 1
    result["consumed"]["ranges"] += 1
    result["consumed"]["blocks"] += returned_blocks
    result["consumed"]["bytes"] += returned_bytes
    result["aggregate_artifact_digest"] = canonical_digest(
        {
            "previous": state["aggregate_artifact_digest"],
            "sequence": len(result["accepted_ranges"]),
            "artifact": result_artifact_digest,
            "payload": result_payload_digest,
        }
    )
    accumulated = result["coverage_accumulator"]
    accumulated["omissions"] = sorted(
        set(accumulated["omissions"]) | set(omission_list)
    )
    if disposition == "unsupported":
        accumulated["disposition"] = "unsupported"
    elif disposition == "partial_unknown":
        accumulated["disposition"] = "partial_unknown"
    elif disposition == "partial_known" and next_range is None:
        accumulated["disposition"] = "partial_known"
    ocr_priority = {
        "not_evaluated": 0,
        "performed_complete": 1,
        "performed_partial": 2,
        "not_performed": 3,
        "unavailable": 4,
    }
    if ocr_disposition is not None:
        if ocr_disposition not in ocr_priority:
            raise ContinuableExtractionError("unsupported OCR disposition")
        if ocr_priority[ocr_disposition] > ocr_priority[accumulated["ocr_disposition"]]:
            accumulated["ocr_disposition"] = ocr_disposition
    if next_range is None:
        result["terminal_coverage"] = deepcopy(accumulated)
        if disposition == "complete" and accumulated["disposition"] == "complete":
            result["state"] = "completed"
            result["terminal_reason"] = "COMPLETED"
        else:
            result["state"] = "failed"
            result["terminal_reason"] = (
                "UNSUPPORTED_PROJECTION"
                if accumulated["disposition"] == "unsupported"
                else "INCOMPLETE_PROJECTION"
            )
    result["next_range_descriptor"] = (
        deepcopy(dict(next_range)) if next_range is not None else None
    )
    result["next_range_digest"] = next_digest
    errors = validate_continuable_extraction(result)
    if errors:
        raise ContinuableExtractionError(
            "invalid range transition:\n" + "\n".join(errors)
        )
    return result
