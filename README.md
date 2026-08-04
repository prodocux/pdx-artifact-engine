# PDX Artifact Engine

PDX Artifact Engine is a **model-optional**, deterministic artifact orchestration
framework. It turns structured plans into skill calls, verification results, and
checksummed manifests.

> **No trained PDX model weights are included in this repository.**
> Plans may be supplied manually, by rules, or later by an external model
> provider. PDX-5B-1B+ experts are an optional future bundle, not a v0.1.0
> requirement.

**v0.2.0a1 (in progress):** the repository ships `pdx_artifact_core` (execution
plan v1 contracts, ToolExecutor protocols, v0→v1 translator, run state machine).
Legacy Dispatcher compatibility remains available during the v1 migration.

## Positioning

| Claim | Status |
|---|---|
| `pdx_execution_plan_v1` + ToolRequest/Result schemas | **Available (core 0.2.0a1)** |
| v0→v1 plan translator (rejects unresolved `expert`) | **Available (core)** |
| Run state machine (`awaiting_*` → `running`) | **Available (core)** |
| Validate `plan.json` against v0 schema | Available |
| Load skill registry + dispatch skills | Available (v0 kinds) |
| Deterministic fixture staging | Available |
| Mock skill execution for CI / demos | Available |
| Write `artifact_manifest.json` + `run_manifest.json` | Available |
| `RulePlanner` / `ManualPlanner` | Available (to move out of Core per plan) |
| ProDocuX HTTP `/v1` adapter | **Available (alpha)** (`adapters/prodocux/`) |
| Real ProDocuX / FreeCAD / Blender subprocess execution | Register executors |
| `LlamaCppPlanner` / GGUF download / hot-swap | Planned |
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

The product-neutral ProDocuX HTTP adapter ships in the main distribution. The
media identity/probe adapter is optional and has its own package:

```bash
pip install ./adapters/media
```

See [`docs/RELEASE.md`](docs/RELEASE.md) for package boundaries and release
verification.

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

## Acknowledgments

Codex and Cursor contributed implementation support, contract hardening, and
cross-review during the v0.2 upgrade. Final design and release decisions remain
with the project maintainers.
