# Engine Phase 3 — job-bound verified retrieval (freeze)

Status: **COMPLETE** (2026-08-28).

## Formal record

Engine exposes job-bound verified bytes retrieval that validates
terminal job state, result `kind`, and exact artifact identity before
calling Kernel `POST /v1/artifacts/retrieve`.

## Freeze SHA

- Engine Phase 3 implementation: `fb3aa6d`
- Kernel Phase 3 companion: `f6cee0d`

## Landed

- `POST /internal/v1/jobs/{job_id}/retrieve`
- `JobService.retrieve()` + Kernel client hop
- `ProDocuXHttpClient.retrieve_artifact()`
- Schemas under `docs/phase3/schemas/`
- Tests: `tests/test_phase3_retrieve.py`

## Env (same as worker)

- `PDX_KERNEL_BASE_URL`
- `PRODOCUX_BEARER_TOKEN`
- Optional mTLS client cert env vars

When Kernel client is not configured, retrieve returns
`KERNEL_UNAVAILABLE` (503).

## Companion

Kernel route and retrieval logic: `prodocux/docs/PHASE3_STATUS.md`.
