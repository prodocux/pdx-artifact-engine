# PDX Artifact Engine

PDX Artifact Engine is a **model-optional**, deterministic artifact orchestration
framework. It turns structured plans into skill calls, verification results, and
checksummed manifests.

> **No trained PDX model weights are included in this repository.**
> Plans may be supplied manually, by rules, or later by an external model
> provider. PDX-5B-1B+ experts are an optional future bundle, not a v0.1.0
> requirement.

Initial framework authored with Codex; Cursor assisted integration, hardening, and release.

## Positioning (v0.1.0)

| Claim | Status |
|---|---|
| Validate `plan.json` against schema | Available |
| Load skill registry + dispatch skills | Available |
| Deterministic fixture staging | Available |
| Mock skill execution for CI / demos | Available |
| Write `artifact_manifest.json` + `run_manifest.json` | Available |
| `RulePlanner` / `ManualPlanner` | Available |
| Built-in checks `step_completed:` / `file_exists:` | Available |
| Real ProDocuX / FreeCAD / Blender subprocess execution | Not in v0.1.0 (register executors) |
| `LlamaCppPlanner` / GGUF download / hot-swap | Planned v0.2.0+ |
| Shipped `PDX-Core-1B` weights | **Not included** (separate release) |

Target architecture (not present in v0.1.0): a future 8 GB mode may keep a
`PDX-Core-1B` router resident and hot-swap specialists. That is a roadmap goal,
not a current runtime capability.

## Core thesis

```text
plan.json  (manual | rules | future model provider)
  -> skill dispatch
  -> artifact outputs
  -> verification
  -> artifact_manifest.json + run_manifest.json
```

Small models should eventually plan and repair. Skills should execute artifact
creation with deterministic tools. v0.1.0 proves the second half without the
first.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Deterministic demo (no LLM)

From the repository root:

```bash
python -m pdx_artifact_engine.cli.run \
  --plan examples/plans/pif_deterministic_plan.json \
  --output-dir .tmp/pif-deterministic \
  --mock
```

Or generate a plan with `RulePlanner`:

```bash
python -m pdx_artifact_engine.cli.run \
  --rule-request examples/requests/pif_rule_request.json \
  --output-dir .tmp/pif-rule \
  --mock
```

Both write:

- `run_manifest.json` — overall `completed` / `completed_with_review` / `failed` / `blocked`
- `artifact_manifest.json` — files, provenance, verification

CLI exit code is `1` when status is `failed` or `blocked`.

### Aspirational plan (contains expert step)

`examples/plans/pif_workflow_plan.json` still includes a `PDX-Doc-1B` expert step
to document the future shape. Without `--mock`, that plan **blocks**. With
`--mock`, the expert is simulated and the run is marked `completed_with_review`.

## Planner providers

| Provider | v0.1.0 |
|---|---|
| `ManualPlanner` (`--plan`) | Yes |
| `RulePlanner` (`--rule-request`) | Yes |
| `ExternalPlanner` | Stub (raises) |
| `LlamaCppPlanner` | Stub (raises; reserved for v0.2.0+) |
| Future `PDXCorePlanner` | Not started |

## Schemas

| Schema | Purpose |
|---|---|
| `schemas/plan.schema.json` | Workflow plan (+ optional `depends_on`) |
| `schemas/skill.schema.json` | One skill's metadata |
| `schemas/skill_registry.schema.json` | Registry document |
| `schemas/artifact_manifest.schema.json` | Deliverable manifest |
| `schemas/run_manifest.schema.json` | Run status |
| `schemas/model_manifest.schema.json` | Optional model descriptor (no weights) |
| `schemas/3d_spec.schema.json` | CAD/scene specs |

Model weights stay outside git. Describe them with
`examples/models/*.manifest.json` and `docs/model-cards/`.

## Repository layout

```text
docs/                 Architecture, roadmap, model cards
schemas/              JSON contracts
examples/             Plans, fixtures, rule requests, model manifests
notebooks/kaggle/     Training plans (no weights)
runtime/              Python package `pdx_artifact_engine`
skills/               Sample skill registry
evals/                Eval notes
tests/                pytest
```

## v0.1.0 release criteria

- [x] Apache-2.0 license
- [x] Unified skill + registry contract
- [x] README states model-optional clearly
- [x] `depends_on` + `$step.output` wiring
- [x] Honest run status (no silent success on blocked experts)
- [x] Deterministic E2E example without LLM
- [x] `model_manifest` schema (weights out of band)
- [x] Path traversal rejection for `file_exists` / mock outputs
- [x] Unknown skill / executor errors always write schema-valid failed manifests
- [x] Cycle detection covered by tests
- [x] Fresh Python 3.12 venv pytest green

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Near-term roadmap

1. Register real ProDocuX skill executors (M1).
2. Convert ProDocuX runs into planner traces.
3. Train and publish `PDX-Core-1B` out of band; wire `LlamaCppPlanner` (v0.2.0).
4. Low-RAM hot-swap runtime (M7).
