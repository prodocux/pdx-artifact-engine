# Runtime dependency security (working tree)

This overlay does not rewrite frozen compatibility v1/v2/v3 or the published
`0.3.0a3` release record. It records the unpublished image recipe that
replaces the Phase 5 scan pin (`1925f68` Engine image).

## Application packages

Engine runtime depends on `jsonschema` only. The Phase 5 Engine findings were
`pip 24.0` and `setuptools 79.0.1` from the Python base image after
`pip install .`.

## Packaging tools

The production `Dockerfile` uninstalls `pip` and `setuptools` after install.
Local development and wheel builds still use `setuptools>=77` from
`[build-system]`.

Farpals image builds that still use `docker/pdx-engine.Dockerfile` must adopt
this uninstall step (or build with this repository `Dockerfile`) before the
next dependency scan. Do not rebuild the previously pinned image tag in place.

## Out of scope

OS/base-image packages, WordPress/plugins, and future advisories are not
cleared by this overlay. Absence of a failing functional test is not a
waiver.
