# FreeCAD Skill Spec

## Purpose

Generate parametric CAD artifacts from a `pdx_3d_spec_v0` input.

## Best For

- dimensioned parts
- mechanical models
- 3D-printable objects
- STEP/STL exports
- geometry checks

## Input

`schemas/3d_spec.schema.json` with:

- `engine = "freecad"`
- explicit units
- object parameters
- constraints
- output formats

## Output

Artifact manifest containing:

- `.FCStd` source file
- `.STEP` and/or `.STL` exports
- geometry verification report
- warnings for impossible or ambiguous constraints

## Planned Verification

- file exists
- mesh export exists
- bounding box check
- manifold/watertight check where available
- minimum wall thickness advisory
- units recorded

