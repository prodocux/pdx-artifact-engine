# PDX-Core-1B (planned)

Status: **planned** — weights are not published and are not part of this repository.

## Role

Local router / planner expert for PDX Artifact Engine (intent → plan.json, skill
selection, repair loops).

## Distribution policy

- Publish weights via Hugging Face, GitHub Releases, or a private registry.
- Record download URI + sha256 in `examples/models/pdx_core_1b.manifest.json`.
- Runtime integration lands in v0.2.0+ (`LlamaCppPlanner`), not v0.1.0.

## Non-goals for v0.1.0

- No GGUF / safetensors in git
- No bundled inference runtime
- Framework must run with ManualPlanner / RulePlanner only
