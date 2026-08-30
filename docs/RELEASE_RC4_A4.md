# Coordinated rc4 / a4 release candidate

Prepared: 2026-08-30. Status: versioned candidate; NOT published or approved
for official Farpals pin promotion.

## Versions and scope

| Component | Candidate version | Planned tag | Repair baseline |
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

Final SHAs cannot be embedded into their own source commits. They are supplied
in the coordinator's external release handoff, together with built image IDs,
package hashes and verification results. Later evidence-only commits do not
replace those source pins.

## Security and verification

The earlier scoped OS acceptance is in Kernel
`docs/SECURITY_OS_ACCEPTANCE.md`. Its recorded candidates are historical;
this versioned cut must verify the same base/OS package inventory and runtime
conditions before claiming that the existing risk decision applies. Remaining
OS advisories are not a clean-OS certification. A changed dependency inventory
requires a new application scan; changed OS packages require reassessment.

Before publication: full upstream suites, clean wheel installs, package checks,
exact-source builds, external runtime inventory/advisory checks, and final
Farpals candidate integration are required. Never reinstall pip into the
runtime to prepare audit or test tooling.

Farpals must use a separate final-candidate pins file, then verify source
revisions, upstream suites, scans and PHP/Docker E2E. Its Core, WordPress,
plugin and operational risk decisions remain Farpals-owned.

## Publication boundary

The release coordinator owns GitHub/tag/PyPI publication. These versioned
commits alone do not authorize publication. Do not move previous tags, rebuild
previous public assets, or attach Media a2 assets to the Engine a4 Release.
After publication, record public URLs, exact file hashes and provenance in a
new release record; do not rewrite historical records.

