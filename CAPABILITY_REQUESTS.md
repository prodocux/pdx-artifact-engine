# CAPABILITY_REQUESTS — Artifact Engine capability requests

> Product consumers file product-neutral Engine capability ceilings here.
> Filing a request authorizes evaluation only. Implementation, contract freeze,
> version change and release remain separately gated.

## Status

- `proposed` — filed, awaiting maintainer/referee decision
- `approved` — approved, awaiting implementation
- `in-progress` — being implemented
- `done` — shipped (record the public Engine version)
- `rejected` — declined (record the reason)

## ER-001 [status: in-progress]

- Reporter: bounded local-index consumer
- Date: 2026-09-26
- Public baseline: `pdx-artifact-engine==0.3.0a9`
- Blocker: large-source projection can require multiple bounded Kernel calls
  and outlive one process, lease or deadline. A product-owned synchronous loop
  cannot prove crash-safe range order, idempotent replay, budget enforcement or
  atomic final publication. Engine already owns product-neutral run state,
  checkpoints, artifact bindings, reconciliation, cancellation and receipts,
  but has no published continuable-extraction operation profile connecting
  those primitives to a real Kernel adapter.
- Requested Engine capability: an additive, versioned, format-neutral durable
  extraction operation. A run binds immutable source artifact identity/digest,
  media type, parser-contract name/version and advertised continuation
  capability. Each bounded attempt durably accepts an opaque format-owned range
  identity, expected next range, result artifact identity/digest, accumulated
  counters, coverage and omissions. Resume validates all bindings before the
  next adapter call. Duplicate replay is idempotent; gaps, overlaps, out-of-
  order results, parser changes and source mutation fail closed. Cancellation,
  deadline, maximum ranges/blocks/bytes and retry ceilings are explicit, and
  counters advance atomically with accepted range state. Raw source or
  extracted bytes never enter checkpoints, events, logs or receipts.
- Publication semantics: intermediate range artifacts may be durable but are
  not observable as a completed projection. Final publication is atomic and
  occurs only after a semantically valid terminal Kernel response. The receipt
  binds ordered range digests, aggregate digest, source/parser identity,
  coverage, omissions, limits, consumed counters and terminal reason. Failed,
  cancelled, exhausted or unsupported runs remain explicitly incomplete.
- Capability negotiation: Engine treats page/block/row/sheet/slide/tile range
  descriptors as opaque validated identities supplied by the adapter contract;
  it does not parse formats or assume every format is continuable. Unsupported
  continuation and source-too-large are stable terminal dispositions and must
  not cause fallback to a successful prefix or an unbounded retry loop.
- Required conformance: 55-page PDF bounded completion with tail marker;
  existing DOCX 200+6 completion through the same operation; restart between
  ranges; idempotent replay; gap/overlap/forged-next/source/parser rejection;
  timeout/cancel/retry-exhaustion with no later adapter call; deterministic
  reconciliation of a crash between result persistence and checkpoint
  acceptance; and exactly-once final publication. CSV, XLSX and PPTX
  tail-marker fixtures must use the same operation. Image limits and
  non-continuable source-byte ceilings must terminate without retry loops.
  Tests use the public Kernel adapter/package, not a success-only stub.
- Boundary: Kernel owns deterministic format extraction and range semantics.
  Engine owns durable neutral orchestration. Products retain ACL, search,
  citation, scheduling and domain publication policy. Existing frozen contracts
  remain byte-stable; additions use new versioned contracts/compatibility data.
- Evidence: external consumer Gate 1 and Gate 2 fixtures, including rc9 DOCX
  206-heading continuation and rc9 55-page PDF rejection. Consumer-specific
  coordination evidence remains outside the public Engine repository.
- Referee decision: approved for implementation on 2026-09-26; contract freeze
  and release remain separately gated.
- Shipped in: not shipped

## ER-002 [status: in-progress]

