# Blender Skill Spec

## Purpose

Generate visual 3D scenes, renders, and animations from a `pdx_3d_spec_v0`
input.

## Best For

- product rendering
- packaging mockups
- explainer visuals
- camera animation
- material and lighting scenes
- PNG/MP4 outputs

## Input

`schemas/3d_spec.schema.json` with:

- `engine = "blender"`
- scene objects
- materials
- camera setup
- optional animation plan
- output formats

## Output

Artifact manifest containing:

- `.blend` source file
- rendered `.png` and/or `.mp4`
- render settings
- verification screenshots or frame checks

## Planned Verification

- non-empty scene
- camera sees target objects
- render file exists
- frame count and duration match requested values
- basic pixel nonblank check
- no missing texture references

