import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));

export class SemanticError extends Error {
  constructor(code, message = code) { super(message); this.code = code; }
}

function assertIJsonString(value) {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new SemanticError("CANONICAL_JSON_INVALID");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) throw new SemanticError("CANONICAL_JSON_INVALID");
  }
}

export function canonicalize(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new SemanticError("CANONICAL_JSON_INVALID");
    return JSON.stringify(value);
  }
  if (typeof value === "string") { assertIJsonString(value); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value !== "object") throw new SemanticError("CANONICAL_JSON_INVALID");
  const entries = Object.keys(value).sort().map((key) => {
    assertIJsonString(key);
    return `${JSON.stringify(key)}:${canonicalize(value[key])}`;
  });
  return `{${entries.join(",")}}`;
}

export function digest(value) {
  return crypto.createHash("sha256").update(canonicalize(value), "utf8").digest("hex");
}

function without(value, ...keys) {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));
}

function requireEqual(actual, expected, code) {
  if (actual !== expected) throw new SemanticError(code);
}

export function validateArguments(value, limits) {
  let totalKeys = 0;
  let secretRefs = 0;
  function visit(item, depth) {
    if (depth > limits.max_depth) throw new SemanticError("DISPATCH_PROPOSAL_BOUNDS_EXCEEDED");
    if (typeof item === "string") { assertIJsonString(item); if (item.startsWith("secret-ref://")) secretRefs += 1; return; }
    if (typeof item === "number") canonicalize(item);
    if (Array.isArray(item)) {
      if (item.length > limits.max_array_length) throw new SemanticError("DISPATCH_PROPOSAL_BOUNDS_EXCEEDED");
      item.forEach((child) => visit(child, depth + 1));
    } else if (item !== null && typeof item === "object") {
      const keys = Object.keys(item);
      if (keys.length > limits.max_properties_per_object) throw new SemanticError("DISPATCH_PROPOSAL_BOUNDS_EXCEEDED");
      totalKeys += keys.length;
      if (totalKeys > limits.max_total_keys) throw new SemanticError("DISPATCH_PROPOSAL_BOUNDS_EXCEEDED");
      keys.forEach((key) => { assertIJsonString(key); visit(item[key], depth + 1); });
    }
  }
  visit(value, 1);
  if (secretRefs > limits.max_secret_refs || Buffer.byteLength(canonicalize(value), "utf8") > limits.max_canonical_bytes) {
    throw new SemanticError("DISPATCH_PROPOSAL_BOUNDS_EXCEEDED");
  }
}

export function validatePolicy(policy) {
  const tools = [...policy.allowed_tools].sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0);
  const names = tools.map((tool) => tool.name);
  if (new Set(names).size !== names.length) throw new SemanticError("DISPATCH_POLICY_TOOL_DUPLICATE");
  requireEqual(canonicalize(policy.allowed_tool_names), canonicalize(names), "DISPATCH_POLICY_TOOL_ORDER_INVALID");
  for (const tool of tools) {
    requireEqual(tool.deployment.identity_digest, digest(without(tool.deployment, "identity_digest")), "DISPATCH_DEPLOYMENT_DIGEST_INVALID");
  }
  requireEqual(policy.allowed_tool_names_digest, digest(names), "DISPATCH_ALLOWED_TOOLS_DIGEST_INVALID");
  requireEqual(policy.frozen_tool_definitions_digest, digest(tools), "DISPATCH_TOOL_DEFINITIONS_DIGEST_INVALID");
  requireEqual(policy.policy_digest, digest(without(policy, "policy_digest")), "DISPATCH_POLICY_DIGEST_INVALID");
  return policy;
}

export function validateDecisionReceipt(receipt, policy, proposalSchemaDigest) {
  validatePolicy(policy);
  for (const key of ["workflow_job_id", "workflow_step_id", "dispatch_policy_id", "policy_revision_epoch", "policy_digest"]) {
    requireEqual(receipt[key], policy[key], "DISPATCH_DECISION_BINDING_INVALID");
  }
  requireEqual(receipt.proposal_schema_digest, proposalSchemaDigest, "DISPATCH_PROPOSAL_SCHEMA_DIGEST_INVALID");
  validateArguments(receipt.arguments, policy.proposal_limits);
  requireEqual(receipt.arguments_digest, digest(receipt.arguments), "DISPATCH_ARGUMENTS_DIGEST_INVALID");
  requireEqual(receipt.canonical_proposal_digest, digest({proposal_schema_id: receipt.proposal_schema_id, proposal_schema_digest: receipt.proposal_schema_digest, tool_name: receipt.tool_name, arguments: receipt.arguments}), "DISPATCH_PROPOSAL_DIGEST_INVALID");
  if (!policy.allowed_tool_names.includes(receipt.tool_name)) throw new SemanticError("DISPATCH_TOOL_NOT_ALLOWED");
  requireEqual(receipt.decision_receipt_digest, digest(without(receipt, "decision_receipt_digest")), "DISPATCH_DECISION_RECEIPT_DIGEST_INVALID");
  return receipt;
}

