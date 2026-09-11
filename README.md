# PDX Artifact Engine

PDX Artifact Engine is a **model-optional**, deterministic artifact orchestration
framework. It turns structured plans into skill calls, verification results, and
checksummed manifests.

> **No trained PDX model weights are included in this repository.**
> Plans may be supplied manually, by rules, or later by an external model
> provider. PDX-5B-1B+ experts are an optional future bundle, not a v0.1.0
> requirement.

**Current PyPI prerelease: `0.3.0a6`**, published from tag **`v0.3.0a6`** at
commit `1f29a792b9b86cef1c54706ab154ad4c50cbfc6a`. Media adapter remains
**`0.2.0a2`** and was not republished with Engine a6. Publication evidence is
recorded in
[`compatibility/pdx_artifact_engine_release_a6.json`](compatibility/pdx_artifact_engine_release_a6.json);
it does not rewrite the frozen coordinated release records.

The next unpublished candidates are Engine **`0.3.0a8`** and Media
**`0.2.0a3`**. Public tag **`v0.3.0a7`** did not pass the release workflow and
is retained only as an audit record; it is not a PyPI release or consumer pin.
See [the a8/a3 release candidate record](docs/RELEASE_A8_MEDIA_A3.md).

Engine a6 adds an authenticated, read-only per-step recovery projection without
modifying the a5 workflow contracts or durable authority model.

The prior coordinated security cut and its accepted OS boundary remain recorded
in [the rc4/a4 publication record](docs/RELEASE_RC4_A4.md). Engine a5 adds the
runtime-provider workflow without changing those frozen historical records.

```powershell
python -m pip install "pdx-artifact-engine==0.3.0a6"
```

## Positioning

| Claim | Status |
|---|---|
| `pdx_execution_plan_v1` + ToolRequest/Result schemas | **Available (0.3.0a5; introduced in 0.3.0a1)** |
| v0→v1 plan translator (rejects unresolved `expert`) | **Available (core)** |
| Run state machine (`awaiting_*` → `running`) | **Available (core)** |
| Bounded run snapshot + step receipt contracts | **Available (0.3.0a5; introduced in 0.3.0a1)** |
| Checkpoint CAS + decision record-once repository ports | **Available (core)** |
| Replay-safe pending-only snapshot resume | **Available (engine)** |
| External-operation pending/unknown/reconcile lifecycle | **Available (core)** |
| Execution context, cooperative cancellation, receipts, ordered events | **Available (core)** |
| Durable runtime-provider workflow v1 (23 packaged schemas, SQLite CAS, authenticated activation, HMAC leases, receipts) | **Available (`0.3.0a5`)** |
| Read-only workflow step recovery projection | **Available (`0.3.0a6`)** |
| Generic conformance-check binding | **Unpublished candidate (`0.3.0a8`)** |
| Media technical conformance evaluator | **Unpublished standalone candidate (`0.2.0a3`)** |
| Validate `plan.json` against v0 schema | Available |
| Load skill registry + dispatch skills | Available (v0 kinds) |
| Deterministic fixture staging | Available |
| Mock skill execution for CI / demos | Available |
| Write `artifact_manifest.json` + `run_manifest.json` | Available |
| `RulePlanner` / `ManualPlanner` | Available (to move out of Core per plan) |
| ProDocuX HTTP `/v1` adapter | **Available (alpha)** (`adapters/prodocux/`) |
| ProDocuX deterministic block extraction/render tools | **Available (alpha)** (`prodocux.extract_content_blocks`, `prodocux.render_artifact`) |
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

Install the current Engine prerelease from PyPI:

```bash
pip install "pdx-artifact-engine==0.3.0a6"
```

