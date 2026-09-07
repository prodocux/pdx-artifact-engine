# Runtime workflow step projection — additive a6 candidate

Status: implemented locally for Farpals Phase B restart recovery. This is an
additive Engine-owned read model; it does not modify the 23 schemas frozen and
published with Engine `0.3.0a5`.

## Route

`GET /internal/v1/runtime-provider-workflows/{workflow_job_id}/steps`

The route requires the normal private Engine authentication profile and a bearer
credential registered in `PDX_ENGINE_CONTROL_PLANE_BINDINGS`. A valid generic
Engine bearer that is not a registered control-plane instance receives
`ACTIVATION_AUTH_FORBIDDEN`.

The response validates against
`pdx_runtime_provider_step_projection_v1.schema.json`. Its documented and
packaged bytes are identical. It contains the workflow/plan identity, workflow
state, snapshot time, and one entry for every step in immutable plan order.

Each entry exposes only current Engine step state, latest attempt number, whether
the latest claim is active, and the terminal outcome record identity when one
exists. Terminal identity consists of record ID, record schema ID and payload
digest. Raw records, provider output, credentials, plaintext lease tokens and
lease-token digests are excluded.

## Recovery semantics

- The projection is built in one SQLite read transaction from the frozen plan,
  durable step rows, claims and outcome records.
- Callers reconcile before reading when recovering after a restart. An expired
  claim remains durable and active until reconcile fences it; after reconcile,
  the step is pending, the prior attempt remains visible, and `active_claim` is
  false.
- Terminal workflows remain readable. The workflow state/receipt remains the
  authority for terminal handling.
- The snapshot is informational. Farpals may use it to choose a candidate next
  step, but activation CAS remains the final readiness authority.
- `recorded_at` identifies the observation time; it is not a monotonic mutation
  revision and must not be used as a compare-and-swap token.

No database migration, Kernel change, worker pull interface, or competing Hub
durable state is introduced.

## Contract verification

The additive manifest pins the schema and its dedicated AJV verifier without
changing the a5 authoritative manifest. Reproduce the cross-runtime compile with:

```powershell
$env:PDX_AJV_MODULE_ROOT = 'D:\path\to\npm-project-with-ajv'
node .\docs\runtime-provider-workflow\additive\verify-step-projection-ajv-strict.mjs
```

Expected output: `AJV_ADDITIVE_STEP_PROJECTION_PASS 1`.