export function deriveActivationBinding(request, policy, receipt, authenticatedPrincipal) {
  if (request.caller_authority_id !== undefined && request.caller_authority_id !== authenticatedPrincipal) throw new SemanticError("DISPATCH_PRINCIPAL_MISMATCH");
  for (const key of ["workflow_job_id", "workflow_step_id", "source_run_id", "source_plan_digest", "decision_receipt_id", "decision_receipt_digest"]) {
    requireEqual(request[key], receipt[key], "DISPATCH_ACTIVATION_BINDING_INVALID");
  }
  requireEqual(request.dispatch_policy_id, policy.dispatch_policy_id, "DISPATCH_ACTIVATION_BINDING_INVALID");
  requireEqual(request.policy_digest_assertion, policy.policy_digest, "DISPATCH_ACTIVATION_BINDING_INVALID");
  requireEqual(request.policy_revision_epoch, policy.policy_revision_epoch, "DISPATCH_ACTIVATION_BINDING_INVALID");
  return digest({workflow_job_id: request.workflow_job_id, workflow_step_id: request.workflow_step_id, source_run_id: request.source_run_id, source_plan_digest: request.source_plan_digest, decision_receipt_id: request.decision_receipt_id, decision_receipt_digest: request.decision_receipt_digest, dispatch_policy_id: request.dispatch_policy_id, policy_digest: policy.policy_digest, policy_revision_epoch: policy.policy_revision_epoch, authenticated_principal: authenticatedPrincipal});
}

export function validateTerminalReceipt(receipt) {
  const rejected = receipt.status.startsWith("rejected_");
  if (receipt.status === "completed" && (!receipt.execution_occurred || !receipt.input_schema_verified || !receipt.output_schema_verified || !receipt.receipt_cas_published || !receipt.executor_output_artifacts_published || receipt.error_code !== null || receipt.reconciliation_required)) throw new SemanticError("DISPATCH_RECEIPT_TERMINAL_INVALID");
  if (rejected && (receipt.authoritative_activation_id !== null || receipt.dispatch_attempt_id !== null || receipt.run_b_id !== null || receipt.run_b_plan_digest !== null || receipt.execution_occurred || receipt.receipt_cas_published || receipt.executor_output_artifacts_published || receipt.artifact_identities.length !== 0)) throw new SemanticError("DISPATCH_RECEIPT_TERMINAL_INVALID");
  if (receipt.status !== "completed" && receipt.error_code === null) throw new SemanticError("DISPATCH_RECEIPT_ERROR_REQUIRED");
  requireEqual(receipt.receipt_digest, digest(without(receipt, "receipt_digest")), "DISPATCH_RECEIPT_DIGEST_INVALID");
  return receipt;
}

export function validateRouteMapping(mapping) {
  const required = new Set(["register_policy", "revoke_policy", "import_external_decision_receipt", "activate", "get_step_projection", "get_dispatch_receipt", "reconcile_dispatch"]);
  const operations = mapping.routes.map((route) => route.operation);
  if (operations.length !== required.size || new Set(operations).size !== required.size || operations.some((value) => !required.has(value))) throw new SemanticError("DISPATCH_ROUTE_MAPPING_INVALID");
}

function load(relative) { return JSON.parse(fs.readFileSync(path.join(root, relative), "utf8")); }
function rawDigest(relative) { return crypto.createHash("sha256").update(fs.readFileSync(path.join(root, relative))).digest("hex"); }

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const vectors = load("canonicalization-vectors.v1.json");
  for (const vector of vectors.positive) { requireEqual(canonicalize(vector.input), vector.canonical, "CANONICAL_VECTOR_MISMATCH"); requireEqual(digest(vector.input), vector.sha256, "CANONICAL_VECTOR_DIGEST_MISMATCH"); }
  for (const vector of vectors.negative) {
    let rejected = false;
    try { canonicalize(JSON.parse(vector.encoded_json)); } catch (error) { rejected = error.code === vector.code; }
    if (!rejected) throw new Error(`negative canonical vector accepted: ${vector.name}`);
  }
  const policy = load("examples/policy.valid.json");
  const decision = load("examples/decision-receipt.valid.json");
  validateDecisionReceipt(decision, policy, rawDigest("schemas/pdx_dynamic_dispatch_tool_proposal_v1.schema.json"));
  const request = load("examples/activation-request.valid.json");
  requireEqual(load("examples/activation-response.valid.json").idempotency_binding_digest, deriveActivationBinding(request, policy, decision, "control-plane-01"), "DISPATCH_ACTIVATION_DIGEST_INVALID");
  validateTerminalReceipt(load("examples/receipt-completed.valid.json"));
  validateTerminalReceipt(load("examples/receipt-rejected.valid.json"));
  validateRouteMapping(load("route-mapping.json"));
  process.stdout.write(`DYNAMIC_DISPATCH_SEMANTICS_PASS ${vectors.positive.length}+${vectors.negative.length}\n`);
}
