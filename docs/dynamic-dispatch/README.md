# Governed dynamic dispatch contract draft

Status: bilateral schema negotiation draft. Not frozen. Implementation,
migration, routes, versioning and release are unauthorized.

ER-002 is feasible only as an additive dispatch-step profile owned by the
existing durable runtime workflow. The workflow job and step remain the sole
durable authority. The profile coordinates two static
`pdx_execution_plan_v1` runs and does not add a public workflow machine state.

## Draft schemas

- `pdx_dynamic_dispatch_common_v1`: shared identities, deployment identity,
  frozen tool definitions, terminal statuses and errors.
- `pdx_dynamic_dispatch_policy_v1`: immutable policy registered before Run A.
- `pdx_dynamic_dispatch_policy_register_request_v1`: caller proposal for policy
  registration; it cannot supply Engine-derived status, digests or timestamps.
- `pdx_dynamic_dispatch_policy_revoke_v1`: compare-and-revoke request.
- `pdx_dynamic_dispatch_decision_receipt_v1`: Engine-recorded Run A proposal.
- `pdx_dynamic_dispatch_tool_proposal_v1`: bounded untrusted proposal shape;
  validation never grants activation authority.
- `pdx_dynamic_dispatch_decision_import_request_v1`: optional external Run A
  import bound to immutable manifest and receipt identities.
- `pdx_dynamic_dispatch_activation_request_v1`: authenticated reference-only
  activation command; it contains no proposal body or allowlist.
- `pdx_dynamic_dispatch_activation_response_v1`: accepted or exact-retry Run B
  identity.
- `pdx_dynamic_dispatch_receipt_v1`: record-once terminal dispatch evidence.
- `pdx_dynamic_dispatch_step_projection_v1`: read-only recovery projection;
  it never exposes credentials, secret values or lease tokens.
- `pdx_dynamic_dispatch_error_v1`: stable error envelope.
- `pdx_dynamic_dispatch_reconcile_v1`: bounded recovery request.
- `pdx_dynamic_dispatch_route_mapping_v1`: subordinate private control-plane
  routes and authentication semantics.

Schema names, IDs and fields remain proposals until bilateral review and a
separate freeze authorization. Existing frozen workflow schemas and
`pdx_execution_plan_v1` are not modified.

## Agreed limits

- maximum JSON depth: 8;
- maximum properties in one object: 64;
- maximum total object keys: 256;
- maximum RFC 8785 canonical argument bytes: 65,536;
- maximum opaque `secret-ref://` values: 8;
- maximum array length: 1,024.

JSON Schema enforces local bounds where possible. Recursive totals, canonical
bytes, secret-reference counts, digest recomputation, policy/tool parity and
state transition rules require the semantic validator planned for the next
negotiation revision.

Draft validation currently covers 14 JSON Schemas, valid examples, negative
authority/CAS/URI cases, complete route-operation uniqueness, Python Draft
2020-12 meta-schema validation and AJV 2020-12 `strict: true` compilation.

`semantic-validator.mjs` and `canonicalization-vectors.v1.json` provide the
executable cross-field and RFC 8785/I-JSON draft authority. Passing them proves
negotiation parity only; it does not freeze schemas or authorize runtime code.

## Explicit draft boundaries

- Transport authentication is external authoritative context. A body principal
  is optional and non-authoritative; when present it must match transport.
- Run A normally belongs to the same workflow job. Import of an external Run A
  requires immutable CAS manifest and decision-receipt identities.
- Pre-Run-B rejection evidence remains durable in the step projection and does
  not publish a CAS artifact.
- Run B terminal receipts publish to CAS. Executor output artifacts publish
  only after output-schema verification.
- Subprocess/OCI termination, cooperative in-process cancellation and
  read-only idempotent executors retain distinct reconciliation semantics.
