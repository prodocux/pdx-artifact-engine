# Architecture

## Design Principle

PDX Artifact Engine separates intelligence into two layers:

1. Planners compile intent into structured plans and specs
   (`ManualPlanner` / `RulePlanner` now; optional model providers later).
2. Skills execute deterministic artifact operations and verification.

v0.1.0 is **model-optional**: the framework must run with hand-authored or
rule-generated plans. Small models are a later acceleration layer, not a
hard dependency.

This separation keeps the runtime local, low-RAM, auditable, and easier to
commercialize.

## Runtime Flow

```text
User Request
  -> PDX-Core-1B
  -> plan.json
  -> specialist selection
  -> artifact spec
  -> skill calls
  -> artifact outputs
  -> verification report
  -> repair loop
  -> final delivery manifest
```

## Expert Responsibilities

### PDX-Core-1B

The only model expected to be resident in 8 GB mode.

Responsibilities:

- Intent classification.
- Skill and expert routing.
- Plan generation.
- Missing-input detection.
- Tool-call validation.
- Verification-loop management.
- Final delivery summarization.

### PDX-Doc-1B

Document and regulatory workflow specialist.

Outputs:

- `drafts.json`
- `source_map.json`
- `evidence_spec.json`
- `review.md` entries
- audit repair plans

### PDX-Code-1B

Code artifact specialist.

Outputs:

- repo inspection plan
- patch plan
- test plan
- failure repair plan

It should not bypass normal version-control or test workflows.

### PDX-Data-1B

Structured data specialist.

Outputs:

- table schemas
- extraction specs
- reconciliation reports
- validation requests

### PDX-Media-1B

Visual and time-based media specialist.

Outputs:

- chart specs
- slide specs
- image prompts
- storyboard specs
- video composition specs

### PDX-3D-1B

3D and CAD specialist.

Outputs:

- CAD specs for FreeCAD
- scene specs for Blender
- geometry constraints
- units and tolerances
- export requirements
- verification requests

## Skill Layer

Skills are callable, testable artifact functions. A skill may wrap Python,
FreeCAD, Blender, ffmpeg, chart engines, document tools, or external command
line tools.

A skill must declare:

- name
- version
- description
- input schema
- output schema
- artifacts produced
- dependencies
- failure codes
- verification hooks

## Memory Strategy

8 GB mode:

- Keep `PDX-Core-1B` loaded.
- Load one specialist only when required.
- Prefer Q4 or Q5 GGUF.
- Keep context compact.
- Use retrieval and artifact manifests instead of long context stuffing.

16 GB mode:

- Keep Core plus one active specialist.
- Allow longer context and faster repair loops.

Server mode:

- Keep several specialists loaded.
- Use queueing, batching, and a persistent artifact store.

## Why Not One General 5B Model

A single 5B model may be easier to explain, but it is less aligned with the
product goal:

- Higher RAM pressure.
- Weaker specialization.
- Less deterministic behavior.
- Harder verification.
- Less room for skill-level monetization.

PDX-5B-1B+ treats the model bundle as a set of small compilers and treats
skills as artifact executors.
