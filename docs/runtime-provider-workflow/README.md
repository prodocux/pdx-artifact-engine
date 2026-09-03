# Runtime provider workflow v1 — bilateral contract freeze

Status: bilateral contract content frozen; production implementation is not authorized.

This additive contract answers the application-neutral workflow capability request.
It does not modify the published `0.3.0a4` contracts, the frozen compatibility
records, or the six consumer-owned provider/check handshake envelopes.

## Authority and boundaries

Engine owns durable workflow, step, attempt, claim/lease, aggregate counters,
artifact edges, cancellation, reconciliation and terminal receipts. A provider,
reviewer, peer message or artifact is untrusted evidence and never grants
approval, credentials, policy exceptions or capabilities. Application/runtime
layers retain provider selection, workspace policy, approval and process/network
isolation. Engine never persists a credential reference or plaintext lease token.

The authoritative frozen documents are:

- `pdx_runtime_provider_workflow_plan_v1`: immutable, digested workflow intent,
  bounded application-neutral step kinds, aggregate budgets and allowed
  producer/consumer artifact edges;
- `pdx_runtime_provider_workflow_state_v1`: Engine-derived counters and durable
  state projection; counters are not accepted from a provider update;
- `pdx_runtime_provider_workflow_receipt_v1`: terminal relationship record that
  separates evidence/recommendations from human or application-native authority;
- `pdx_runtime_provider_workflow_error_v1`: bounded stable rejection semantics.

The plan digest covers the complete plan document except `plan_digest` itself,
using RFC 8785/I-JSON canonicalization and SHA-256. In particular it covers task,
run, steps, dependencies, budgets, authorized artifact edges and operation or
check-definition digests.

## Required transactional semantics

JSON Schema constrains document shape; the future persistence implementation
must additionally provide these atomic invariants:

1. Starting an attempt increments total attempts and active steps in the same
   transaction as the claim. Exceeding any limit rejects the transition and
   creates no claim.
2. Event bytes, registered artifact bytes, record-once artifacts, artifact edges
   and external operations increment their counters in the same transaction as
   the metered record.
3. An artifact read is accepted only when task/run match and an exact planned
   producer-to-consumer edge exists. Attempt-scoped artifacts cannot cross an
   attempt unless the plan edge explicitly targets the consuming step.
4. A successful check can terminate only after its report artifact identity,
   SHA-256, size and media type have been verified and registered exactly once.
5. Cancel, timeout or budget exhaustion atomically invalidates active claims and
   leases. Later updates/artifacts/outcomes are rejected as bounded security
   evidence and never advance workflow state.
6. Reconcile derives state from durable records and cannot let an expired attempt
   update a replacement claim. `reconcile_required` is Engine-derived.

## Stable errors

The contract freezes these codes:

- `WORKFLOW_BUDGET_EXHAUSTED`
- `ARTIFACT_REFERENCE_UNAUTHORIZED`
- `ARTIFACT_EDGE_UNPLANNED`
- `ARTIFACT_RECORD_CONFLICT`
- `COMMUNICATION_CHANNEL_UNAUTHORIZED`
- `WORKFLOW_NOT_ACTIVE`
- `POST_TERMINAL_ACTIVITY_REJECTED`
- `CLAIM_STALE`
- `LEASE_EXPIRED`
- `SEQUENCE_CONFLICT`
- `PAYLOAD_DIGEST_INVALID`
- `CHECK_REPORT_REQUIRED`
- `CHECK_REPORT_UNVERIFIED`

No route, database migration, worker dispatch or release capability is implied by
these files. Implementation and release require separate authorization.

Budget exhaustion uses the existing `failed` machine state with
`terminal_error.code=WORKFLOW_BUDGET_EXHAUSTED`; it is not a parallel RunState.

## Authoritative wire surface

The frozen contract assigns PDX-owned wire IDs for workflow create request/response,
provider claim request/claim/update, check claim request/claim/update, typed
event/outcome records, provider/check lease renewal, cancel, reconcile,
state/receipt/error documents and route mapping. Check events/outcomes use a
dedicated record so their agreed payloads map without synthetic fields. The
mapping freezes 202/200 success, 409 CAS/idempotency conflicts, 410 inactive or
post-terminal claims, and 413 size rejection. These schemas map the agreed
consumer envelopes without republishing or modifying them.

## Semantic validation

`semantic_validator.py` is executable contract evidence, not packaged runtime
code. It rejects duplicate step/edge IDs, missing dependencies, cycles, unknown
edge endpoints, self-edges, invalid role/producer combinations, aggregate/step
budget contradictions, invalid repair iteration/parent relationships and an
invalid plan digest. A concurrency ceiling larger than the step count is valid;
it is merely unused capacity. Fixed Hub topology remains a Farpals profile.
`repair_iterations` is the
ninth durable counter and is atomically incremented when a repair step is
created. Runtime implementation must use the agreed RFC 8785 authority.

All schema files must compile under both Python Draft 2020-12 validation and AJV
2020-12 with `strict: true`. The evidence manifest pins the route mapping,
semantic validator, AJV verifier, canonical parity verifier, exact Farpals
positive/negative vectors and lossless check mapping fixtures.

### Reproduce the JavaScript gates

The recorded run used Node `22.18.0`, AJV `8.20.0` and `ajv-formats` `3.0.1`.
`PDX_AJV_MODULE_ROOT` must point to an npm project containing those dependencies;
mapping verification additionally needs `FARPALS_HUB_CONTRACT_ROOT` pointing to
the Hub contract package whose six proposal digests are recorded in
`consumer-proposal-agreement.json`.

```powershell
$env:PDX_AJV_MODULE_ROOT = 'D:\path\to\farpals\contracts\farpals-hub'
node .\docs\runtime-provider-workflow\verify-ajv-strict.mjs
$env:FARPALS_HUB_CONTRACT_ROOT = $env:PDX_AJV_MODULE_ROOT
node .\docs\runtime-provider-workflow\verify-consumer-mappings.mjs
node .\docs\runtime-provider-workflow\verify-canonical-parity.mjs
```

Expected output is `AJV_STRICT_PASS 21`, `CONSUMER_MAPPING_PASS 2` and
`CANONICAL_PARITY_PASS 3+2`.
