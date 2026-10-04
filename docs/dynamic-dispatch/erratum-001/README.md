# ERRATUM-001 parent workflow authority candidate

Status: bilateral review candidate; not frozen; implementation unauthorized.

This additive candidate closes the parent-authority gap discovered after the
ER-002 dispatch envelopes were frozen. It adds five v2 parent-workflow schemas
without changing any v1 workflow schema or any of the 14 frozen ER-002 schema
bytes.

The v2 plan introduces a first-class `dispatch` step, explicit dispatch attempt
and runtime budgets, and three dispatch artifact-edge roles. State and receipt
v2 retain the existing `RunState` vocabulary while adding durable dispatch
counters and the immutable dispatch-receipt relationship.

The fifth schema is an additive route mapping. It preserves the existing
twelve operations and paths, but selects v1 or v2 wire schemas exclusively
from the workflow contract version stored at creation. The caller cannot
select or change that version.

`semantic-validator.mjs` verifies plan topology, budgets, policy/plan binding,
state counters, artifact identity digests and dispatch receipt edges.
`verify-ajv-strict.mjs` compiles all five schemas under AJV 2020-12 strict mode.

No runtime, migration, route, package or version change is authorized by this
candidate.
