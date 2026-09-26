"""Fail-closed validation for Kernel continuation responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

_SCHEMAS = {
    "prodocux_pdf_continuable_projection_v1": "prodocux_pdf_continuable_projection_v1.json",
    "prodocux_csv_continuable_projection_v1": "prodocux_csv_continuable_projection_v1.json",
    "prodocux_xlsx_continuable_projection_v1": "prodocux_xlsx_continuable_projection_v1.json",
    "prodocux_pptx_continuable_projection_v1": "prodocux_pptx_continuable_projection_v1.json",
    "prodocux_image_tile_projection_v1": "prodocux_image_tile_projection_v1.json",
}


def validate_kernel_projection(value: Mapping[str, Any]) -> None:
    """Validate the exact Kernel schema and its cross-field semantics."""
    schema_id = value.get("schema_version")
    filename = _SCHEMAS.get(schema_id)
    if filename is None:
        raise ValueError("Kernel continuation schema is not supported")
    try:
        schema = json.loads(
            files("prodocux_kernel.schemas")
            .joinpath(filename)
            .read_text(encoding="utf-8")
        )
        from prodocux_kernel.intake import validate_continuable_projection
    except (ImportError, FileNotFoundError) as exc:
        raise RuntimeError(
            "compatible ProDocuX Kernel contract package is required"
        ) from exc
    Draft202012Validator(schema).validate(dict(value))
    validate_continuable_projection(value)


def validate_kernel_projection_capabilities(value: Mapping[str, Any]) -> None:
    try:
        schema = json.loads(
            files("prodocux_kernel.schemas")
            .joinpath("prodocux_projection_capabilities_v1.json")
            .read_text(encoding="utf-8")
        )
    except (ImportError, FileNotFoundError) as exc:
        raise RuntimeError(
            "compatible ProDocuX Kernel contract package is required"
        ) from exc
    Draft202012Validator(schema).validate(dict(value))
