# Product-neutral provenance export

`pdx_provenance_bundle_v1` is an additive export contract. It represents
artifacts as entities, steps and external operations as activities, and human,
provider, or adapter identities as agents. Relationship names intentionally
match the W3C PROV-O vocabulary where practical.

The bundle is bounded, reference-complete, and bound to its canonical SHA-256.
It contains opaque identities and scalar attributes, not credentials, prompts,
raw document content, or unrestricted logs. Engine durable records and receipts
remain authoritative; a provenance graph is a derived export and cannot create
approval, mutate a run, or lower policy.

Semantica, an RDF store, a graph database, or another analytics system may
consume the bundle through a later adapter. None is a runtime dependency of PDX
Core or Engine. A future adapter must preserve node identities and bundle
digests and must label any inferred relationship as derived rather than
authoritative evidence.
