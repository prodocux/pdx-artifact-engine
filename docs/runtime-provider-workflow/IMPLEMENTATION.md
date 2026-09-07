# Runtime provider workflow implementation

Status: the bilateral workflow implementation was published as Engine
`0.3.0a5`. Release `0.3.0a6` adds only the read-only step
projection described in `STEP_PROJECTION.md`. Contract authority remains the 23-schema manifest frozen through PDX
`f5f05ce39246712c8e9c4e3121bafaa9a4df6b54` and Farpals
`891f837013251e70755c4eb0eac14df3be9bb87b`.

## Implemented Engine ownership

- SQLite/WAL durable workflow, step, attempt, claim, record and artifact-edge
  tables with `BEGIN IMMEDIATE` transitions.
- Create/get-plan/get-state, provider/check activation, lease renewal, typed
  updates, cancel, reconcile and terminal receipt routes.
- Frozen-plan dependency and budget checks before attempt creation.
- Authenticated control-plane instance matching; request-body identity is not an
  authentication authority.
- HMAC-SHA-256 deterministic lease-token recovery for exact activation retries.
  Plaintext tokens are returned but never persisted.
- Per-attempt sequence CAS, payload digest verification, lease expiry/staleness
  fencing, check-report identity registration and terminal claim invalidation.
- Packaged copies of all 23 authoritative schemas with byte-parity tests.
- Additive control-plane-only step projection for restart recovery; it exposes
  no lease token, token digest, credential, provider payload or new authority.

## HMAC configuration and rotation

For a single key, set `PDX_ENGINE_WORKFLOW_HMAC_SECRET` to at least 32 bytes. For
rotation, use `PDX_ENGINE_WORKFLOW_HMAC_KEYS` as a JSON object mapping opaque key
IDs to secrets and select the writer with
`PDX_ENGINE_WORKFLOW_ACTIVE_HMAC_KEY_ID`. Old keys must remain configured until
all claims created under them are terminal. `/ready` fails when an active claim
references a missing key.

Control-plane bearer credentials must already pass the normal Engine auth profile
and must additionally be registered with `PDX_ENGINE_CONTROL_PLANE_BINDINGS`, a
JSON object mapping control-plane instance IDs to bearer credentials.

## Boundary

Engine never executes providers, stores `credential_ref`, interprets agent text
as authority, or enforces host network/process policy. No existing E-05 job table,
published a4/a5 contract or Kernel interface was changed.
