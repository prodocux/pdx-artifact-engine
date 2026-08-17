"""Validation helpers for opaque artifact storage identities."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_core.validate import load_schema


def validate_artifact_storage_identity(identity: dict[str, Any]) -> list[str]:
    """Validate a product-neutral, non-credentialed artifact identity."""

    validator = Draft202012Validator(
        load_schema("artifact_storage_identity.v1.schema.json"),
        format_checker=FormatChecker(),
    )
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(validator.iter_errors(identity), key=lambda item: list(item.path))
    ]
