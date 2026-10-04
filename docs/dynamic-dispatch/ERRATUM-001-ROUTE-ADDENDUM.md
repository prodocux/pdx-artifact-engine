# ERRATUM-001 route-authority addendum candidate

Status: bilateral review required. Runtime implementation remains paused.

The endorsed ERRATUM-001 plan-authority proposal requires four additive v2
parent-workflow schemas. During schema drafting, a second authority dependency
was found: the frozen `pdx_runtime_provider_route_mapping_v1` binds create,
plan, state and receipt operations exclusively to the corresponding v1
schemas. Four standalone v2 schemas would therefore be unreachable through an
authoritative wire contract.

This addendum proposes one additional schema,
`pdx_runtime_provider_route_mapping_v2`, plus a conforming mapping document.
It preserves the same twelve operation names, methods and paths. For each
operation whose wire representation differs by workflow contract version, the
mapping declares both the v1 and v2 schema and requires selection from the
workflow contract version durably stored at creation. A caller cannot choose
the response version or reinterpret an existing workflow.

The v1 route mapping and schema remain byte-identical. The addendum does not
add a route, rename a route, authorize content negotiation by an untrusted
caller, or authorize route implementation. The five-schema erratum candidate
must receive bilateral review before an erratum freeze can be created.
