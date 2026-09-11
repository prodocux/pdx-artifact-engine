# Engine 0.3.0a8 and Media 0.2.0a3 release candidates

Status: unpublished. Engine a8 supersedes the failed publication attempt at
public tag `v0.3.0a7`; that tag is retained as an audit record and is not a
PyPI release or downstream pin. Media `0.2.0a3` has not been published.

The conformance implementation is unchanged from FSF-qualified commit
`47de6c2e341f6d5809be931f161e889b7990466e`. This follow-up changes only the
Engine package version, release documentation, and the stale release-version
test. Media remains `0.2.0a3`.

Engine a8 provides the additive v2 check-update binding while retaining a5/a6
v1 workflow wires. Media a3 implements the frozen technical profile and
conformance evaluator. `not_evaluated` remains solely a Media report
disposition and is not an Engine `RunState`.

Frozen schemas, FSF's existing parser, P0a, and FSF-M1 remain outside this
release-only correction. Publication requires a clean Git export of the final
candidate commit to pass the complete tests, clean-install verification,
package metadata checks, and GitHub asset digest verification.
