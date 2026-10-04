import { canonicalize, digest, SemanticError } from "../semantic-validator.mjs";

function fail(code) { throw new SemanticError(code); }

export function computePlanDigest(plan) {
  return digest(Object.fromEntries(Object.entries(plan).filter(([key]) => key !== "plan_digest")));
}

export function validatePlanV2(plan) {
  if (plan.plan_digest !== computePlanDigest(plan)) fail("WORKFLOW_PLAN_DIGEST_INVALID");
  const steps = plan.steps;
  const ids = steps.map((step) => step.workflow_step_id);
  if (new Set(ids).size !== ids.length) fail("WORKFLOW_STEP_ID_DUPLICATE");
  const byId = new Map(steps.map((step) => [step.workflow_step_id, step]));
  const visiting = new Set();
  const visited = new Set();
  function visit(id) {
    if (visiting.has(id)) fail("WORKFLOW_DEPENDENCY_CYCLE");
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dependency of byId.get(id).depends_on) {
      if (!byId.has(dependency)) fail("WORKFLOW_DEPENDENCY_UNKNOWN");
      visit(dependency);
    }
    visiting.delete(id);
    visited.add(id);
  }
  ids.forEach(visit);

  const dispatch = steps.filter((step) => step.step_kind === "dispatch");
  const providers = steps.filter((step) => !["check", "dispatch"].includes(step.step_kind));
  const checks = steps.filter((step) => step.step_kind === "check");
  if (dispatch.reduce((sum, step) => sum + step.max_attempts, 0) > plan.budgets.max_dispatch_attempts) fail("WORKFLOW_DISPATCH_ATTEMPT_BUDGET_CONTRADICTION");
  if (providers.reduce((sum, step) => sum + step.max_attempts, 0) > plan.budgets.max_provider_attempts) fail("WORKFLOW_PROVIDER_ATTEMPT_BUDGET_CONTRADICTION");
  if (checks.reduce((sum, step) => sum + step.max_attempts, 0) > plan.budgets.max_check_attempts) fail("WORKFLOW_CHECK_ATTEMPT_BUDGET_CONTRADICTION");
  if (plan.budgets.max_dispatch_runtime_seconds > plan.budgets.max_total_runtime_seconds) fail("WORKFLOW_DISPATCH_RUNTIME_BUDGET_CONTRADICTION");
  if (plan.artifact_edges.length > plan.budgets.max_cross_step_artifact_edges) fail("WORKFLOW_EDGE_BUDGET_CONTRADICTION");

  const dispatchRoles = new Set(["dispatch_receipt", "dispatch_output"]);
  for (const edge of plan.artifact_edges) {
    const producer = byId.get(edge.producer_step_id);
    if (!producer || !byId.has(edge.consumer_step_id)) fail("ARTIFACT_EDGE_STEP_UNKNOWN");
    if (edge.producer_step_id === edge.consumer_step_id) fail("ARTIFACT_EDGE_SELF_REFERENCE");
    if (dispatchRoles.has(edge.artifact_role) && producer.step_kind !== "dispatch") fail("ARTIFACT_EDGE_ROLE_INVALID");
    if (edge.artifact_role === "decision_receipt" && edge.consumer_step_id !== dispatch[0]?.workflow_step_id) fail("ARTIFACT_EDGE_ROLE_INVALID");
  }
  return plan;
}

export function validatePolicyPlanBinding(plan, policy) {
  const step = plan.steps.find((item) => item.workflow_step_id === policy.workflow_step_id);
  if (!step || step.step_kind !== "dispatch") fail("DISPATCH_PLAN_STEP_MISMATCH");
  if (plan.workflow_job_id !== policy.workflow_job_id || step.dispatch_policy_id !== policy.dispatch_policy_id || step.run_a_plan_digest !== policy.run_a_plan_digest || step.decision_step_id !== policy.decision_step_id) fail("DISPATCH_PLAN_POLICY_BINDING_INVALID");
}

