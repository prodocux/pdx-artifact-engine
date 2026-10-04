# ER-002 ERRATUM-001 contract freeze

Status: frozen on 2026-10-04. Production implementation is authorized; a
release version and publication remain separately unauthorized.

This freeze accepts the five-schema ERRATUM-001 surface after bilateral
review. `erratum-freeze.v1.json` is the authoritative manifest. It adds four
v2 parent-workflow contracts and one v2 route mapping while preserving the
original ER-002 freeze, every parent-workflow v1 schema and the v1 route
mapping byte-for-byte.

Runtime and storage work must implement these frozen semantics without adding
a second workflow authority. Any schema or semantic change requires a new,
additive erratum. This freeze does not assign a package version, authorize a
tag, publish a wheel or authorize downstream adapter development.
