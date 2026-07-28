from pathlib import Path

from pdx_artifact_engine.cli.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]


def test_pif_plan_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "plan.schema.json",
        ROOT / "examples" / "plans" / "pif_workflow_plan.json",
    )
    assert errors == []


def test_deterministic_plan_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "plan.schema.json",
        ROOT / "examples" / "plans" / "pif_deterministic_plan.json",
    )
    assert errors == []


def test_freecad_plan_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "plan.schema.json",
        ROOT / "examples" / "plans" / "3d_freecad_plan.json",
    )
    assert errors == []


def test_freecad_3d_spec_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "3d_spec.schema.json",
        ROOT / "examples" / "3d" / "freecad_bottle_cap_spec.json",
    )
    assert errors == []


def test_blender_3d_spec_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "3d_spec.schema.json",
        ROOT / "examples" / "3d" / "blender_perfume_render_spec.json",
    )
    assert errors == []


def test_skill_registry_sample_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "skill_registry.schema.json",
        ROOT / "skills" / "registry.sample.json",
    )
    assert errors == []


def test_model_manifest_example_is_valid() -> None:
    errors = validate_file(
        ROOT / "schemas" / "model_manifest.schema.json",
        ROOT / "examples" / "models" / "pdx_core_1b.manifest.json",
    )
    assert errors == []
