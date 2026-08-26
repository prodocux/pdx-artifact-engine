# Engine Phase 0 decision record

Status: **Phase 0 paper freeze** — Phase 1 production implementation is not
authorized by this document.

Date: 2026-08-26

## Authority

| Surface | Owner | Evidence |
| --- | --- | --- |
| Neutral operation / plan / tool request | Engine Core | `pdx_execution_plan_v1`, `pdx_tool_request_v1` |
| `RunState` | Engine Core | `pdx_artifact_core.state.RunState` |
| Events / checkpoints / snapshots | Engine Core | `pdx_run_event_v1`, workflow checkpoint, `pdx_run_snapshot_v1` |
| External operations | Engine Core | `pdx_external_operation_v1` |
| Publication receipts | Engine Core | `pdx_publication_receipt_v1` |
| Generic artifact storage identity | Engine Core | `artifact_storage_identity.v1` (unchanged; may include `gs://`) |
| ProDocuX hop identity profile | Engine Phase 0 | `docs/phase0/schemas/pdx_prodocux_artifact_identity_profile_v1.schema.json` |
| Private job interface E-05 | Engine Phase 0 | `docs/phase0/schemas/pdx_internal_job_*.schema.json` |
| E-05 route mapping | Engine Phase 0 | `docs/phase0/e05-route-mapping.json` |
| TTL source staging | Engine Phase 0 | `docs/phase0/schemas/pdx_staging_handle_v1.schema.json` |
| Kernel `/v1` | Kernel | not owned here |

## Closed Phase 1 blockers (Engine slice)

1. Topology: all asynchronous product work enters Engine. Direct Kernel calls
   are deterministic tests only.
2. Neutral schema authority: Core contracts stay in this repository; Kernel
   keeps `/v1`; Phase 0 files do not become a third universal schema authority.
3. Canonical run state: public machine values are the `RunState` enum.
   `queued` is not a machine state. Worker claim/lease/attempt are operational
   fields, not `RunState` members.
4. Private authentication: rotatable bearer + private network for the first
   self-hosted profile; production mTLS without changing the job contract.
5. E-05 is required, not optional.
6. Byte path: bounded ephemeral upload, immediate hash, Engine TTL staging,
   durable state stores handle + digest + size + media type only;
   `artifact://` only on the Kernel hop; no shared writable volume with
   WordPress or Kernel output.

## Host consumer wire format

These Engine schemas are the **sole E-05 wire contract**. External host
consumer drafts (including Farpals `engine-job-submit.consumer.v1`) must be
rewritten onto this format during reconciliation. PDX will not add a second
wire format and will not rename fields to match host drafts.

Hosts must send Engine field names and encodings:

- `schema_version`, `job_id`, `request_id`
- `subject.binding_id` and `subject.revision`
- `deadline_at` (RFC3339)
- `payload.filename`, `payload.content_b64`, `payload.decoded_size_bytes`
- SHA-256 as a bare 64-character lowercase hex string (no `sha256:` prefix)
- accepted jobs project `staging` (`pdx_staging_handle_v1`)

A host may apply stricter decoded-size or TTL policy than Engine maxima.
That host policy is not an Engine ceiling. If a host documents 10 MiB or a
900 second TTL, label it host intake policy. Engine maxima remain 32 MiB
decoded and 3600 seconds default TTL (`docs/phase0/limits.json`).

## E-05 surface (frozen)

```text
POST /internal/v1/jobs
GET  /internal/v1/jobs/{job_id}
POST /internal/v1/jobs/{job_id}/cancel
POST /internal/v1/jobs/{job_id}/reconcile
```

Machine-readable mapping: `docs/phase0/e05-route-mapping.json`.

| Method | Path | Request schema | Success | Error |
| --- | --- | --- | --- | --- |
| POST | `/internal/v1/jobs` | `pdx_internal_job_create_v1` | 202 + `pdx_internal_job_status_v1` | 400/409 + `pdx_internal_error_v1` |
| GET | `/internal/v1/jobs/{job_id}` | none | 200 + `pdx_internal_job_status_v1` | 404 + `pdx_internal_error_v1` |
| POST | `/internal/v1/jobs/{job_id}/cancel` | `pdx_internal_job_cancel_v1` | 200 + `pdx_internal_job_status_v1` | 404/409 + `pdx_internal_error_v1` |
| POST | `/internal/v1/jobs/{job_id}/reconcile` | `pdx_internal_job_reconcile_v1` | 200 + `pdx_internal_job_status_v1` | 404 + `pdx_internal_error_v1` |

