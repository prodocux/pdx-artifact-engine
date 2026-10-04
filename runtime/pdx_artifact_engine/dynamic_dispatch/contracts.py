"""Validation for packaged governed dynamic-dispatch contracts."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

PACKAGES = (
    "pdx_artifact_engine.contracts.dynamic_dispatch",
    "pdx_artifact_engine.contracts.runtime_provider_workflow",
)


def _schemas() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for package in PACKAGES:
        for entry in resources.files(package).iterdir():
            if entry.name.endswith(".schema.json"):
                result[entry.name] = json.loads(entry.read_text(encoding="utf-8"))
    return result


def validate(schema_name: str, value: dict[str, Any]) -> None:
    schemas = _schemas()
    registry = Registry()
    for name, schema in schemas.items():
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(name, resource)
        registry = registry.with_resource(schema["$id"], resource)
    validator = Draft202012Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    )
    error = next(iter(validator.iter_errors(value)), None)
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        raise ValueError(f"{path}: {error.message}")
