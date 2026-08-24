# pdx-artifact-core

Platform-neutral contracts and runtime primitives for PDX Artifact Engine.

This source subtree has a buildable boundary for isolated development and
packaging checks, but `pdx-artifact-core` is **not currently published as an
independent PyPI distribution**. Public users should install
`pdx-artifact-engine`; that distribution owns and ships the
`pdx_artifact_core` import package. A future split requires an explicit release
and migration decision.

- `pdx_execution_plan_v1`, `ToolRequest`, `ToolResult` JSON Schemas
- `ToolExecutor` / `Verifier` / `StorageAdapter` protocols
- Run state machine (`awaiting_tool` / `awaiting_approval` return edges)
- Thread-safe reference `ApprovalLedger` with public snapshot lookups for
  replay-safe host integrations
- `pdx_plan_v0` → v1 compatibility translator (rejects unresolved `expert`)

Does **not** import ProDocuX Kernel or call LLMs.

Applications may register product-specific executors without adding those
dependencies or identifiers to Core.