- Reporter: governed dynamic-dispatch consumer
- Date: 2026-10-03
- Public baseline: `pdx-artifact-engine==0.3.0a11`
- Blocker: execution plans resolve each tool as a static registry identifier,
  and dispatcher execution does not enforce the optional skill input/output
  schemas as an activation boundary. A consumer that lets an untrusted model
  choose a later tool would otherwise need to route outside Engine authority,
  weakening allowlist, idempotency, receipt and provenance guarantees.
- Requested Engine capability: a bounded two-run dispatch transition. Run A is
  a normal static decision plan and produces an immutable, credential-free tool
  proposal receipt. Engine then validates that stored receipt against a policy
  registered before Run A, synthesizes a separate static v1 Run B plan and
  executes the resolved tool. Caller-supplied proposal bodies or post-decision
  allowlist expansion are never authoritative.
- Policy authority: the durable policy binds workflow and Run A plan identity,
  decision step, revision epoch, allowed tool names and complete frozen tool
  definitions. Frozen definitions bind skill version, input/output schema
  identities and digests, published implementation distribution digest,
  registry revision and entrypoint. Activation revalidates the live registry
  and executor identity and fails closed on any mismatch. Human approval may
  restrict a registered tool but cannot elevate an unregistered one.
- Activation authority: only an authenticated control-plane principal may
  request activation. Transport identity is authoritative; any body assertion
  must match it. Authentication failures occur before idempotency allocation.
  Material activation fields, including decision receipt and policy
  identities/digests, policy epoch and authenticated principal, are sealed by
  an RFC 8785/I-JSON digest.
- Idempotency and lifecycle: exact concurrent retries create or recover one
  Run B identity; a changed binding conflicts without altering the original
  activation. Completed receipts and verified artifacts remain immutable after
  policy revocation. Revocation before executor invocation cancels cleanly;
  revocation after execution starts records possible external effects,
  suppresses unverified outputs and requires reconciliation where applicable.
- Receipt semantics: every activation outcome has a record-once durable
  dispatch receipt. Run B terminal receipts are immutable CAS artifacts;
  pre-Run B rejection receipts remain queryable in the durable dispatch store.
  Executor outputs publish only after output-schema validation; invalid,
  failed or cancelled outputs are suppressed. Receipt identity is distinct
  from per-request tracking and authoritative activation identity.
- Compatibility and reuse: preserve `pdx_execution_plan_v1` byte and semantic
  compatibility by using two static runs rather than mutating an executing
  graph. Evaluation must first determine how to extend the existing durable
  runtime-provider workflow, authenticated activation, CAS, reconciliation and
  receipt infrastructure; it must not introduce a second competing workflow
  authority or machine-state vocabulary.
- Required conformance: clean-wheel reproduction of the a11 static-tool and
  missing input-schema gates; pre-registered-policy and live-registry mismatch
  rejection; input validation before executor invocation; output validation
  before artifact publication; exact/concurrent retry and crash recovery;
  authenticated-principal mismatch; policy revocation in not-started and
  running phases; all terminal receipt paths; and cross-language RFC 8785
  parity including ECMAScript number thresholds and UTF-16 key ordering.
- Boundary: evaluation, authoritative contract negotiation and contract freeze
  are complete. The freeze does not prescribe internal storage paths, authorize
  implementation, assign a release version or authorize downstream adapter
  work. Consumer-specific evidence remains outside the public Engine
  repository.
- PDX evaluation: feasible as an additive profile owned by the existing durable
  runtime workflow. Initial product-neutral assessment and ownership
  counterproposal are recorded in `docs/dynamic-dispatch/`. Bilateral review
  accepted the 14-schema surface, semantic validator, canonical vectors and
  route mapping; `contract-freeze.v1.json` is the authoritative freeze record.
- Implementation: signed-off candidate `a58663734dde245bfbb8506699c1d3d0e3cdc1a6`
- Shipped in: not shipped
