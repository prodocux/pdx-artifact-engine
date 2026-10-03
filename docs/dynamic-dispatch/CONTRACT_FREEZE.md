# ER-002 governed dynamic dispatch contract freeze

Status: frozen on 2026-10-03. Production implementation remains unauthorized.

This freeze accepts the ER-002 governed dynamic-dispatch contract surface after
bilateral review. `contract-freeze.v1.json` is the authoritative frozen
manifest. The status text embedded in the reviewed README, SEMANTICS document
and `draft-manifest.json` describes the preserved pre-freeze snapshot; it is
historical provenance and is superseded by this document for governance state.

The freeze covers:

- 14 JSON Schema Draft 2020-12 documents;
- the seven-operation subordinate route mapping;
- RFC 8785/I-JSON canonicalization vectors;
- the executable semantic validator;
- AJV 2020-12 strict compilation evidence;
- digest-valid policy, decision, activation and receipt examples; and
- the pre-freeze manifest reviewed by the consumer.

The freeze does not authorize runtime code, storage or migration changes,
private HTTP route wiring, a version assignment, a release, or downstream
adapter development. Those actions require separate approval.

Any semantic or byte-level change to a frozen file requires an additive schema
version or a separately reviewed erratum. The frozen files must not be silently
rewritten.
