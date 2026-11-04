# External-operation implementation

Available in `pdx-artifact-engine==0.3.0a13`. Public distribution bytes and
clean installation have been verified.

The implementation extends RuntimeWorkflowStore, using the same SQLite
database, WAL and BEGIN IMMEDIATE boundary as the existing workflow and dispatch
services. No frozen contract file has been changed. The document-freeze record
continues to describe the historical contract freeze.

The runtime implements the additive v3 parent contracts and packaged copies of
the frozen schemas. V1/v2 jobs retain their handlers. A bound dispatch step
cannot use ordinary dispatch activation to bypass external-operation authority.
The step must have a registered frozen dispatch policy and an immutable decision
whose arguments equal the independently verified, schema-checked payload.

## Deployment composition and trust

Compose ExternalOperationService with a RuntimeWorkflowStore, registered authority
configurations, artifact resolver, payload schemas, adapters, dispatch registry
and independent observation verifier. The artifact resolver must enforce storage
authorization and full artifact identity. The verifier must authenticate provider
or manual evidence; a caller's outcome or assertion is never sufficient.

For HTTP, make_server accepts external_service_factory and
external_principal_bindings. The factory receives the existing workflow store and
dispatch service. Bearer credentials map to immutable Principal objects supplied
by deployment configuration, not request JSON or headers asserting a name. The
profile is fail-closed without registered principals/adapters. Legacy CLI startup
does not invent these deployment-specific authorities or provider integrations.

Activation allocates the operation, consumes approval use, reserves the subject
and increments parent counters in one transaction. Exact retries recover it;
changed bindings conflict. The original approval is never rewritten. One submit
permit persists the provider key and possibly_submitted intent before network
work. Trusted workers call service.submit; there is no public resubmit endpoint.
Registered adapters own network timeouts and credentials. Submit exceptions leave
an unknown result and never produce proof of nonexecution.

## Recovery and evidence

Reconcile reserves one query claim and parent counters before calling a registered
read-only adapter outside the transaction. Recovery never calls submit. A crashed
or timed-out query retains its charged reservation; a stale response is fenced.
The query runtime counter conservatively charges the full reserved call allowance
(at most 30 seconds), including on success. This prevents worker death from
resetting the 600-second budget; it is not CPU-time telemetry. The scheduling
horizon and observation/evidence bounds are also enforced. An unproven lookup
profile remains manual_only; no retry changes the provider key.

Manual cases are registered only through the trusted service API, one per
operation. Wire observations cannot open a case. The independent verifier must
confirm current manual authority and, for nonexecution, definitive proof and
termination of the previous submitter. Manual resolution cannot authorize resend.

Every snapshot is an immutable CAS artifact with sequence and previous digest.
Identical observations replay; changed content under the same identity conflicts.
Contradictory confirmed evidence appends a conflict without replacing the original
confirmation or terminal parent bytes. A parent receipt binds the prior snapshot;
one later snapshot attaches the immutable parent receipt, without a digest cycle.

All v3 parent terminal receipt paths recheck current external-operation authority
in the terminal transaction. If a successful step receives conflicting confirmed
evidence before the parent finishes, the parent becomes blocked with
EXTERNAL_OUTCOME_UNRESOLVED. Full parent receipt semantics are checked against
actual CAS bytes before freezing. Conflicts after terminalization append evidence
without changing the historical parent receipt.

## Review tests and limits

The new runtime tests use real SQLite connections, separate spawned processes,
countable fake-provider persistence and a worker killed after provider acceptance.
Recovery must preserve one submission and query instead. Tests also cover
principal isolation, expiry/revocation, exact/material retries, manual evidence,
query budgets, late/conflicting observations, HTTP and parent cancellation.
They do not demonstrate any live provider, OAuth, webhook signature implementation
or distributed exactly-once effects. A deployment must supply and qualify those
adapters/verifiers; the core does not make a payment call by itself.

Deployment qualification of provider adapters and verifiers remains separate.
