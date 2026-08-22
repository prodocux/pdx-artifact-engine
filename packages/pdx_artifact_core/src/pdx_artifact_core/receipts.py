"""Product-neutral publication/verification receipt contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from pdx_artifact_core.validate import load_schema


class PublicationReceiptError(ValueError):
    """A publication receipt failed closed."""


def validate_publication_receipt(receipt: Mapping[str, Any]) -> list[str]:
    artifact_schema = load_schema("artifact_storage_identity.v1.schema.json")
    registry = Registry().with_resource(
        artifact_schema["$id"], Resource.from_contents(artifact_schema)
    )
    validator = Draft202012Validator(
        load_schema("publication_receipt.v1.schema.json"),
        registry=registry,
        format_checker=FormatChecker(),
    )
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(receipt), key=lambda item: list(item.path)
        )
    ]
    if errors:
        return errors
    status = receipt["status"]
    if status in {"applied", "no_op"} and receipt["observed_digest"] != receipt["expected_digest"]:
        errors.append(f"observed_digest: must equal expected_digest for {status}")
    if status == "conflict" and receipt["observed_digest"] == receipt["expected_digest"]:
        errors.append("observed_digest: conflict must differ from expected_digest")
    return errors


def create_publication_receipt(
    *,
    receipt_id: str,
    operation_id: str,
    target_id: str,
    request_id: str,
    idempotency_key: str,
    status: str,
    expected_digest: str,
    verifier_id: str,
    verifier_version: str,
    recorded_at: str,
    before_digest: str | None = None,
    observed_digest: str | None = None,
    artifacts: list[Mapping[str, Any]] | None = None,
    detail: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": "pdx_publication_receipt_v1",
        "receipt_id": receipt_id,
        "operation_id": operation_id,
        "target_id": target_id,
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "status": status,
        "expected_digest": expected_digest,
        "verifier_id": verifier_id,
        "verifier_version": verifier_version,
        "recorded_at": recorded_at,
    }
    if before_digest is not None:
        receipt["before_digest"] = before_digest
    if observed_digest is not None:
        receipt["observed_digest"] = observed_digest
    if artifacts is not None:
        receipt["artifacts"] = deepcopy([dict(item) for item in artifacts])
    if detail is not None:
        receipt["detail"] = deepcopy(dict(detail))
    if error is not None:
        receipt["error"] = deepcopy(dict(error))
    errors = validate_publication_receipt(receipt)
    if errors:
        raise PublicationReceiptError(
            "invalid publication receipt:\n" + "\n".join(errors)
        )
    return receipt
