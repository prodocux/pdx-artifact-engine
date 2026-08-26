# Engine Phase 0 contracts

Additive paper contracts for the private job interface, TTL staging, and the
Engine→Kernel `artifact://` identity profile. They are **not** a public API,
**not** listed in frozen compatibility v1/v2/v3, and **not** implemented by
this directory.

See `docs/adr/ADR-0002-phase0-private-job-staging-profile.md` and
`docs/PHASE0_DECISIONS.md`.

| Path | Authority |
| --- | --- |
| `e05-route-mapping.json` | E-05 method/path → request, success, HTTP status, error schema |
| `fixture-digest-manifest.json` | SHA-256 of contract files (raw UTF-8 bytes, LF) |
| `schemas/` | JSON Schema Draft 2020-12 |
| `examples/` | `*.request.json` are requests; `job_status.*` are success envelopes |
