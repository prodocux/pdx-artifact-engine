# ER-002 implementation candidate

Status: `implementation_candidate_not_signed_off`

This candidate implements the frozen governed dynamic-dispatch contracts and
ERRATUM-001 parent-workflow authority. It does not assign a release version,
authorize publication, or change the frozen contract bytes.

Implemented boundaries:

- durable policy registration and compare-and-set revocation;
- immutable decision receipt import and RFC 8785 digest verification;
- authenticated activation, frozen live-registry verification and atomic
  idempotency allocation;
- synthesized static `pdx_execution_plan_v1` Run B plans;
- input/output schema enforcement and output suppression on failure;
- immutable receipt and verified-output CAS publication;
- parent v2 workflow counters, step receipts and artifact edges;
- not-started and running cancellation evidence;
- attempt-bound reconciliation and competing-worker execution fencing; and
- all seven frozen HTTP operations.

The host supplies a `DispatchToolRegistry` containing deployment-verified
executors. A worker calls `run_next_activation()`; the Engine atomically fences
competing workers before invoking the registered executor.

Review evidence and file digests are recorded in
`implementation-candidate.v1.json`. Demand-side sign-off is required before a
version, tag, wheel publication or downstream adapter implementation is
authorized.
