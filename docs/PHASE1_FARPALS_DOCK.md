# PDX ↔ Farpals Phase 1 dock handoff

Status: **P1 dock complete** (`materialized_source` / `processing_output` + auth profiles)

Date: 2026-08-27

## What PDX now exposes (consume this)

Private Engine façade (reference transport HTTP):

| Method | Path | Success |
| --- | --- | --- |
| POST | `/internal/v1/jobs` | 202 + `pdx_internal_job_status_v1` (`pending` + `staging`) |
| GET | `/internal/v1/jobs/{job_id}` | 200 + status |
| POST | `/internal/v1/jobs/{job_id}/cancel` | 200 + `cancelled` (staging deleted) |
| POST | `/internal/v1/jobs/{job_id}/reconcile` | 200 + converged status |
| GET | `/internal/v1/jobs/{job_id}/result` | 200 + `pdx_internal_job_result_v1` |
| GET | `/internal/v1/jobs/{job_id}/results` | 200 + `pdx_internal_job_results_v1` |

Auth: `Authorization: Bearer <token>` when
`PDX_ENGINE_BEARER_TOKENS` is set **or**
`PDX_ENGINE_AUTH_PROFILE=self_hosted|production_mtls`.
`production_mtls` additionally requires a verified client certificate
(`SSL_CLIENT_VERIFY=SUCCESS` by default). `/health` and `/ready` stay public.

Body ceiling: `Content-Length` required; hard reject above Engine
`max_encoded_bytes` (44 739 244) + 64 KiB JSON margin with **413**
`BODY_TOO_LARGE` before any body read. Cancel/reconcile validate frozen Phase 0
request schemas and require `body.job_id == path job_id`.

### Exact `/result` contract (Farpals-stable single item)

Authority:

- Schema: `docs/phase1/schemas/pdx_internal_job_result_v1.schema.json`
- Example: `docs/phase1/examples/job_result.materialized_source.json`

`GET …/result` prefers `kind=materialized_source` when the job has multiple
result items. For `render_artifact` jobs (no intake source), it returns the
sole `processing_output`.

**`kind=materialized_source` means:** Kernel intake identity from
`POST /v1/intake/materialize` — **source bytes**, not extract/render output.

**`kind=processing_output` means:** Kernel-owned derived/render identity
(`artifact://derived/…`, `artifact://sink/…`, or `artifact://render/…`) —
**not** the intake source and not raw `content_blocks` JSON on the status wire.

Frozen `pdx_internal_job_status_v1` is unchanged and does **not** embed result.

### Exact `/results` contract (multi-kind list)

- Schema: `docs/phase1/schemas/pdx_internal_job_results_v1.schema.json`
- Example: `docs/phase1/examples/job_results.list.json`

Locked semantics (schema + service validation + contract tests):

| Rule | Behavior |
| --- | --- |
| kind ↔ URI | `materialized_source` → `artifact://intake/…` only; `processing_output` → `artifact://derived\|sink\|render/…` only |
| uniqueness | at most one item per kind |
| job binding | every item `job_id` MUST equal envelope `job_id` |
| order | non-semantic; consumers MUST select by `kind` |
| incomplete | `GET …/results` → 200 + `results=[]`; `GET …/result` → 404 `RESULT_NOT_READY` |
| bytes | never on status / projection / result envelopes |
| retrieval | opaque identity only; verified bytes / Media Library = **Phase 3** |

Intake URI always embeds unique `artifact_id`
(`artifact://intake/{artifact_id}/{basename}`) so same basenames do not collide.

Worker `intake_document` path:

1. Read Engine staging (ephemeral)
2. Kernel `POST /v1/intake/materialize` → `artifact://intake/{id}/…`
3. Kernel `POST /v1/intake/extract-blocks` with `document_artifact` (no b64)
4. Kernel `POST /v1/artifacts/derived` → `artifact://derived/{id}/content_blocks.json`
5. Persist result list; `GET …/result` still returns `materialized_source`

Worker `render_artifact` path:

1. Staging bytes = Kernel render request JSON
2. Kernel `POST /v1/render/artifact` (artifact delivery)
3. Persist `processing_output` for `GET …/result` and `GET …/results`

## Wire authority

- Phase 0 create/status/cancel/reconcile schemas remain authoritative.
- Phase 1 `/result` and `/results` are additive; Farpals may pin them.
- SHA-256 is bare 64-hex on the Engine hop.

## Explicit Farpals stop-line

- WordPress auth, MCP/WebMCP, public job projection, audit correlation
- Mapping WP attachment → Engine `subject.binding_id` / `revision`
- Projecting `materialized_source` / `processing_output` into Media
- Host-side enqueue scheduling and `display_status` (`queued` copy only)

## Deployment backlog (Farpals / host-owned — not PDX Phase 3)

- Host compose / process supervision
- Farpals `PdxEngineClient` client-certificate wiring before
  `production_mtls` cutover
- Trusted private edge: strip/forbid client-injected
  `SSL_CLIENT_VERIFY` (or equivalent); Engine/Kernel must not be
  publicly exposed

## Deferred to Phase 3 (PDX + Farpals delivery)

- ~~Verified retrieval of `artifact://derived|sink|render/…` bytes~~ → **frozen** (see Phase 3 SHAs)
- ~~Size / digest / MIME recheck~~ → Kernel `POST /v1/artifacts/retrieve`
- WordPress Media Library ingestion and attachment / publication binding (Farpals slice 2)

## Phase 3 freeze SHAs (verified bytes — unblocks Farpals publish)

- Kernel: `f6cee0d`
- Engine: `fb3aa6d`
- Routes: `POST /v1/artifacts/retrieve`, `POST /internal/v1/jobs/{job_id}/retrieve`

See [`PHASE3_STATUS.md`](PHASE3_STATUS.md) and `docs/phase3/README.md`.

## Pins (Phase 0, still valid)

- Engine freeze: `b49fc89d4962e12e09f353d3721b2c459963368e`
- Kernel freeze: `60c306a7d418cce537ca54fdd000117ae08dec6e`
- Do not mutate frozen compatibility v1/v2/v3 bytes

## Phase 1 freeze SHAs

- Kernel: `f5fc9516b36e0ca5fb105244a45799fc441c3a76`
- Engine: `a2cd14a166dd8b9985530d007731acdabf7cc19a`

See also [`PHASE1_STATUS.md`](PHASE1_STATUS.md).
