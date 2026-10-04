# ER-002 freeze erratum candidate: workflow plan authority

Status: bilateral review required. Runtime implementation remains paused.

The frozen ER-002 dispatch envelopes are internally consistent, but the parent
workflow has no frozen machine contract that can authorize a dispatch step.
The existing `pdx_runtime_provider_workflow_plan_v1` permits only `builder`,
`check`, `reviewer` and `repair`. Its create request accepts only that v1 plan,
its counters have no dispatch-attempt budget, and its artifact-edge roles do
not identify decision receipts, dispatch receipts or verified dispatch output.

This conflicts with the accepted ownership rule that the parent workflow plan
must identify the dispatch step and remain the sole durable authority. Runtime
code must not silently reinterpret one of the four existing step kinds.

## Required additive surface

The erratum should add, without modifying any frozen v1 byte:

1. `pdx_runtime_provider_workflow_plan_v2`
   - preserves every v1 field and invariant;
   - adds `dispatch` to `step_kind`;
   - requires a dispatch step to bind `dispatch_policy_id`,
     `run_a_plan_digest` and `decision_step_id`;
   - forbids check- and repair-only fields on a dispatch step;
   - adds explicit aggregate `max_dispatch_attempts` and
     `max_dispatch_runtime_seconds` budgets; and
   - adds artifact-edge roles for `decision_receipt`, `dispatch_receipt` and
     `dispatch_output`.
2. `pdx_internal_runtime_provider_workflow_create_request_v2`
   - references plan v2;
   - retains the existing authenticated control-plane and idempotency rules.
3. `pdx_runtime_provider_workflow_state_v2`
   - retains the existing public `RunState` vocabulary;
   - adds durable `dispatch_attempts`, `active_dispatches` and
     `dispatch_runtime_seconds` counters only.
4. `pdx_runtime_provider_workflow_receipt_v2`
   - binds the dispatch-step terminal receipt and verified output artifact
     edges into the parent workflow receipt;
   - does not duplicate the detailed dispatch receipt or expose credentials.

The existing ER-002 policy, decision, activation, terminal receipt, projection,
error and route schemas remain byte-identical. The existing seven dispatch
operations remain subordinate to the parent workflow.

## Required semantic cases

- v1 plans continue to validate and execute byte-identically.
- A dispatch step cannot be represented as builder, reviewer, repair or check.
- Policy registration rejects a workflow or step not present as a dispatch step
  in the stored v2 plan.
- The plan-bound policy ID, Run A plan digest and decision step must exactly
  match policy registration and activation evidence.
- Dispatch attempt/runtime counters are incremented in the same transaction as
  activation and terminal acceptance; rejection before allocation consumes
  neither counter.
- Workflow budget exhaustion cannot create a Run B.
- Parent terminal receipt includes only verified dispatch artifacts and the
  immutable dispatch-receipt identity.
- Existing v1 state and receipt schemas remain byte-identical.

## Governance

This document is a minimal additive erratum proposal, not a schema freeze. It
does not authorize database migrations, route wiring, runtime implementation,
version assignment, downstream adapter work or publication. Implementation may
resume only after the v2 parent-workflow schemas and semantics receive bilateral
review and a separate erratum freeze record.
