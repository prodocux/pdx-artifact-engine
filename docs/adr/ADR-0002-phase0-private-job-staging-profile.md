# ADR-0002: Phase 0 private job interface, staging, and Kernel identity profile

Status: Accepted for Phase 0 contract freeze (not implemented)

Date: 2026-08-26

## Context

PDX Artifact Core already owns product-neutral `RunState`, execution context,
checkpoints, ordered run events, external operations, publication receipts,
and artifact storage identity. Artifact storage identity still permits `gs://`
object identity at the generic Core layer.

Asynchronous product work must enter Engine, not Kernel. A private
enqueue/status/cancel/reconcile interface, Engine-owned TTL source staging, and
an Engine→Kernel identity profile restricted to `artifact://` are required
before Phase 1 runtime work.

## Decision

1. Engine remains the sole authority for the neutral operation envelope,
   `RunState`, events, checkpoints, external operations, publication receipts,
   and the generic artifact storage identity schema. That generic schema is
   not edited.
2. The ProDocuX integration profile rejects `gs://`, signed URLs, local paths,
   and caller-selected output URIs at the Engine→Kernel hop. Only Kernel-
   compatible `artifact://` identities cross that hop. This profile is additive
   under `docs/phase0/` and does not mutate frozen Core schemas.
3. Phase 1 must expose this private interface (reference transport: HTTP):

   ```text
   POST /internal/v1/jobs
   GET  /internal/v1/jobs/{job_id}
   POST /internal/v1/jobs/{job_id}/cancel
   POST /internal/v1/jobs/{job_id}/reconcile
   ```

   The interface is not a public Agent or Document API. It uses a rotatable
   bearer credential on a private network; production adds mTLS without
   changing the application contract.
4. `POST /internal/v1/jobs` may carry one bounded ephemeral payload. Ingress
   hashes decoded bytes, writes Engine-owned TTL staging, and acknowledges
   only after replacing the payload with a handle plus digest, size, and media
   type. Durable rows, checkpoints, events, receipts, and logs never contain
   bytes or base64. Request-body logging is forbidden.
5. Engine source staging does not share a writable volume with WordPress or
   with the Kernel output sink. Direct Kernel calls remain limited to
   deterministic tests.
6. Frozen compatibility manifests v1, v2, and v3 remain byte-identical.
7. Host consumer drafts are not a second Engine wire format. They must map
   onto `pdx_internal_job_*` as specified in `docs/PHASE0_DECISIONS.md`.

## Consequences

- Phase 1 may implement SQLite repositories, worker lifecycle, TTL staging,
  adapter hardening, and the private HTTP façade against these documents.
- Hosts that speak WordPress keep those bindings on the Farpals side. Engine
  subjects stay opaque (`binding_id` + `revision`).
