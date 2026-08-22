# ADR-0001: Preserve frozen contracts through additive versioning

Status: Accepted for implementation

Date: 2026-08-22

## Context

PDX Artifact Core 0.2.0a2 and ProDocuX 0.2.0 share a release-candidate
compatibility manifest. Existing applications pin those versions and schema
digests. Durable execution additions must not redefine an already published
execution, tool, verifier, checkpoint, approval, or artifact contract.

Commit `61cff57` made three PDX schema digests cross-platform by enforcing LF
endings for JSON. The synchronized v1 manifest SHA-256 is
`0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303` in
both repositories.

## Decision

1. `pdx_prodocux_compatibility_v1.json` is immutable.
2. Tests pin its byte digest and validate only schemas explicitly listed by
   that manifest.
3. Existing v1 schema files and public primitive signatures are never edited
   for additive capability work.
4. Durable snapshots, step receipts, repository ports, and later external
   operation records use new contract files and additive exports.
5. The next coordinated release publishes
   `pdx_prodocux_compatibility_v2.json`; v1 remains packaged as historical
   compatibility evidence.
6. A change that cannot be represented additively receives a new contract
   version instead of changing v1 in place.

## Consequences

- Existing Core and Engine consumers retain their exact pinned surface.
- Adding a new packaged schema does not mutate v1 or make the v1 test compare
  against unrelated future schemas.
- Active-release tests must target v2 once populated.
- Product persistence, provider clients, scheduling, and domain policy remain
  outside Core.
