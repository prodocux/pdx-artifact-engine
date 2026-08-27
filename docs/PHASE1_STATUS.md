# PDX Phase 1 — freeze

Status: **COMPLETE** (2026-08-27).

## Formal record

PDX Phase 1 complete for E-05, worker execution, opaque artifact
identity, filesystem persistence, readiness, bearer and production
mTLS profiles. Farpals interoperability is verified under the
self-hosted private bearer profile. Verified artifact-byte retrieval
and WordPress Media Library delivery are deferred to Phase 3.
Production host orchestration and Farpals client-certificate wiring
remain deployment-owned prerequisites.

WebMCP remains Farpals-owned. Frozen Phase 0 pins and E-05 wire are
unchanged.

## Freeze SHAs

| Repo | Role | Phase 1 freeze |
| --- | --- | --- |
| `prodocux` | Kernel | recorded after Kernel Phase 1 commit |
| `pdx-artifact-engine` | Engine | recorded after Engine Phase 1 commit |

Phase 0 baselines (still valid):

- Engine Phase 0: `b49fc89d4962e12e09f353d3721b2c459963368e`
- Kernel Phase 0: `60c306a7d418cce537ca54fdd000117ae08dec6e`

## Landed slices

### Kernel (`prodocux`)

- Auth profiles: `PRODOCUX_AUTH_PROFILE=self_hosted|production_mtls`
- Bearer: `PRODOCUX_BEARER_TOKENS`
- `GET /health`, `GET /ready` (`auth_profile_ok`)
- Filesystem sink / intake / derived stores
- Sidecar `Dockerfile`

### Engine (`pdx-artifact-engine`)

- E-05 create / get / cancel / reconcile (+ schema validation, body ceiling)
- Worker: `intake_document`, `render_artifact`
- Additive `GET …/result` and `GET …/results` (kind↔URI bound)
- Auth profiles: `PDX_ENGINE_AUTH_PROFILE=self_hosted|production_mtls`
- Optional worker client TLS env for Kernel hop

## Farpals docking

See [`PHASE1_FARPALS_DOCK.md`](PHASE1_FARPALS_DOCK.md).
Verified E2E today: **self_hosted + loopback + bearer**.
`production_mtls` profiles exist on PDX; Farpals client cert wiring is
deployment-owned before production cutover.

## Deployment backlog (not PDX Phase 3)

- Host compose / process supervision
- Farpals production mTLS client certificate support
- Trusted-edge guarantee: external clients must not inject
  `SSL_CLIENT_VERIFY` (or equivalent); Engine/Kernel stay private

## Deferred to Phase 3

- Verified `artifact://…` byte retrieval
- Size / digest / MIME recheck after download
- WordPress Media Library ingestion
- Final attachment / publication binding
