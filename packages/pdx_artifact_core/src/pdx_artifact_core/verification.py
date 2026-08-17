"""Product-neutral verifier result validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_STATUSES = {"pass", "fail", "review"}


def validate_verifier_result(result: Mapping[str, Any]) -> list[str]:
    """Return stable validation errors for ``verifier_result_v1``."""
    errors: list[str] = []
    required = (
        "verifier_id",
        "version",
        "status",
        "reason_codes",
        "rule_set_id",
        "rule_set_version",
        "rule_digest",
        "evidence_ids",
        "timestamp",
    )
    for field in required:
        if field not in result:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors
    if result["status"] not in _STATUSES:
        errors.append("status must be pass, fail, or review")
    for field in ("verifier_id", "version", "rule_set_id", "rule_set_version"):
        if not isinstance(result[field], str) or not result[field]:
            errors.append(f"{field} must be a non-empty string")
    if not isinstance(result["rule_digest"], str) or not _DIGEST.fullmatch(
        result["rule_digest"]
    ):
        errors.append("rule_digest must be a lowercase sha256")
    for field in ("reason_codes", "evidence_ids"):
        value = result[field]
        if (
            not isinstance(value, list)
            or len(value) > 50
            or len(value) != len(set(value))
        ):
            errors.append(f"{field} must be a unique list with at most 50 items")
        elif not all(isinstance(item, str) and item for item in value):
            errors.append(f"{field} entries must be non-empty strings")
    details = result.get("details", {})
    if not isinstance(details, Mapping) or len(details) > 10:
        errors.append("details must be an object with at most 10 fields")
    elif not all(
        value is None or isinstance(value, (str, int, float, bool))
        for value in details.values()
    ):
        errors.append("details values must be scalar")
    try:
        parsed = datetime.fromisoformat(str(result["timestamp"]))
        if parsed.tzinfo is None:
            raise ValueError
    except ValueError:
        errors.append("timestamp must be an ISO-8601 date-time with timezone")
    allowed = set(required) | {"details"}
    if extra := set(result) - allowed:
        errors.append(f"unexpected fields: {sorted(extra)}")
    return errors