See the
[`pdx-artifact-engine` PyPI `0.3.0a6` release](https://pypi.org/project/pdx-artifact-engine/0.3.0a6/)
and
[GitHub prerelease](https://github.com/prodocux/pdx-artifact-engine/releases/tag/v0.3.0a6).

The older published wheel
[`pdx-artifact-engine` PyPI `0.3.0a1`](https://pypi.org/project/pdx-artifact-engine/0.3.0a1/)
predates the additive extract/render freeze and must not be overwritten. Frozen
compatibility v3 still pins implementation commit
`37e89752560b22dc8724d470dce96187f19e3f98`.

Requires Python 3.11+.

The product-neutral ProDocuX HTTP adapter ships in the main distribution. The
media identity/probe adapter is optional and has its own package:

```bash
pip install ./adapters/media
```

Install its coordinated standalone PyPI package with:

```bash
pip install "pdx-adapter-media==0.2.0a2"
```

See the [`pdx-adapter-media` PyPI project](https://pypi.org/project/pdx-adapter-media/0.2.0a2/).

See [`docs/RELEASE.md`](docs/RELEASE.md) for package boundaries and release
verification.

The active coordinated ProDocuX/PDX prerelease surface is recorded in
[`compatibility/pdx_prodocux_compatibility_v2.json`](compatibility/pdx_prodocux_compatibility_v2.json).
Additive extract/render pins are recorded in
[`compatibility/pdx_prodocux_compatibility_v3.json`](compatibility/pdx_prodocux_compatibility_v3.json).
G1A in that manifest is the frozen synthetic render-conformance fixture set.
Current tags, package versions, assets, and publication state are recorded in
[`compatibility/pdx_prodocux_release_v1.json`](compatibility/pdx_prodocux_release_v1.json).
The immutable v1 manifest remains packaged in the repository as historical
compatibility evidence.

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

| Provider | Current prerelease status |
|---|---|
| `ManualPlanner` (`--plan`) | Yes |
| `RulePlanner` (`--rule-request`) | Yes |
| `ExternalPlanner` | Stub (raises) |
| `LlamaCppPlanner` | Stub (raises; planned, not implemented in `0.3.0a5`) |
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

The packaged Core additionally publishes execution-plan, verifier-result,
workflow-checkpoint, approval, artifact identity, step receipt, run snapshot,
external operation, execution context, publication receipt, and run event v1
contracts. `ArtifactRuntime` accepts product-owned verifier implementations
through an injected registry; missing verifiers fail closed unless the host
explicitly selects review policy. Serialized snapshot resume validates plan,
subject, evidence, artifact, and receipt digests and executes only pending
steps. Provider polling, durable databases, scheduling, and domain policy stay
outside Core.

Model weights stay outside git. Describe them with
`examples/models/*.manifest.json` and `docs/model-cards/`.

## Repository layout

```text
docs/                 Architecture, roadmap, model cards, Phase 0 contracts
packages/             Packaged Core source and schemas
adapters/             Product-neutral optional integration packages
schemas/              JSON contracts
examples/             Plans, fixtures, rule requests, model manifests
notebooks/kaggle/     Training plans (no weights)
runtime/              Python package `pdx_artifact_engine`
skills/               Sample skill registry
evals/                Eval notes
tests/                pytest
```

## Historical v0.1.0 release criteria

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

See [docs/ROADMAP.md](docs/ROADMAP.md) for the M0-M8 milestone definitions.
Phase 0 private-job paper freeze: [`docs/PHASE0_DECISIONS.md`](docs/PHASE0_DECISIONS.md).

1. Integrate the available ProDocuX HTTP adapter tools into product-owned skill
   registries and executors (M1).
2. Convert ProDocuX runs into planner traces.
3. Train and publish `PDX-Core-1B` out of band; wire `LlamaCppPlanner` in a
   future version.
4. Low-RAM hot-swap runtime (M7).

## Acknowledgments

Codex and Cursor contributed implementation support, contract hardening, and
cross-review during the v0.3 prerelease upgrade. Final design and release decisions remain
with the project maintainers.
