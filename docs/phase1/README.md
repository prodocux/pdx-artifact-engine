# Phase 1 additive contracts

These documents extend the private Engine surface **without** editing frozen
Phase 0 schemas (including `pdx_internal_job_status_v1`).

| Path | Authority |
| --- | --- |
| `schemas/pdx_internal_job_result_v1.schema.json` | Exact body for `GET …/result` and each `/results` item |
| `schemas/pdx_internal_job_results_v1.schema.json` | Exact body for `GET …/results` |
| `examples/job_result.materialized_source.json` | Intake source fixture |
| `examples/job_result.processing_output.json` | Derived/render output fixture |
| `examples/job_results.list.json` | Multi-kind list fixture |

## Result semantics

| `kind` | URI namespace (required) |
| --- | --- |
| `materialized_source` | `artifact://intake/{id}/{basename}` only |
| `processing_output` | `artifact://derived|sink|render/…` only |

### `/results` rules (service validation + contract tests)

1. At most **one item per kind** (max two items).
2. Every item `job_id` **MUST** equal envelope `job_id`.
3. Array **order is non-semantic** — consumers MUST select by `kind`.
4. Incomplete jobs: `GET …/results` → HTTP 200 with `results=[]`.
   Contrast: `GET …/result` → HTTP 404 `RESULT_NOT_READY`.
5. Bytes never appear on status, job projection, or result envelopes.
6. Opaque identity only — verified byte retrieval / Media Library ingestion
   remains **Phase 3** (not claimed ready in Phase 1).

`GET …/result` prefers `materialized_source` when present (Farpals-stable).
