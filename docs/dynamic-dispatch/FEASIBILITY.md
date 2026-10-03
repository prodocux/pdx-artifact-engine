# Governed dynamic dispatch feasibility assessment

Status: PDX counterproposal draft; not frozen; implementation unauthorized.

This assessment evaluates ER-002 against the public
`pdx-artifact-engine==0.3.0a11` source and its already published durable runtime
workflow. It is product-neutral. Consumer fixtures and coordination evidence
remain outside this repository.

## Decision

The requested capability is feasible as an additive Engine profile, subject to
the boundary below. PDX accepts the two-static-run principle, pre-registered
policy authority, immutable decision evidence, authenticated activation,
schema validation, material idempotency binding and terminal receipt
requirements.

PDX does not accept a second durable dispatch authority or a public filesystem
`/dispatch_store`. The existing runtime workflow remains the sole durable
workflow authority. Dispatch policy, decision, activation and receipt records
must be transactionally owned by that workflow and must reuse its cancellation,
reconciliation, counters, artifact identities and terminal receipt graph.

This decision authorizes contract negotiation only. It does not authorize a
database migration, route, worker, version change, tag or release.

## Existing capabilities that can be reused

- `pdx_execution_plan_v1` already represents both static runs. No dynamic DAG
  mutation or change to the frozen v1 plan is required.
- `SkillDefinition` already carries optional `input_schema` and
  `output_schema`; enforcement can be added at the governed activation and
  execution boundary without changing existing registry files.
- Runtime workflow persistence already provides SQLite WAL, `BEGIN IMMEDIATE`
  transitions, workflow/step identity, attempts, authenticated claim
  activation, HMAC lease recovery, ordered records, cancellation,
  reconciliation, artifact edges and immutable terminal receipts.
- Existing runtime workflow machine states remain authoritative. Dispatch
  phases and rejection reasons must not become another public `RunState`.
- Existing canonicalization vectors and cross-runtime verification provide the
  starting authority for RFC 8785/I-JSON digests. Python `json.dumps` is not an
  acceptable digest authority for this profile.

## Confirmed gaps

1. Dispatcher tool names are static registry identifiers. Tool selection from a
   prior step is not an Engine-owned activation transition.
2. Dispatcher execution does not enforce `SkillDefinition.input_schema` before
   executor invocation or `output_schema` before artifact publication.
3. The registry exposes no stable published-distribution identity for an
   executor callable. A governed profile therefore needs an explicit deployment
   registry projection; it must not infer trust from Python bytecode.
4. Runtime workflow contracts have provider and deterministic-check attempts,
   but no dispatch-step profile linking two static Engine runs.
5. Existing runtime workflow digests use a deterministic JSON encoding in
   several implementation paths. ER-002 digests require the pinned RFC 8785
   authority and cannot silently reuse a non-equivalent encoder.

## Accepted boundaries

- A dispatch policy is registered and sealed before Run A begins.
- Model/provider output is untrusted evidence and never grants authority.
- Run A and Run B remain byte-compatible `pdx_execution_plan_v1` documents.
- Activation reads the Engine-recorded decision receipt, never a caller-supplied
  proposal body.
- Transport authentication precedes idempotency allocation.
- The policy binds tool name and version, input/output schemas, distribution
  artifact digest, deployment registry revision and entrypoint symbol.
- Run B input validation happens before executor invocation. Output validation
  happens before output artifact publication.
- All terminal outcomes have record-once receipts. Rejected attempts do not
  overwrite the successful activation associated with an idempotency key.
- Revocation before invocation is a clean cancellation. Revocation after
  invocation records possible external effects and follows the existing
  reconcile-required boundary.
- Secret plaintext is never part of a plan, decision receipt, digest input,
  event, error or terminal receipt. Opaque secret references may be bound;
  resolution occurs only at the trusted executor boundary.

## Explicit non-goals

- Dynamic mutation of a running v1 plan.
- Arbitrary multi-agent graphs or model-selected global registry access.
- Caller-provided allowlists, schemas, tool definitions or successful outcome
  assertions.
- A new workflow state vocabulary or a parallel durable store.
- Freezing schema IDs, routes or a release version in this assessment.

## Feasibility gates before implementation may be authorized

1. Agree on the dispatch-step ownership model in the counterproposal.
2. Agree on the deployment registry projection and distribution digest
   authority for built-in, package and explicitly injected executors.
3. Draft versioned schemas, semantic validation, route mapping and positive and
   negative fixtures.
4. Prove RFC 8785 parity using the existing cross-runtime vector process.
5. Prove the new profile does not alter frozen workflow or v1 plan contracts.
6. Complete bilateral review and an explicit contract freeze.
