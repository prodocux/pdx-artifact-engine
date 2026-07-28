# Roadmap

## North Star

Build a local artifact engine that can turn intent into deliverable files on
8 GB to 16 GB machines by combining 1B-class specialist models with
deterministic skills.

## M0: Project Foundation

Goal: establish the repo, contracts, and product shape.

Status: **done for v0.1.0** (model-optional framework; no shipped weights).

Deliverables:

- Public GitHub-ready repository.
- Runtime architecture document.
- Unified skill + skill registry schemas.
- Artifact + run manifest schemas.
- Model manifest schema (weights out of band).
- ManualPlanner / RulePlanner + deterministic fixture demo.
- Kaggle implementation plan.
- Initial backlog.

Exit criteria:

- A new contributor can understand what PDX Artifact Engine is.
- A skill developer can write a compatible skill wrapper.
- Framework runs end-to-end without an LLM.
- A model developer can generate compatible traces (later milestones).

## M1: Skill Kernel Stabilization

Goal: make ProDocuX skills reliable enough to be called by a small model.

Initial skills:

- `pdf_extract`
- `doc_assemble`
- `structure_health`
- `pif_audit`
- `number_audit`
- `version_diff`
- `clause_diff`

Deliverables:

- CLI entry points.
- JSON input/output wrappers.
- Failure codes.
- Golden fixtures.
- Verification reports.
- MCP-compatible metadata.

Exit criteria:

- A PIF document workflow can be run without model intervention.
- Every step produces structured output and an audit log.

## M2: PDX-Core-1B

Goal: train the core router and planner.

Responsibilities:

- Understand user intent.
- Select the right expert or skill.
- Produce valid JSON plans.
- Ask for missing inputs.
- Interpret skill outputs.
- Trigger repair loops.
- Stop when verification is complete.

Training sources:

- ProDocuX run traces.
- Synthetic tool-routing examples.
- Failure and repair traces.
- Unsupported-action examples.

Exit criteria:

- Valid JSON rate >= 98%.
- Skill selection accuracy >= 90% on held-out tasks.
- Unsupported or unsafe requests are escalated to the user.

## M3: PDX-Doc-1B

Goal: specialize document workflows.

Responsibilities:

- Draft structured document sections.
- Suggest source maps.
- Generate review flags.
- Build evidence specs.
- Repair draft JSON after audit failures.

Exit criteria:

- Produces valid ProDocuX `drafts.json` and review structures.
- Does not fabricate sources when source material is missing.
- Improves ProDocuX PIF workflows over Core-only routing.

## M4: PDX-Code-1B and PDX-Data-1B

Goal: add software and data artifact support.

`PDX-Code-1B` responsibilities:

- Repo inspection plans.
- Small patch plans.
- Test and lint command selection.
- Error-log summarization.
- Repair proposal generation.

`PDX-Data-1B` responsibilities:

- Table normalization.
- CSV/XLSX schema inference.
- Numeric reconciliation.
- Extraction and validation specs.

Exit criteria:

- Can route basic code/data tasks to skills and verifiers.
- Produces compact, executable plans rather than verbose prose.

## M5: PDX-Media-1B

Goal: add visual and time-based artifact planning.

Responsibilities:

- Chart specs.
- Slide outlines.
- Image prompt specs.
- Storyboards.
- Video composition specs.
- Render verification requests.

Skills:

- `chart_render`
- `slide_render`
- `image_prompt_pack`
- `video_storyboard`
- `ffmpeg_compose`

Exit criteria:

- Generates specs that deterministic render tools can execute.
- Produces verification criteria for visual artifacts.

## M6: PDX-3D-1B

Goal: add CAD and 3D scene artifact planning.

`PDX-3D-1B` is a specialist under the Media/CAD family. It compiles user intent
into structured 3D specs and scripts for FreeCAD and Blender.

Responsibilities:

- Decide whether a task is CAD, scene rendering, or animation.
- Produce parametric CAD specs for FreeCAD.
- Produce scene/material/camera/animation specs for Blender.
- Generate script plans for FreeCAD Python or Blender Python.
- Request geometry and render verification.
- Keep engineering units and constraints explicit.

FreeCAD path:

- Mechanical parts.
- Parametric geometry.
- Dimensioned models.
- STEP/STL export.
- 3D-printability checks.

Blender path:

- Product renders.
- Visual scenes.
- Materials and lighting.
- Animation and camera paths.
- PNG/MP4 output.

Exit criteria:

- Can produce a valid CAD spec for a simple printable object.
- Can produce a valid Blender scene spec for a product render.
- Can route artifacts to FreeCAD or Blender skills with verification.

## M7: Low-RAM Runtime

Goal: make the expert bundle usable locally.

Modes:

- 8 GB: Core resident, specialists hot-swapped.
- 16 GB: Core plus one hot specialist.
- Server: multiple experts resident with queueing.

Deliverables:

- GGUF export pipeline.
- llama.cpp runner.
- Expert router.
- Skill registry.
- Artifact manifest store.
- Benchmark harness.

Exit criteria:

- Runs locally with predictable RAM use.
- Produces artifact outputs with verification manifests.

## M8: Commercial Packaging

Goal: make the project sellable without weakening open-source adoption.

Open source:

- Core runtime.
- Basic skill wrappers.
- Schemas.
- Sample workflows.
- PDX-Core-1B if licensing permits.

Paid:

- Certified regulatory packs.
- Jurisdiction rules.
- Golden test suites.
- Enterprise batch runner.
- Private connectors.
- Validation reports.
- On-prem appliance.
- Support and update channel.

