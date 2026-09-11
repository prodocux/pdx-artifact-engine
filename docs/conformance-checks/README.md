# Generic conformance check binding proposal

Status: bilaterally frozen with FSF. This is not a runtime implementation or
an implementation release.

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
