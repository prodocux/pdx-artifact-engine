# Phase 3 — job-bound verified retrieval

Engine adds a private façade route that **binds retrieval to E-05 job
context** before delegating to Kernel verified bytes.

## Route

`POST /internal/v1/jobs/{job_id}/retrieve`

### Request (`pdx_internal_job_artifact_retrieve_v1`)

- `job_id` must equal path `job_id`
- `kind`: `materialized_source` or `processing_output`
- `artifact`: full `prodocux_opaque_artifact_v1` identity (must match
  the stored result item for that `kind`)

### Success (`pdx_internal_job_artifact_content_v1`)

- Echoes bound `job_id`, `kind`, and `artifact`
- `media_type`, `size_bytes`, `sha256`, `content_b64` from Kernel hop

### Errors

| Code | When |
|------|------|
| `RESULT_NOT_READY` | Job not in `completed` / `completed_with_review` |
| `RESULT_KIND_MISSING` | No result for requested `kind` |
| `ARTIFACT_BINDING_MISMATCH` | Request artifact ≠ stored result artifact |
| `KERNEL_UNAVAILABLE` | No Kernel client env (`PDX_KERNEL_BASE_URL` + `PRODOCUX_BEARER_TOKEN`) |
| `KERNEL_RETRIEVAL_FAILED` | Kernel hop failed (retryable) |
| `ARTIFACT_TOO_LARGE` | Resolved artifact exceeds 32 MiB retrieval policy (non-retryable) |

## Kernel hop

Adapter `ProDocuXHttpClient.retrieve_artifact()` →
`POST /v1/artifacts/retrieve` with `prodocux_artifact_retrieve_v1`.

Worker and internal HTTP share the same env vars as Phase 1:

- `PDX_KERNEL_BASE_URL`
- `PRODOCUX_BEARER_TOKEN`
- Optional mTLS: `PRODOCUX_CLIENT_CERT`, `PRODOCUX_CLIENT_KEY`, `PRODOCUX_CA_CERT`

## Schemas

- `schemas/pdx_internal_job_artifact_retrieve_v1.schema.json`
- `schemas/pdx_internal_job_artifact_content_v1.schema.json`

Kernel companion schemas live in `prodocux/docs/phase3/schemas/`.

## Compare / verify worker

Operations `compare_normalized_profiles` and `verify_evidence` are expensive
T1 paths and **must** execute through the Engine worker (not Core→Kernel sync).

1. Staging bytes = Kernel request JSON (`application/json` payload)
2. Adapter calls `compare/normalized-profiles` or `verify/evidence-bundle`
3. Worker persists structured JSON to derived store as **`processing_output`**

Derived artifact basenames:

- `normalized_diff_result.json`
- `evidence_bundle_result.json`

Frozen `pdx_internal_job_status_v1` is unchanged. Result bytes, when needed,
use the frozen retrieval contract above.

## Retrieval limit layering

Opaque identity `size_bytes` may be up to **100 MiB** in metadata schemas.
Retrieval wire policy is **32 MiB** (Kernel) with stable `ARTIFACT_TOO_LARGE`.
See `prodocux/docs/phase3/README.md`.