export function validateStateAgainstPlan(state, plan) {
  if (state.plan_digest !== plan.plan_digest) fail("WORKFLOW_STATE_PLAN_DIGEST_INVALID");
  const counters = state.counters;
  if (counters.dispatch_attempts > plan.budgets.max_dispatch_attempts || counters.dispatch_runtime_seconds > plan.budgets.max_dispatch_runtime_seconds || counters.active_dispatches > counters.active_steps) fail("WORKFLOW_DISPATCH_COUNTER_INVALID");
}

export function validateReceiptV2(receipt) {
  const edges = new Map(receipt.artifact_edges.map((edge) => [edge.artifact.artifact_id, edge]));
  for (const edge of receipt.artifact_edges) {
    if (edge.artifact_identity_digest !== digest(edge.artifact)) fail("ARTIFACT_IDENTITY_DIGEST_INVALID");
  }
  for (const step of receipt.step_receipts.filter((item) => item.step_kind === "dispatch" && item.status === "succeeded")) {
    const edge = edges.get(step.dispatch_receipt_artifact.artifact_id);
    if (!edge || edge.artifact_role !== "dispatch_receipt" || canonicalize(edge.artifact) !== canonicalize(step.dispatch_receipt_artifact) || edge.producer_step_id !== step.workflow_step_id || edge.producer_attempt_number !== step.attempt_number) fail("DISPATCH_RECEIPT_EDGE_REQUIRED");
  }
  if (receipt.final_counters.active_dispatches !== 0) fail("WORKFLOW_TERMINAL_ACTIVE_DISPATCH_INVALID");
  return receipt;
}

export function validateRouteMappingV2(mapping, frozenV1) {
  const expected = new Map(frozenV1.routes.map((route) => [route.operation, route]));
  if (mapping.routes.length !== expected.size) fail("ROUTE_OPERATION_SET_INVALID");
  const seen = new Set();
  for (const route of mapping.routes) {
    const parent = expected.get(route.operation);
    if (!parent || seen.has(route.operation)) fail("ROUTE_OPERATION_SET_INVALID");
    seen.add(route.operation);
    if (route.method !== parent.method || route.path !== parent.path) fail("ROUTE_WIRE_IDENTITY_CHANGED");
    if (route.v1.request_schema !== parent.request_schema || route.v1.success_schema !== parent.success_schema) fail("ROUTE_V1_BINDING_CHANGED");
  }
  const byOperation = new Map(mapping.routes.map((route) => [route.operation, route]));
  const expectedV2 = {
    create: ["pdx_internal_runtime_provider_workflow_create_request_v2", "pdx_internal_runtime_provider_workflow_create_response_v1"],
    get_state: [null, "pdx_runtime_provider_workflow_state_v2"],
    get_plan: [null, "pdx_runtime_provider_workflow_plan_v2"],
    cancel: ["pdx_internal_runtime_workflow_cancel_v1", "pdx_runtime_provider_workflow_state_v2"],
    reconcile: ["pdx_internal_runtime_workflow_reconcile_v1", "pdx_runtime_provider_workflow_state_v2"],
    update_provider: ["pdx_internal_runtime_provider_update_v1", "pdx_runtime_provider_workflow_state_v2"],
    update_check: ["pdx_internal_runtime_check_update_v1", "pdx_runtime_provider_workflow_state_v2"],
    get_receipt: [null, "pdx_runtime_provider_workflow_receipt_v2"],
  };
  for (const [operation, pair] of Object.entries(expectedV2)) {
    const route = byOperation.get(operation);
    if (route.v2.request_schema !== pair[0] || route.v2.success_schema !== pair[1]) fail("ROUTE_V2_BINDING_INVALID");
  }
  for (const route of mapping.routes.filter((item) => !(item.operation in expectedV2))) {
    if (canonicalize(route.v2) !== canonicalize(route.v1)) fail("ROUTE_V2_UNCHANGED_BINDING_DRIFT");
  }
  return mapping;
}
