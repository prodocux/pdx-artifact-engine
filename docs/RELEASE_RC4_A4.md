# Coordinated rc4 / a4 published prerelease

Published: 2026-08-30. Status: GitHub and PyPI publication completed.
Farpals official pin promotion and production approval remain separate gates.

## Versions and scope

| Component | Published version | Tag | Historical repair baseline (not a release pin) |
|---|---|---|---|
| ProDocuX Kernel | 0.3.0rc4 | v0.3.0rc4 | 120cbd3f1ad6fe2fb8a9263ce9000bcaaba043bb |
| PDX Artifact Engine | 0.3.0a4 | v0.3.0a4 | c82d38f8d1536beb2a412241d9348d1c6ffa5651 |
| PDX Adapter Media | 0.2.0a2 | unchanged | do not republish |

Kernel includes pypdf 6.15.0, FastAPI 0.141.1 and Starlette 1.6.0. Both
runtime images uninstall pip/setuptools. Engine a4 is a coordinated version
and packaging/image cut, not a new application behavior or wire contract.

Relative to the repair baselines, this cut changes version metadata, version
assertions, release documentation and the explicit Docker base reference only.
Historical compatibility v1/v2/v3 and release rc2/a2 and rc3/a3 records remain
unchanged. Do not replace repair evidence with claims about the final release.

## Build boundary

Both Dockerfiles pin the previously reviewed base:
`python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6`.

Use exact `git archive` exports of the coordinator's final 40-hex release
SHAs as build contexts, and each exported repository's own Dockerfile.
Do not build a dirty working tree with `COPY . .`. Do not overwrite old
image tags. Set `org.opencontainers.image.revision` to the exported full SHA.

Release source pins (not later documentation/evidence commits):

- Kernel: `44e29bd64089279910f4d78a0a36cf3fdb953cc7`.
- Engine: `2acdebf73134ed106a636ed38e1ecce6596eb751`.

Public URLs, exact file hashes and workflow IDs are in
[`pdx_prodocux_release_rc4_a4.json`](../compatibility/pdx_prodocux_release_rc4_a4.json).
Later documentation/evidence commits do not replace these source pins.

## Security and verification

The earlier scoped OS acceptance is in Kernel
`docs/SECURITY_OS_ACCEPTANCE.md`. Its recorded candidates are historical;
this versioned cut verified the same base/OS package inventory and runtime
conditions, preserving applicability of that scoped risk decision. Remaining
OS advisories are not a clean-OS certification. A changed dependency inventory
requires a new application scan; changed OS packages require reassessment.

The release gates passed: exact-source Kernel tests (231 passed, 10 skipped),
Engine tests (197 passed), clean wheel installs, package checks, exact-source
builds, external application inventory/advisory checks, and final Farpals
candidate integration at `6acf2a6851fb5b815248594dc65ce9eddfb579f8`.
The ten Kernel skips are optional private/historical fixtures, not new skips.
Never reinstall pip into the runtime to prepare audit or test tooling.

The final application scans covered Kernel 35 / Engine 8 packages with zero
advisory matches and zero skipped packages. Both OS inventory hashes matched
`87cf43e01449a03647b3ce853ca35b531fc336bef7b7572993983bcfbe49d69f`.
This was inventory equivalence to the accepted OS baseline, not a new clean
OS scan: 79 advisory matches / 14 unique HIGH or CRITICAL remain conditionally
accepted. The recorded HTTP/non-QUIC, no-FTS5, non-root and no-TTY conditions
still apply.

Farpals must use a separate final-candidate pins file, then verify source
revisions, upstream suites, scans and PHP/Docker E2E. Its Core, WordPress,
plugin and operational risk decisions remain Farpals-owned.

## Publication boundary

The release coordinator completed the authorized GitHub/tag/PyPI publication.
Both release workflows succeeded after protected `pypi` approval. Engine's
`publish-media` job was skipped; Media remains `0.2.0a2`.

All four public GitHub/PyPI file hashes and downloaded bytes match the approved
assets. For each file, the PyPI Integrity API publisher, statement subject digest,
and certificate source SHA/tag match the release. This evidence check is not
independent Sigstore signature verification.

A fresh environment installed both exact versions from PyPI. Dependency
consistency (`pip check`), package versions/imports, packaged schemas,
lazy API store initialization, and `JobService` construction/cleanup passed.

The post-publication documentation/record follow-up adds three regression tests
per repository: Kernel 234 passed / 10 skipped, Engine 200 passed. These counts
describe the follow-up tree, not a rebuilt or retagged release artifact.

Do not move release tags, rebuild public assets, or rewrite historical records.
The new published overlay is byte-identical across both repositories.
Farpals official pins/compose were not changed by this publication. Its remaining
WordPress risk, plugin review, alert-delivery and full-storage disaster-recovery
gates are not waived by upstream publication.
