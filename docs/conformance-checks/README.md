# Generic conformance check binding proposal

Status: bilaterally frozen with FSF. The unpublished Engine ``0.3.0a7``
candidate implements this binding additively; it is not yet an implementation
release.

FSF consumer provenance (ready for PDX contract seal, not a pin, GitHub not required):
`docs/conformance-checks/fsf-consumer-provenance.v1.json`.
Home is `D:\FreeStudioFlow\free-studio-flow` tag `pdx-contract-seal-v1`
(`cf21332fb0764e1b5b19efb1d68b0e1771b5c8d9`), not B-roll.

Kernel owns template-conformance schemas. The media adapter package owns media
technical/conformance schemas. Engine does not copy either schema family. It
only binds a schema id, canonical payload/report digests, immutable report
artifact identity, execution result, and safe error where applicable onto the
existing a5/a6 durable check workflow.

The report artifact directly references the a5/a6 common `opaqueArtifact`;
Engine does not maintain a second URI or identity grammar.

| Report disposition | Binding / check outcome | Host action |
|---|---|---|
| `not_evaluated` | no binding | technical check was not requested |
| `evaluation_failed` | `failed` plus `safe_error` | fail, block, or retry |
| `does_not_conform` | `succeeded` plus verified report | block next product step |
| `conforms` | `succeeded` plus verified report | permit next step |

`does_not_conform` means execution succeeded and preserves the a5 verified
report requirement. Conformance is the report verdict, not an execution
failure. No row maps to `completed_with_review`.

`not_evaluated` is not accepted by this schema and must not be added to
`RunState`; it is solely a disposition inside a media conformance report when
technical conformance was not requested.

Scope is P0b template conformance, P1 media conformance, and the P2 generic
binding only. It does not close P0a prompt-sheet intake or FSF-M1 and does not
authorize removing B-roll's current parser.

Engine accepts the binding through
``pdx_internal_runtime_check_update_v2`` while retaining the a5/a6 v1 update
wire. It verifies the frozen check-definition digest, terminal execution
result, safe error, report digest, and full immutable artifact identity in one
transaction. The binding is stored separately from the frozen v1 workflow
receipt and is available read-only at
``GET /internal/v1/runtime-provider-workflows/{workflow_job_id}/steps/{workflow_step_id}/conformance-binding``.
