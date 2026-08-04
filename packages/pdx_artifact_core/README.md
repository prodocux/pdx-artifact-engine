# pdx-artifact-core

Platform-neutral contracts and runtime primitives for PDX Artifact Engine.

- `pdx_execution_plan_v1`, `ToolRequest`, `ToolResult` JSON Schemas
- `ToolExecutor` / `Verifier` / `StorageAdapter` protocols
- Run state machine (`awaiting_tool` / `awaiting_approval` return edges)
- `pdx_plan_v0` → v1 compatibility translator (rejects unresolved `expert`)

Does **not** import ProDocuX Kernel or call LLMs.

Applications may register product-specific executors without adding those
dependencies or identifiers to Core.