`examples/job_cancel.request.json` and `examples/job_reconcile.request.json`
are **requests**. Success bodies are `job_status.*` envelopes. Cancel/reconcile
do not use a second success schema.

## Ephemeral payload ceilings

Cited from Kernel extract-blocks (`32 MiB` decoded). Live Kernel operations may
be stricter; Engine must fail closed when Kernel capabilities are lower.

| Limit | Value |
| --- | --- |
| max decoded bytes | `33554432` |
| max encoded bytes (base64) | `44739244` |
| default staging TTL | `3600` seconds |
| max staging TTL | `86400` seconds |
| staging directory mode | `0700` |
| documented staging root | `/var/lib/pdx-engine/staging` |

Allowed media types and basename suffixes are in
`docs/phase0/limits.json`.

## Staging lifecycle

- Bytes exist only on Engine-owned TTL filesystem staging after accept.
- Durable job/run records store `pdx_staging_handle_v1` only.
- Restart recovery: if the handle exists and TTL has not expired, resume;
  if bytes are missing, fail closed with a retryable or terminal code per
  deadline, never rewrite a completed receipt.
- Terminal `completed`, `completed_with_review`, `failed`, `blocked`,
  `cancelled`, and `timed_out` delete staging bytes.
- TTL expiry deletes staging bytes and does not create a second artifact or
  receipt.

## Frozen compatibility (must remain byte-identical)

| File | SHA-256 |
| --- | --- |
| `compatibility/pdx_prodocux_compatibility_v1.json` | `0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303` |
| `compatibility/pdx_prodocux_compatibility_v2.json` | `c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e` |
| `compatibility/pdx_prodocux_compatibility_v3.json` | `9591ab363472db78efb64265e3050fa4626be43783f848d0888e732898486d2b` |

Published distribution baseline: Engine `0.3.0a2` tag commit
`eba0d21ba665720a88546132f4779b4da6eb3beb`. v3 implementation pin remains
`37e89752560b22dc8724d470dce96187f19e3f98`.

Hackathon / prior coordinated releases remain compatible because Phase 0
adds only `docs/phase0/**` and tests. It does not edit frozen compatibility
manifests, packaged Core schemas, HTTP `/v1`, or adapter runtime. Phase 1
must stay additive on the same rule (ADR-0001). Wheels package
`pdx_artifact_core/schemas/*.json` only; Phase 0 paper files are not shipped
as Core contracts.

Fixture digests: `docs/phase0/fixture-digest-manifest.json`. Algorithm: SHA-256
of each listed file's raw UTF-8 bytes as stored (LF JSON, no re-encoding).
The manifest file itself is excluded from the hashed set.

## Working-tree SHA checklist

- [x] Frozen compatibility v1 SHA-256 `0b860fc0…1303` (test-enforced)
- [x] Frozen compatibility v2 SHA-256 `c301aba7…378e` (test-enforced)
- [x] Frozen compatibility v3 SHA-256 `9591ab36…6d2b` (test-enforced)
- [x] Phase 0 fixture digest manifest present (`docs/phase0/fixture-digest-manifest.json`)
- [ ] Phase 0 contract commit SHA recorded after the contracts commit

## Explicitly out of Phase 0

- SQLite repositories, worker, HTTP façade, adapter runtime changes.
- Any edit to frozen compatibility JSON bytes or to
  `artifact_storage_identity.v1.schema.json`.
- WordPress, WooCommerce, OAuth, or Farpals types in Engine schemas.
- `adapters/LICENSE` is unrelated untracked work and is not part of Phase 0.

## Phase 0 exit checklist

- [x] Neutral operation envelope, `RunState`, events, checkpoints, external
      operations, receipts, and generic artifact identity remain Engine-owned.
- [x] E-05 private routes frozen.
- [x] Ephemeral payload ceilings, MIME list, deadline, TTL, hash-before-accept,
      durable handle-only state, and no request-body logging frozen.
- [x] Engine-owned TTL staging root/mode/restart/cleanup frozen; no shared
      writable volume with the application host or Kernel output.
- [x] Engine→Kernel profile is `artifact://` only.
- [x] Neutral fixtures, negatives, and bridge mappings added.
- [x] Frozen compatibility v1/v2/v3 bytes are tested unchanged.
- [x] E-05 route → request/success/error schema and HTTP status mapping.
- [x] Fixture digest manifest and canonical hash rule.
- [ ] Maintainer records Phase 0 commit SHA after the contracts commit.
- [x] `adapters/LICENSE` is not part of this Phase 0 delivery.
