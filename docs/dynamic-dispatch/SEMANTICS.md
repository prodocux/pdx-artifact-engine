# Governed dynamic dispatch semantic rules

Status: negotiation draft; not frozen; implementation unauthorized.

JSON Schema validates document shape. The following rules are mandatory
cross-field semantics for the ER-002 draft and are intended to become executable
semantic-validator cases after bilateral review.

The executable draft authority is `semantic-validator.mjs`; its cross-runtime
vectors are `canonicalization-vectors.v1.json`. Neither file authorizes schema
freeze or production implementation.

## 1. RFC 8785 digest projections

Every digest below is lowercase SHA-256 over RFC 8785 canonical UTF-8 bytes.
Self-digest fields are excluded from their own projection.

Schema digests are the exception: they are SHA-256 over the authoritative raw
UTF-8 schema file bytes. No parse/re-serialization is allowed.

| Digest | Canonical input |
| --- | --- |
| deployment `identity_digest` | object containing `kind`, `bundle_name`, `bundle_version`, `bundle_digest`, `registry_revision`, `entrypoint_symbol` |
| `skill_definition_digest` | product-neutral frozen `SkillDefinition` projection agreed by schema; never Python object identity or bytecode |
| `allowed_tool_names_digest` | exact sorted `allowed_tool_names` array |
| `frozen_tool_definitions_digest` | exact sorted `allowed_tools` array, including deployment identity and schema/hook digests |
| `policy_digest` | complete Engine policy document excluding `policy_digest` |
| `arguments_digest` | exact bounded `arguments` object |
| `canonical_proposal_digest` | object containing `proposal_schema_id`, `proposal_schema_digest`, `tool_name`, `arguments` |
| `decision_receipt_digest` | complete decision receipt excluding `decision_receipt_digest` |
| `idempotency_key_digest` | the idempotency key string; the plaintext key is not placed in a terminal receipt |
| `idempotency_binding_digest` | object containing workflow job/step, source run/plan, decision receipt ID/digest, policy ID/digest/epoch and authenticated principal |
| `receipt_digest` | complete terminal dispatch receipt excluding `receipt_digest` |

Tool names and definitions must be sorted by tool name using RFC 8785 UTF-16
ordering before digesting. `allowed_tool_names` must exactly equal the ordered
list of names projected from `allowed_tools`. Duplicate names fail closed.

## 2. Policy authority

- Registration request fields are proposals. Engine derives status,
  registration principal/time and every digest.
- `caller_authority_id`, when present, must equal authenticated transport
  principal. It is never authoritative by itself.
- Workflow and step must exist, be active and name a dispatch step whose Run A
  plan and decision step match the request.
- Each deployment identity must resolve through the trusted deployment
  registry. A wheel/OCI digest is accepted only if the loaded executor is from
  that verified bundle. Injected executors require a registered deployment
  bundle; arbitrary callables are rejected.
- Registration is create-once for `(workflow_job_id, workflow_step_id,
  dispatch_policy_id, policy_revision_epoch)`. An exact replay returns the
  stored policy. A changed body conflicts.
- Revocation is compare-and-set on expected epoch and policy digest. It is
  idempotent only for the same revocation reason and resulting record.

## 3. Proposal bounds

Bounds are computed over the exact `arguments` value after strict I-JSON parse
and before executor invocation.

- The root object has depth 1. Entering an object or array increments depth by
  one. Scalars do not add another level. Maximum depth is 8.
- Every object is limited to 64 direct properties. The recursive sum of all
  object property counts is limited to 256.
- Every array is limited to 1,024 direct items.
- RFC 8785 canonical bytes for the complete arguments object are limited to
  65,536 bytes.
- A secret reference is a string whose entire value uses the separately frozen
  opaque secret-reference contract and begins with `secret-ref://`. At most 8
  values are allowed. Secret values, inline credentials and resolvable URLs are
  forbidden.
