# Backlog

## v0.1.0 (framework)

- [x] Apache-2.0 license
- [x] Unified skill + skill_registry schemas
- [x] Model-optional README positioning
- [x] ManualPlanner + RulePlanner
- [x] depends_on + `$step.output` wiring
- [x] run_manifest with honest status
- [x] Deterministic fixture E2E example
- [x] model_manifest schema (weights out of band)
- [x] Path traversal guards + unknown-skill failed manifests
- [x] Regression tests on clean Python 3.12 venv

## Now (post-publish)

- [ ] Push `prodocux/pdx-artifact-engine` and tag `v0.1.0`
- [ ] Confirm GitHub Actions pytest on main
- [ ] Convert ProDocuX Run06 into planner traces
- [ ] Register real ProDocuX skill executors (not mock)

## v0.2.0

- [ ] LlamaCppPlanner provider
- [ ] Model download config from model_manifest
- [ ] Publish PDX-Core-1B weights out of band

## PDX-Core-1B

- [ ] Select base model candidates
- [ ] Build router dataset
- [ ] Build held-out router eval
- [ ] Create Kaggle training notebook
- [ ] Add GGUF export instructions

## PDX-Doc-1B

- [ ] Define `drafts.json` training format
- [ ] Add source-map eval examples
- [ ] Add audit-repair examples

## PDX-3D-1B

- [ ] Finalize FreeCAD skill input/output schema
- [ ] Finalize Blender skill input/output schema
- [ ] Create synthetic CAD/Blender routing traces
- [ ] Prototype FreeCAD / Blender CLI wrappers

## Runtime

- [x] Define skill registry format
- [x] Artifact + run manifest writers
- [x] Plan validation and mock/fixture dispatch
- [ ] Local model hot-swap
- [ ] llama.cpp benchmark script
