from __future__ import annotations

from copy import deepcopy

import pytest
from pdx_artifact_core import (
    ProvenanceError,
    create_provenance_bundle,
    validate_provenance_bundle,
)


def _bundle() -> dict:
    return create_provenance_bundle(
        bundle_id="prov:run-001",
        source_run_id="run-001",
        generated_at="2026-09-15T10:00:00+00:00",
        entities=[{"id": "artifact:input", "type": "artifact", "digest": "a" * 64}],
        activities=[{"id": "step:render", "type": "engine_step"}],
        agents=[{"id": "adapter:office", "type": "software_agent"}],
        relations=[
            {"type": "used", "subject_id": "step:render", "object_id": "artifact:input"},
            {"type": "wasAssociatedWith", "subject_id": "step:render", "object_id": "adapter:office"},
        ],
    )


def test_provenance_bundle_is_digest_bound_and_reference_complete() -> None:
    bundle = _bundle()
    assert validate_provenance_bundle(bundle) == []
    changed = deepcopy(bundle)
    changed["entities"][0]["digest"] = "b" * 64
    assert validate_provenance_bundle(changed) == [
        "bundle_digest: does not match canonical bundle content"
    ]


def test_provenance_bundle_rejects_unknown_relation_node() -> None:
    with pytest.raises(ProvenanceError, match="references an unknown node"):
        create_provenance_bundle(
            bundle_id="prov:run-002",
            source_run_id="run-002",
            generated_at="2026-09-15T10:00:00+00:00",
            entities=[],
            activities=[{"id": "step:one", "type": "engine_step"}],
            agents=[],
            relations=[
                {"type": "used", "subject_id": "step:one", "object_id": "artifact:missing"}
            ],
        )