- Duplicate JSON keys, non-I-JSON numbers and unpaired surrogates fail before
  bounds evaluation.

Any violation yields `DISPATCH_PROPOSAL_BOUNDS_EXCEEDED`, invokes no executor,
allocates no Run B and publishes no executor artifacts.

## 4. Decision receipt ownership

For the default same-workflow path, Engine records the decision receipt directly
from the verified Run A result. No route allows a caller to submit that receipt.

The external import route is optional and accepts only a completed Engine Run A
manifest artifact plus a decision receipt whose manifest, run, plan, policy,
step, schema and proposal digests all verify. Importing arbitrary JSON or a
caller-computed proposal is forbidden. Exact import replay is idempotent;
different content for the same receipt identity conflicts.

## 5. Activation transaction

Authentication and authorization precede the transaction. The transaction then
validates, in order:

1. active parent workflow and matching dispatch step;
2. stored policy identity, status, epoch, expiry and digest;
3. stored terminal decision receipt and all workflow/run/step bindings;
4. proposal bounds and frozen input schema;
5. live deployment registry, tool definition and schema digests;
6. idempotency key binding;
7. available workflow budgets and absence of a conflicting active attempt.

Only after all checks pass may Engine allocate dispatch attempt, authoritative
activation and Run B identities. All allocations occur in one transaction.
Exact concurrent retry recovers those identities. Failure before allocation
does not increment attempt counters or consume an execution slot.

## 6. Run B output authority

Run B is synthesized by Engine from the stored decision receipt and frozen
policy. The caller cannot replace tool, arguments, schemas or output bindings.

Input schema is verified immediately before invocation. Output document and
artifact identities are verified against the frozen output schema and storage
before publication. Output-schema failure suppresses every executor output
artifact, even if files were written to a staging directory.

## 7. Terminal receipt matrix

| Status | Execution occurred | Run B | Receipt CAS | Output artifacts | Error required |
| --- | ---: | ---: | ---: | ---: | ---: |
| `completed` | true | yes | yes | verified only | no |
| `executed_output_invalid` | true | yes | yes | no | yes |
| `executor_failed` | true | yes | yes | no | yes |
| `cancelled` | phase-dependent | yes | yes | no | yes |
| `synthesis_failed` | false | activation yes, Run B absent | no | no | yes |
| every `rejected_*` | false | no | no | no | yes |

`completed` requires input and output schema verification, no error and no
reconciliation. Rejections require null activation/attempt/Run B identities and
an empty artifact list. `synthesis_failed` may have an authoritative activation
identity but has no Run B identity.

## 8. Cancellation and reconciliation

- `not_started`: `execution_occurred=false`, clean abort, external outcome
  `none`, reconciliation false.
- `running` subprocess/OCI: request graceful termination then bounded forced
  termination. Execution occurred. Reconciliation is true if termination is
  unconfirmed or external effects are possible.
- `running` in-process: cooperative cancellation only. It must never claim a
  killed process tree. Failure to acknowledge cancellation yields termination
  `termination_unconfirmed`.
- A frozen `idempotent_read_only=true` tool may set reconciliation false after
  confirmed termination/cooperative stop because it has no write effects.
  Merely naming a tool read-only is insufficient; the value is part of the
  frozen tool definition and deployment identity.
- Unknown external outcome is never converted to success by retry. Reconcile
  must recover authoritative external evidence or remain reconcile-required.

Policy revocation cannot rewrite completed receipts or delete verified
artifacts. A different epoch under an existing idempotency key conflicts rather
than creating another Run B.

## 9. Step projection

The read-only projection is recovery evidence, not a new workflow state. It may
show internal dispatch phase, policy identity, current activation identity,
terminal receipt identity and reconciliation requirement. It never exposes
idempotency plaintext, credentials, secret references, HMAC material or lease
tokens.

The parent runtime workflow state and receipt remain authoritative for workflow
completion and aggregate counters.
