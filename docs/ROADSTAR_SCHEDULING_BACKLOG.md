# RoadStar scheduling capability backlog

Status: planning only. This document does not authorize schema freeze,
implementation, migration, version changes, or publication.

## Confirmed boundary

PDX Engine executes and records an accepted plan. It is not a VRP, load
consolidation, fleet scheduling, or pricing solver. ProDocuX Kernel may validate
and render documents but does not decide HOS, capacity, cargo compatibility,
route feasibility, or optimality.

The intended layers are:

1. `pdx-scheduling-contracts`: product-neutral snapshot, proposal, solver
   result, and verification-report contracts;
2. an independently versioned scheduling solver package;
3. RoadStar domain profiles for rates, HOS, cargo, equipment, and objectives;
4. PDX Engine for approval, local resource reservation, execution, receipts,
   cancellation, and reconciliation;
5. ProDocuX Kernel for dispatch documents, evidence, manifests, and template
   conformance.

## Contract prerequisites

- source rate, currency, accessorial costs, toll and fuel model;
- pickup/delivery windows with timezone and DST rules;
- verified coordinates or addresses with geocoder provenance;
- weight, volume, pallets, axle/compartment/stacking constraints;
- cargo compatibility, temperature, hazardous-material requirements;
- tractor, trailer, equipment, maintenance, inspection, fuel/charge windows;
- driver location, qualifications, certifications, and accumulated HOS;
- dock capacity and service duration;
- split, transfer, cancellation, delay, and service-level policy;
- current assignment/reservation/execution revisions;
- TMS/ELD/provider identities and idempotency fields;
- travel-time model version and observation time.

Missing hard inputs must fail closed; a solver must not invent a city,
distance, rate, capacity, or time window.

## Proposed capabilities

- `REQ-PDX-SCHED-001`: input snapshot and immutable digest contract;
- `REQ-PDX-SCHED-002`: schedule proposal with solver identity, parameters
  digest, objective components, optimality gap, expiry, and rejected reasons;
- `REQ-PDX-SCHED-003`: independent feasibility and domain verification report;
- `REQ-PDX-ENGINE-006`: bounded multi-resource reservation proposal binding;
- `REQ-PDX-ENGINE-007`: atomic local reservation plus external dispatch saga;
- `REQ-PDX-ENGINE-008`: schedule supersession and replanning fencing;
- `REQ-ROADSTAR-EXT-005`: TMS/ELD dispatch reconciliation profile built on
  the existing PDX external-operation lifecycle.

The previous statement that Engine lacks an external-operation
pending/unknown/reconcile lifecycle is obsolete. What remains missing is the
RoadStar provider implementation and any additional generic durable repository
port proven necessary by that implementation.

## Required delivery gates

1. bilateral ownership and schema review;
2. historical-data shadow mode with no dispatch;
3. independent capacity, HOS, windows, and cost verification;
4. solver status distinguishes optimal, feasible, infeasible,
   timeout-with-candidate, and failed;
5. transactional outbox, idempotency, CAS, saga compensation, and unknown
   outcome reconciliation for external systems;
6. real TMS/ELD receipt integration before any claim of real dispatch;
7. measured baseline comparison; no hard-coded trip reduction.
