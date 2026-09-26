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
