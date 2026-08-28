# Engine Phase 3 — verified retrieval + compare/verify worker (freeze)

Status: **COMPLETE** (2026-08-28).

## Formal record

Engine Phase 3 covers:

1. Job-bound verified bytes retrieval (`POST …/retrieve`)
2. Worker execution for `compare_normalized_profiles` and `verify_evidence`
3. Stable `ARTIFACT_TOO_LARGE` mapping from Kernel 413

All expensive T1 product work remains on the Engine worker path.

## Freeze SHA

- Engine Phase 3 implementation: `fb3aa6d`
- Kernel Phase 3 companion: `f6cee0d`
- Phase 3 tail (compare/verify worker + retrieval errors): `9b55213`

## Landed

### Verified retrieval

- `POST /internal/v1/jobs/{job_id}/retrieve`
- `JobService.retrieve()` + Kernel client hop
- `ProDocuXHttpClient.retrieve_artifact()`
- `ARTIFACT_TOO_LARGE` (413, non-retryable) vs `KERNEL_RETRIEVAL_FAILED`

### Compare / verify worker

- Worker paths for `compare_normalized_profiles`, `verify_evidence`
- Adapter `compare_normalized_profiles()`, `verify_evidence_bundle()`
- Result semantics: single `processing_output` derived JSON artifact
- Tests: `tests/test_phase3_compare_verify_worker.py`

### Docs / tests

- `docs/phase3/README.md`
- `tests/test_phase3_retrieve.py`

## Env (same as worker)

- `PDX_KERNEL_BASE_URL`
- `PRODOCUX_BEARER_TOKEN`
- Optional mTLS client cert env vars

## Farpals handoff

- **Publication slice** (retrieve → T2 publish → Media Library): unblocked
  on retrieval freeze; Farpals-owned.
- **Full Phase 3 capabilities** (compare/evidence MCP tools): unblocked once
  Farpals pins this tail SHA and wires job dispatch for the two operations.

## Companion

Kernel retrieval and limit policy: `prodocux/docs/PHASE3_STATUS.md`.
