# Governed external-operation contract

Status: frozen document contract. This profile is not available in the published
runtime. Existing workflow, dispatch and reference helper behavior is unchanged.

## Authority and operation identity

The profile extends existing durable workflow/dispatch authority through additive
parent v3 contracts. It does not define another public workflow RunState enum.
Registered authority/tenant namespaces bind controller, issuer, adapter, manual
reconciler, supervisor and reader identities supplied by authenticated transport.
Request bodies cannot establish those identities or create their own authority.

A subject is persistently unique across workflows/runs in its authority/tenant
namespace. The operation digest is JCS SHA-256 of the immutable specification:
typed payload artifact/schema, sorted unique evidence identities, registered
provider profile/revision/digest, account alias, environment and executor/policy
identity. Referenced bytes, schema and provenance must be independently verified.
Credentials stay outside plans, digests, receipts and this profile.

One immutable approval authorization establishes at most one operation. Engine
records use separately and atomically enforces subject and authorization uniqueness.
Exact retries recover the same operation. Material changes conflict. Cross-key
equivalent retries cannot reparent an operation or reset its counters. Different
legitimate obligations may use different subjects with identical payloads; the
application owns business duplicate detection.

Provider key is persisted before submission and cannot be overridden by a caller.
Used subjects remain reserved, including after confirmed_not_executed. A later
lawful obligation requires a new subject and approval; uncertainty cannot be
bypassed by replacing an unresolved operation. Initial profile never resubmits
with either the same or a new provider key.

## Approval, submission and recovery

New activation and pre-submit permit validate principal, operation binding,
expiry and current issuer epoch/freshness. Freshness is at most 30 seconds and
must contain Engine authoritative UTC time without backdating. Revocation
linearizes when committed to Engine authority; this does not imply immediate
awareness of an undelivered remote revocation. Exact read recovery after expiry
does not grant a new execution permit.

At most one submit permit persists intent/key/fence before adapter submission;
possibly_submitted is conservative, even if a crash occurs before network send.
No network call holds the persistence transaction. Local worker fencing does not
undo a remote side effect. Exceptions, timeouts, failed output schemas and absent
responses never prove provider nonexecution. Exactly-once external effects are
not claimed.

Only a provider demonstrated to query by the persisted client key may use
query_only recovery. Otherwise register manual_only. Query uncertainty, not_found,
lookup failure and retention expiry remain blocked; there is no implicit submit.
Provider access, signature verification and secrets belong to registered adapters.

Automatic limits: 20 query calls, 600 seconds cumulative query execution,
86,400-second scheduling horizon, 64 observation records and 1 MiB evidence.
There is one trusted-control-plane-registered manual case per operation, capped
at 16 records/1 MiB. Observation requests cannot open cases. Exhaustion preserves
blocked uncertainty and reserved identity, never proves nonexecution.

## Observations and immutable receipts

Authenticated observations bind namespace, subject/operation/profile, account,
environment, provider-key digest, remote identity and full verified artifact
evidence. Identical replay is idempotent; changed content under the same identity
returns 409 OBSERVATION_CONFLICT without overwrite. New contradictory confirmed
evidence is appended and requires reconciliation; it does not replace historical
confirmation. Late pending/unknown facts cannot regress a confirmed outcome.

Manual confirmed_not_executed requires independent authorized role, registered
case, definitive nonexecution proof and evidence that the old submitter cannot
later send. A manual resolution never authorizes resubmission of that operation.

Receipt snapshots bind immutable identity, activation/use, submission facts,
observations, budget consumption and previous digest/sequence. Parent terminal
receipt binds a pre-terminal operation snapshot. A later snapshot may attach that
parent receipt once, then cannot replace it. Parent terminalization forbids new
submit permits but leaves authorized bounded reconciliation and evidence append
possible without reopening the historical workflow or changing terminal bytes.

## Parent v3 and wire contracts

External-operation binding is allowed only on dispatch steps, retaining frozen
policy/static-plan requirements. Completed requires provider-confirmed success
with no unresolved conflicts. Allocated operations require an external-operation
receipt for every result. Pre-allocation failure records operation_allocated=false,
safe_error and no fabricated operation artifact. Ordinary dispatch receipt and
external-operation receipt profiles are mutually exclusive.

V3 adds external-call/query counters and a compatible error vocabulary. Operation
allocation counts once; queries have distinct call/counter reservations. Frozen
v1/v2 bytes and old job handlers remain unchanged. Stored workflow version, not
caller header choice, selects the response contract.

route-mapping.json specifies request/success references and HTTP/error semantics.
Reconcile requests cannot carry outcomes. Full artifact/deployment definitions are
referenced through local copies of required frozen resources. These copies are
verification dependencies, not changes to packaged runtime contracts. Draft URNs
in the accepted schema content remain stable identifiers of this frozen version.

## Verification

The pure reference validators require independent trusted context. Fixture flags
cannot substitute for production authentication, verified storage or provider
facts. The synthetic examples do not demonstrate persistence, concurrent workers
or actual provider calls. Real countable-provider/multiprocess crash tests remain
necessary for a future implementation.

In this directory, use requirements-contracts.txt and package.json dependencies,
set PDX_AJV_MODULE_ROOT to a local Node dependency directory and run
`python verify_contracts.py`. Normal repository pytest checks freeze hashes,
Draft 2020-12 schemas, local references and fixture shape without requiring the
semantic verifier's optional development dependencies. No sibling checkout,
private coordination record or network schema lookup is required.
