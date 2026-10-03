# PDX governed dynamic dispatch counterproposal

Status: negotiation draft; not authoritative; implementation unauthorized.

## 1. Ownership model

PDX proposes one additive `dispatch` step profile owned by the existing durable
runtime workflow. A workflow plan identifies the dispatch step, its frozen
policy reference and its aggregate budgets. The profile coordinates two
ordinary static Engine runs:

1. Run A executes a registered decision skill and produces a bounded proposal.
2. Engine validates and records a decision receipt under the workflow step.
3. An authenticated control-plane activation atomically binds the receipt to
   the pre-registered policy and creates one dispatch attempt.
4. Engine synthesizes a static Run B plan containing the resolved registered
   tool and validated arguments.
5. Run B executes through the normal dispatcher. Engine validates outputs,
   records the dispatch receipt and adds verified artifact edges to the parent
   workflow receipt.

The workflow job and step remain the durable authority. `decision_recorded`,
`activated`, `executing` and similar labels are internal dispatch phases, not
public workflow states.

PDX proposes a new additive workflow plan/schema version for dispatch steps.
The frozen v1 workflow schemas and `pdx_execution_plan_v1` remain byte-identical.

## 2. Proposed contract surface

Names below are negotiation placeholders, not frozen schema IDs.

| Contract | Owner | Purpose |
| --- | --- | --- |
| dispatch policy | Engine | Immutable pre-Run-A authority and frozen tool definitions |
| decision receipt | Engine | Credential-free Run A proposal evidence |
| activation request | trusted control plane | References stored receipt and policy; contains no proposal |
| activation response | Engine | Authoritative dispatch attempt and Run B identity |
| dispatch receipt | Engine | Record-once terminal relationship and publication evidence |
| dispatch step projection | Engine | Read-only recovery view without credentials or lease tokens |
| dispatch error | Engine | Stable rejection and reconciliation codes |
| route mapping | Engine | Auth, HTTP and conflict semantics |

The existing workflow create/state/cancel/reconcile/receipt surfaces remain the
parent lifecycle. Dispatch-specific routes, if accepted, are subordinate to a
`workflow_job_id` and `workflow_step_id`; they cannot create an independent
workflow.

## 3. Policy registration

Policy registration must occur before Run A is claimable. The transaction
validates:

- authenticated control-plane authority;
- active workflow and matching dispatch step;
- workflow, plan, step and decision-skill identity;
- unique tool names and bounded allowlist size;
- tool definition, input/output schema and verification-hook digests;
- published distribution or deployment-bundle identity;
- registry revision and entrypoint symbol;
- policy epoch, expiry/revocation fields and canonical policy digest.

PDX counterproposal: a wheel or OCI digest is authoritative only when the
executor is actually loaded from that verified distribution/bundle. Explicitly
injected callables require a separately registered deployment bundle identity;
an arbitrary callable, module string or bytecode hash is insufficient.

## 4. Decision receipt

The decision receipt is generated only when Run A and its decision step are
successfully completed. It binds:

- workflow job, workflow step, Run A and source plan digest;
- decision step and attempt identity;
- bounded proposal schema ID/digest;
- tool name and canonical argument document/digest;
- policy ID, epoch and digest expected by the workflow plan;
- terminal Run A manifest identity and receipt digest.

The receipt contains opaque secret references at most. Secret values and
credential handles resolvable outside the trusted host are forbidden.

## 5. Activation and idempotency

Transport principal is authoritative. A body principal, when present, is only
an assertion and must match the registered transport identity.

The activation binding includes every material field other than schema version
and the per-request tracking ID: workflow/step, source run/plan, decision
receipt identity/digest, policy identity/digest/epoch and authenticated
principal. Engine computes its RFC 8785 SHA-256 digest.

One `(workflow_job_id, workflow_step_id, idempotency_key)` may bind exactly one
activation digest. Exact concurrent retries recover the same dispatch attempt
and Run B. A changed binding produces a separate rejection receipt and never
alters the authoritative activation.

The transaction validates policy status, step readiness, decision receipt,
live deployment registry and input schema before allocating the Run B identity.
Any failure leaves attempt counters, execution slots and Run B state unchanged.

## 6. Run B and schema enforcement

Engine, not the caller, derives Run B. Its tool step is populated from the
verified policy and decision receipt. Before invoking the executor, Engine
validates arguments against the frozen input schema and confirms the live
schema digest again.

After execution, Engine validates the bounded result against the frozen output
schema before registering output artifact identities. A schema-invalid,
failed, cancelled or unknown external outcome does not publish executor output
artifacts. It still produces a terminal dispatch receipt.

This profile does not retroactively change legacy direct `Dispatcher.run`
semantics. Whether schema enforcement later becomes a default dispatcher mode
is a separate compatibility decision.

## 7. Cancellation, revocation and reconciliation

- Before executor invocation: atomically cancel with `execution_occurred=false`.
- After invocation begins: request termination of the controlled process tree,
  record `execution_occurred=true`, suppress unverified outputs and set
  reconcile-required whenever external effects are possible or termination is
  unconfirmed.
- Completed receipts and verified artifacts are immutable after revocation.
- An exact retry of a completed activation returns its historical result.
- A changed policy epoch under an existing idempotency key conflicts and cannot
  create another Run B.

PDX will reuse the existing workflow cancel/reconcile machinery. The dispatch
receipt may refine termination evidence but cannot introduce a new workflow
terminal state.

## 8. Receipt integration

Every activation request reaching the authorized Engine control plane produces
one record-once result or rejection record. Run B terminal dispatch receipts
become typed step-receipt evidence and artifact edges in the parent workflow
receipt. Pre-Run-B rejection records remain queryable through the parent
workflow/step projection and do not pretend a Run B existed.

The receipt must distinguish:

- request tracking ID, dispatch attempt ID and Run B ID;
- execution occurred, output schema verified and outputs published;
- receipt artifact identity versus executor output identities;
- policy/tool/schema/deployment digests actually used;
- cancellation phase, termination result, external outcome and reconciliation
  requirement.

## 9. Proposed error families

Stable names will be negotiated with schemas. Required distinctions include:

- unauthenticated or unauthorized principal;
- body/transport principal mismatch;
- policy absent, expired, revoked or digest/epoch mismatch;
- decision receipt absent, non-terminal, forged or binding mismatch;
- tool not allowed, unknown or live definition mismatch;
- input schema invalid;
- idempotency conflict;
- Run B synthesis failure;
- output schema invalid;
- executor failure;
- cancellation with clean, uncertain or reconcile-required outcome.

These codes are error/reason values, never additional workflow machine states.

## 10. Negotiation questions

1. Does the consumer accept an additive dispatch-step workflow profile rather
   than a standalone durable dispatch service?
2. Can all production executors be identified by a verified wheel, OCI image or
   registered deployment bundle digest? If not, what authoritative identity is
   available for injected executors?
3. Must Run A be executed by the same workflow job, or may a separately
   completed Engine run be imported by immutable manifest identity?
4. Which proposal argument limits are required for object depth, property
   count, canonical bytes and opaque secret-reference count?
5. Are pre-Run-B rejection records required as CAS artifacts, or is durable
   workflow-step projection sufficient?
6. Which executor kinds can provide process-tree termination and external
   reconciliation evidence?

No schema drafting or implementation begins until these ownership questions
are accepted or revised.
