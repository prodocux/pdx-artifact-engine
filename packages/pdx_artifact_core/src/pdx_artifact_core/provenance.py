"""Bounded, product-neutral provenance export with PROV-O relation names."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from pdx_artifact_core.approval import canonical_digest
from pdx_artifact_core.validate import load_schema


class ProvenanceError(ValueError):
    """A provenance bundle failed schema or relationship validation."""


def _schema_errors(bundle: Mapping[str, Any]) -> list[str]:
    validator = Draft202012Validator(
        load_schema("provenance_bundle.v1.schema.json"),
        format_checker=FormatChecker(),
    )
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(bundle), key=lambda item: list(item.path))
    ]


def validate_provenance_bundle(bundle: Mapping[str, Any]) -> list[str]:
    """Validate shape, unique identities, references, and canonical digest."""
    errors = _schema_errors(bundle)
    if errors:
        return errors
    groups = ("entities", "activities", "agents")
    ids = [str(node["id"]) for group in groups for node in bundle[group]]
    if len(ids) != len(set(ids)):
        errors.append("nodes: ids must be unique across entities, activities, and agents")
    known = set(ids)
    for index, relation in enumerate(bundle["relations"]):
        for field in ("subject_id", "object_id"):
            if relation[field] not in known:
                errors.append(f"relations/{index}/{field}: references an unknown node")
    payload = dict(bundle)
    observed = str(payload.pop("bundle_digest"))
    if canonical_digest(payload) != observed:
        errors.append("bundle_digest: does not match canonical bundle content")
    return errors


def create_provenance_bundle(
    *,
    bundle_id: str,
    source_run_id: str,
    generated_at: str,
    entities: Sequence[Mapping[str, Any]],
    activities: Sequence[Mapping[str, Any]],
    agents: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create a deterministic export; consumers may map relations to PROV-O."""
    bundle: dict[str, Any] = {
        "schema_version": "pdx_provenance_bundle_v1",
        "bundle_id": bundle_id,
        "source_run_id": source_run_id,
        "generated_at": generated_at,
        "entities": deepcopy([dict(item) for item in entities]),
        "activities": deepcopy([dict(item) for item in activities]),
        "agents": deepcopy([dict(item) for item in agents]),
        "relations": deepcopy([dict(item) for item in relations]),
    }
    bundle["bundle_digest"] = canonical_digest(bundle)
    if errors := validate_provenance_bundle(bundle):
        raise ProvenanceError("invalid provenance bundle:\n" + "\n".join(errors))
    return bundle
