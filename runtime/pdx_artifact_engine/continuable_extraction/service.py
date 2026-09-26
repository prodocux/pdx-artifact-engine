"""Transactional service for durable continuable extraction."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pdx_artifact_core import (
    ContinuableExtractionError,
    accept_extraction_range,
    canonical_digest,
    validate_continuable_extraction,
    validate_continuable_extraction_receipt,
)

from pdx_artifact_engine.continuable_extraction.store import (
    ContinuableExtractionStore,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ContinuableExtractionError("stored extraction value is not an object")
    return loaded


_TERMINAL_OMISSIONS = {
    "CANCELLED": "cancelled_before_completion",
    "TIME_LIMIT": "time_limit_exhausted",
    "RETRY_BUDGET_EXHAUSTED": "retry_budget_exhausted",
    "SOURCE_TOO_LARGE": "source_too_large",
}


def _terminal_coverage(
    state: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    coverage = deepcopy(
        state.get("coverage_accumulator")
        or {
            "disposition": "complete",
            "omissions": [],
            "ocr_disposition": "not_evaluated",
        }
    )
    coverage["disposition"] = "partial_unknown"
    omission = _TERMINAL_OMISSIONS.get(reason, "unaccepted_ranges")
    coverage["omissions"] = sorted(set(coverage["omissions"]) | {omission})
    return coverage


class ContinuableExtractionService:
    def __init__(
        self,
        store: ContinuableExtractionStore,
        *,
        kernel: Any | None = None,
        projection_validator: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.store = store
        self.kernel = kernel
        self.projection_validator = projection_validator

    def execute_next(
        self,
        operation_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        format_name: str,
        document_b64: str,
        document_filename: str,
        range_limit: int,
        tile_edge: int | None = None,
        ocr_requested: bool = False,
    ) -> dict[str, Any]:
        """Call Kernel, validate its response, persist it, then accept one range."""
        if self.kernel is None or self.projection_validator is None:
            raise ContinuableExtractionError(
                "verified Kernel projection runner is not configured"
            )
        current = self.get(operation_id)
        if current["state"] != "pending" or current["revision"] != expected_revision:
            raise ContinuableExtractionError("extraction revision conflict")
        request_descriptor = current["next_range_descriptor"]
        try:
            response = self.kernel.continue_projection(
                format_name=format_name,
                document_b64=document_b64,
                document_filename=document_filename,
                continuation_descriptor=request_descriptor.get("continuation_descriptor"),
                range_limit=range_limit,
                tile_edge=tile_edge,
                ocr_requested=ocr_requested,
            )
        except Exception as exc:
            if getattr(exc, "status", None) == 413:
                return self.fail(
                    operation_id,
                    expected_revision=expected_revision,
                    reason="SOURCE_TOO_LARGE",
                )
            raise
        try:
            self.projection_validator(response)
        except Exception as exc:
            raise ContinuableExtractionError(
                "Kernel continuation response failed schema or semantic validation"
            ) from exc
        if response.get("source_sha256") != current["source_sha256"]:
            raise ContinuableExtractionError("Kernel response source digest mismatch")
        contract = response.get("parser_contract", {})
        if contract != current["parser_contract"]:
            raise ContinuableExtractionError("Kernel response parser contract mismatch")
        payload = _json(response).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        identity = self.kernel.store_derived(
            output_name=f"{operation_id}-{expected_revision + 1}.projection.json",
            content_b64=base64.b64encode(payload).decode("ascii"),
            media_type="application/json",
            sha256=payload_sha256,
        )
        if (
            identity.get("sha256") != payload_sha256
            or identity.get("size_bytes") != len(payload)
            or identity.get("media_type") != "application/json"
        ):
            raise ContinuableExtractionError("Kernel artifact identity mismatch")
        counts = response["counts"]
        returned_blocks = next(
            (
                counts[name]
                for name in (
                    "returned_blocks",
                    "returned_pages",
                    "returned_rows",
                    "returned_slides",
                    "returned_tiles",
                )
                if name in counts
            ),
            0,
        )
        coverage = response["coverage"]
        ocr = response.get("ocr")
        next_descriptor = response.get("next_cursor")
        if next_descriptor is not None:
            next_descriptor = {"continuation_descriptor": next_descriptor}
        semantic_digest = canonical_digest(
            {
                "validator": "kernel_schema_and_semantic_v1",
                "payload_digest": payload_sha256,
            }
        )
        return self.accept_range(
            operation_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_range=request_descriptor,
            result_artifact_digest=identity["sha256"],
            result_payload_digest=payload_sha256,
            returned_blocks=returned_blocks,
            returned_bytes=len(payload),
            next_range=next_descriptor,
            response_range=response["range"],
            coverage_disposition=coverage["disposition"],
            omissions=coverage["omitted_content_classes"],
            semantic_validation_digest=semantic_digest,
            ocr_disposition=ocr.get("disposition") if isinstance(ocr, Mapping) else None,
        )

    def create(self, state: Mapping[str, Any]) -> dict[str, Any]:
        errors = validate_continuable_extraction(state)
        if errors:
            raise ContinuableExtractionError(
                "invalid extraction state:\n" + "\n".join(errors)
            )
        if state["revision"] != 0 or state["state"] != "pending":
            raise ContinuableExtractionError(
                "new extraction must be pending at revision zero"
            )
        document = deepcopy(dict(state))
        digest = canonical_digest(document)
        now = _now()
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT creation_digest, state_json FROM continuable_extractions WHERE operation_id = ?",
                (document["operation_id"],),
            ).fetchone()
            if row is not None:
                if row["creation_digest"] != digest:
                    raise ContinuableExtractionError(
                        "operation id conflicts with existing extraction"
                    )
                return _load(row["state_json"])
            connection.execute(
                """INSERT INTO continuable_extractions
                   (operation_id, creation_digest, revision, state, state_json, created_at, updated_at)
                   VALUES (?, ?, 0, 'pending', ?, ?, ?)""",
                (document["operation_id"], digest, _json(document), now, now),
            )
        return document

    def create_from_kernel(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Create using the validated live Kernel capability document as authority."""
        if self.kernel is None:
            raise ContinuableExtractionError("Kernel adapter is not configured")
        if "capability_digest" in request:
            raise ContinuableExtractionError(
                "capability_digest is Engine-derived and must not be supplied"
            )
        try:
            capabilities = self.kernel.projection_capabilities()
            from pdx_adapter_prodocux.verified_projection import (
                validate_kernel_projection_capabilities,
            )

            validate_kernel_projection_capabilities(capabilities)
        except Exception as exc:
            raise ContinuableExtractionError(
                "Kernel capability document failed validation"
            ) from exc
        document = deepcopy(dict(request))
        document["capability_digest"] = canonical_digest(capabilities)
        document["capability_authority"] = "kernel_adapter"
        document["capability_verified"] = True
        return self.create(document)

    def get(self, operation_id: str) -> dict[str, Any]:
        with self.store.read_transaction() as connection:
            row = connection.execute(
                "SELECT state_json FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise ContinuableExtractionError("extraction operation not found")
        return _load(row["state_json"])

    def stage_range(
        self,
        operation_id: str,
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
    ) -> None:
        transition = {
            "request_range": deepcopy(dict(request_range)),
            "result_artifact_digest": result_artifact_digest,
            "result_payload_digest": result_payload_digest,
            "returned_blocks": returned_blocks,
            "returned_bytes": returned_bytes,
            "next_range": deepcopy(dict(next_range))
            if next_range is not None
            else None,
            "response_range": deepcopy(dict(response_range))
            if response_range is not None
            else None,
            "coverage_disposition": coverage_disposition,
            "omissions": list(omissions),
            "semantic_validation_digest": semantic_validation_digest,
            "ocr_disposition": ocr_disposition,
        }
        digest = canonical_digest(transition)
        with self.store.transaction() as connection:
            operation = connection.execute(
                "SELECT 1 FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if operation is None:
                raise ContinuableExtractionError("extraction operation not found")
            row = connection.execute(
                """SELECT expected_revision, transition_digest
                   FROM continuable_extraction_staged_ranges
                   WHERE operation_id = ? AND idempotency_key = ?""",
                (operation_id, idempotency_key),
            ).fetchone()
            if row is not None:
                if (
                    row["expected_revision"] != expected_revision
                    or row["transition_digest"] != digest
                ):
                    raise ContinuableExtractionError(
                        "idempotency key conflicts with staged range"
                    )
                return
            connection.execute(
                """INSERT INTO continuable_extraction_staged_ranges
                   (operation_id, idempotency_key, request_digest, expected_revision,
                    transition_json, transition_digest, status, staged_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'staged', ?)""",
                (
                    operation_id,
                    idempotency_key,
                    canonical_digest(request_range),
                    expected_revision,
                    _json(transition),
                    digest,
                    _now(),
                ),
            )

    def accept_staged(self, operation_id: str, idempotency_key: str) -> dict[str, Any]:
        with self.store.transaction() as connection:
            operation = connection.execute(
                "SELECT revision, state_json FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            staged = connection.execute(
                """SELECT expected_revision, transition_json, status
                   FROM continuable_extraction_staged_ranges
                   WHERE operation_id = ? AND idempotency_key = ?""",
                (operation_id, idempotency_key),
            ).fetchone()
            if operation is None or staged is None:
                raise ContinuableExtractionError(
                    "extraction operation or staged range not found"
                )
            current = _load(operation["state_json"])
            transition = _load(staged["transition_json"])
            if staged["status"] == "accepted":
                return current
            updated = accept_extraction_range(
                current,
                expected_revision=staged["expected_revision"],
                idempotency_key=idempotency_key,
                **transition,
            )
            receipt = self._receipt(updated) if updated["state"] != "pending" else None
            changed = connection.execute(
                """UPDATE continuable_extractions
                   SET revision = ?, state = ?, state_json = ?, receipt_json = ?, updated_at = ?
                   WHERE operation_id = ? AND revision = ? AND state = 'pending'""",
                (
                    updated["revision"],
                    updated["state"],
                    _json(updated),
                    _json(receipt) if receipt is not None else None,
                    _now(),
                    operation_id,
                    operation["revision"],
                ),
            ).rowcount
            if changed != 1:
                raise ContinuableExtractionError("extraction revision conflict")
            connection.execute(
                """UPDATE continuable_extraction_staged_ranges
                   SET status = 'accepted', accepted_revision = ?
                   WHERE operation_id = ? AND idempotency_key = ? AND status = 'staged'""",
                (updated["revision"], operation_id, idempotency_key),
            )
            return updated

    def accept_range(self, operation_id: str, **values: Any) -> dict[str, Any]:
        self.stage_range(operation_id, **values)
        return self.accept_staged(operation_id, values["idempotency_key"])

    def reconcile(self, operation_id: str) -> dict[str, Any]:
        while True:
            current = self.get(operation_id)
            if current["state"] != "pending":
                return current
            with self.store.read_transaction() as connection:
                row = connection.execute(
                    """SELECT idempotency_key FROM continuable_extraction_staged_ranges
                       WHERE operation_id = ? AND status = 'staged' AND expected_revision = ?
                       ORDER BY staged_at, idempotency_key LIMIT 1""",
                    (operation_id, current["revision"]),
                ).fetchone()
            if row is None:
                return current
            self.accept_staged(operation_id, row["idempotency_key"])

    def cancel(self, operation_id: str, *, expected_revision: int) -> dict[str, Any]:
        return self._terminate(
            operation_id, expected_revision, "cancelled", "CANCELLED"
        )

    def time_out(self, operation_id: str, *, expected_revision: int) -> dict[str, Any]:
        return self._terminate(
            operation_id, expected_revision, "timed_out", "TIME_LIMIT"
        )

    def fail(
        self, operation_id: str, *, expected_revision: int, reason: str
    ) -> dict[str, Any]:
        if (
            not reason
            or not reason.replace("_", "").isalnum()
            or reason != reason.upper()
        ):
            raise ContinuableExtractionError(
                "terminal reason must be an uppercase stable code"
            )
        return self._terminate(operation_id, expected_revision, "failed", reason)

    def record_retry(
        self, operation_id: str, *, expected_revision: int
    ) -> dict[str, Any]:
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT revision, state_json FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise ContinuableExtractionError("extraction operation not found")
            current = _load(row["state_json"])
            if current["state"] != "pending":
                raise ContinuableExtractionError("terminal extraction rejects retry")
            if row["revision"] != expected_revision:
                raise ContinuableExtractionError("extraction revision conflict")
            updated = deepcopy(current)
            updated["revision"] += 1
            if updated["consumed"]["retries"] >= updated["limits"]["retries"]:
                updated["state"] = "failed"
                updated["terminal_reason"] = "RETRY_BUDGET_EXHAUSTED"
                updated["terminal_coverage"] = _terminal_coverage(
                    updated, "RETRY_BUDGET_EXHAUSTED"
                )
                updated["next_range_descriptor"] = None
                updated["next_range_digest"] = None
            else:
                updated["consumed"]["retries"] += 1
            errors = validate_continuable_extraction(updated)
            if errors:
                raise ContinuableExtractionError(
                    "invalid retry transition:\n" + "\n".join(errors)
                )
            receipt = self._receipt(updated) if updated["state"] != "pending" else None
            changed = connection.execute(
                """UPDATE continuable_extractions
                   SET revision = ?, state = ?, state_json = ?, receipt_json = ?, updated_at = ?
                   WHERE operation_id = ? AND revision = ? AND state = 'pending'""",
                (
                    updated["revision"],
                    updated["state"],
                    _json(updated),
                    _json(receipt) if receipt is not None else None,
                    _now(),
                    operation_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise ContinuableExtractionError("extraction revision conflict")
            return updated

    def _terminate(
        self, operation_id: str, expected_revision: int, state: str, reason: str
    ) -> dict[str, Any]:
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT revision, state_json FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise ContinuableExtractionError("extraction operation not found")
            current = _load(row["state_json"])
            if current["state"] != "pending":
                if current["state"] == state:
                    return current
                raise ContinuableExtractionError(
                    "terminal extraction rejects state transition"
                )
            if row["revision"] != expected_revision:
                raise ContinuableExtractionError("extraction revision conflict")
            updated = deepcopy(current)
            updated["revision"] += 1
            updated["state"] = state
            updated["terminal_reason"] = reason
            updated["terminal_coverage"] = _terminal_coverage(updated, reason)
            updated["next_range_descriptor"] = None
            updated["next_range_digest"] = None
            errors = validate_continuable_extraction(updated)
            if errors:
                raise ContinuableExtractionError(
                    "invalid terminal transition:\n" + "\n".join(errors)
                )
            receipt = self._receipt(updated)
            changed = connection.execute(
                """UPDATE continuable_extractions
                   SET revision = ?, state = ?, state_json = ?, receipt_json = ?, updated_at = ?
                   WHERE operation_id = ? AND revision = ? AND state = 'pending'""",
                (
                    updated["revision"],
                    state,
                    _json(updated),
                    _json(receipt),
                    _now(),
                    operation_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise ContinuableExtractionError("extraction revision conflict")
            return updated

    def receipt(self, operation_id: str) -> dict[str, Any]:
        with self.store.read_transaction() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM continuable_extractions WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise ContinuableExtractionError("extraction operation not found")
        if row["receipt_json"] is None:
            raise ContinuableExtractionError(
                "pending extraction has no terminal receipt"
            )
        return _load(row["receipt_json"])

    @staticmethod
    def _receipt(state: Mapping[str, Any]) -> dict[str, Any]:
        terminal = state.get("terminal_coverage") or {
            "disposition": "partial_unknown",
            "omissions": ["unaccepted_ranges"],
            "ocr_disposition": "not_evaluated",
        }
        receipt = {
            "schema_version": "pdx_continuable_extraction_receipt_v1",
            "operation_id": state["operation_id"],
            "source_artifact_digest": state["source_artifact_digest"],
            "source_sha256": state["source_sha256"],
            "media_type": state["media_type"],
            "parser_contract": deepcopy(state["parser_contract"]),
            "capability_digest": state["capability_digest"],
            "capability_authority": state["capability_authority"],
            "capability_verified": state["capability_verified"],
            "state": state["state"],
            "terminal_reason": state["terminal_reason"],
            "coverage": terminal["disposition"],
            "omissions": terminal["omissions"],
            "ocr_disposition": terminal["ocr_disposition"],
            "final_revision": state["revision"],
            "accepted_ranges_digest": canonical_digest(
                {"ranges": state["accepted_ranges"]}
            ),
            "aggregate_artifact_digest": state["aggregate_artifact_digest"],
            "consumed": deepcopy(state["consumed"]),
            "limits": deepcopy(state["limits"]),
        }
        receipt["receipt_digest"] = canonical_digest(receipt)
        errors = validate_continuable_extraction_receipt(receipt)
        if errors:
            raise ContinuableExtractionError(
                "invalid terminal receipt:\n" + "\n".join(errors)
            )
        return receipt
