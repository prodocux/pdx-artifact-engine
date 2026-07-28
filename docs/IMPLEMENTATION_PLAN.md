# Implementation Plan

## Goal

Create PDX Artifact Engine as the project home for PDX-5B-1B+:

- local agent runtime
- 1B-class expert models
- deterministic skills
- verifiable artifact delivery
- 8 GB low-RAM mode and 16 GB practical mode

## Operating Assumptions

- Kaggle is used for free-GPU experiments, not serving.
- GitHub is the source of truth.
- ProDocuX document skills are the first production-grade skill family.
- FreeCAD and Blender are added as the first 3D skill family.
- Models produce plans/specs; skills produce artifacts.

## 0-30 Days: Foundation

### Project

- Initialize Git.
- Choose license.
- Publish public GitHub repository.
- Add README, roadmap, architecture, schemas, and issue templates.
- Add GitHub Actions for JSON/schema validation.

### Skills

- Register existing ProDocuX skills in `skills/registry.sample.json`.
- Add wrappers for structured input/output where missing.
- Define artifact manifests for ProDocuX runs.
- Add failure codes for each skill.

### Data

- Convert existing ProDocuX experiment runs into trace examples.
- Create `router`, `doc`, `repair`, and `ask_human` trace categories.
- Keep customer/private data out of the public repo.

### Models

- Select 2-3 small base models for Core experiments.
- Build the first Kaggle dataset notebook.
- Build the first Core router fine-tuning notebook.

### 3D

- Keep `PDX-3D-1B` in roadmap as a smoke-track, not the first commercial wedge.
- Write 100 synthetic 3D traces:
  - 50 FreeCAD CAD tasks
  - 50 Blender render/animation tasks
- Evaluate only routing and schema validity at first.

## 31-60 Days: First Working Engine

### Runtime

- Implement a local skill registry loader.
- Implement a plan validator.
- Implement an artifact manifest writer.
- Add a simple dispatcher that can execute mock skills.

### ProDocuX Integration

- Connect the dispatcher to real ProDocuX skills:
  - `pdf_extract`
  - `doc_assemble`
  - `structure_health`
  - `pif_audit`
  - `number_audit`
- Run a PIF workflow from plan to output manifest.

### Kaggle

- Train `PDX-Core-1B` LoRA for routing and plan generation.
- Evaluate valid JSON, skill selection, and missing-input detection.
- Add audit-failure repair examples and rerun.

### 3D

- Prototype FreeCAD skill wrapper if FreeCAD is locally available.
- Prototype Blender skill wrapper if Blender is locally available.
- If local tools are unavailable, keep wrappers as specs and mock executors.

## 61-90 Days: Expert Bundle

### PDX-Doc-1B

- Train a document expert for:
  - structured drafts
  - source maps
  - review flags
  - evidence specs
  - repair actions

### PDX-3D-1B Smoke

- Train a small 3D expert LoRA or instruction baseline.
- Target outputs:
  - valid `pdx_3d_spec_v0`
  - correct FreeCAD vs Blender routing
  - explicit units and constraints
  - valid verification list

### Low-RAM Runtime

- Merge LoRA adapters.
- Convert model checkpoints to GGUF.
- Quantize Q4_K_M and Q5_K_M.
- Benchmark with llama.cpp.
- Define 8 GB and 16 GB runtime profiles.

## First Demo

Demo title:

> PDX Artifact Engine turns a regulatory document request into an audit-ready
> DOCX package with source maps and verification reports on a local machine.

Demo flow:

1. User requests a PIF package.
2. Core creates a plan.
3. Doc expert creates document specs.
4. ProDocuX skills assemble and audit.
5. Engine produces:
   - `output.docx`
   - `source_map.json`
   - `evidence_index.json`
   - `audit_report.json`
   - `artifact_manifest.json`

## Second Demo

Demo title:

> PDX-3D compiles a product design request into a FreeCAD or Blender artifact.

Demo flow:

1. User requests a printable cap or product render.
2. Core routes to `PDX-3D-1B`.
3. 3D expert emits `pdx_3d_spec_v0`.
4. FreeCAD or Blender skill produces outputs.
5. Engine verifies exports or renders.

## Decision Gates

Continue investing in a model expert only if:

- It improves skill selection or artifact specs over prompting alone.
- It produces valid JSON at high reliability.
- It reduces user effort or repair cycles.
- It can be quantized and run in the target RAM profile.

Keep functionality as a deterministic skill if:

- Rules are explicit.
- Output can be computed.
- The task needs precision more than language judgment.
- Failure must be explainable.

