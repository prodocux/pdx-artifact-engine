import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function assertIJsonString(value) {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error("canonical_json_invalid");
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) throw new Error("canonical_json_invalid");
  }
}

function canonicalize(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number") return JSON.stringify(value);
  if (typeof value === "string") { assertIJsonString(value); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  const entries = Object.keys(value).sort().map((key) => {
    assertIJsonString(key);
    return `${JSON.stringify(key)}:${canonicalize(value[key])}`;
  });
  return `{${entries.join(",")}}`;
}

const root = path.dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(fs.readFileSync(path.join(root, "canonicalization-vectors.v1.json"), "utf8"));
for (const vector of vectors) {
  const actual = canonicalize(vector.input);
  if (actual !== vector.canonical) throw new Error(`canonical mismatch: ${vector.name}`);
  if (vector.sha256 && crypto.createHash("sha256").update(actual, "utf8").digest("hex") !== vector.sha256) {
    throw new Error(`digest mismatch: ${vector.name}`);
  }
}
const invalid = JSON.parse(fs.readFileSync(path.join(root, "canonicalization-invalid-vectors.v1.json"), "utf8"));
for (const vector of invalid) {
  try { canonicalize(JSON.parse(vector.encoded_json)); throw new Error(`accepted invalid: ${vector.name}`); }
  catch (error) { if (error.message !== vector.code) throw error; }
}
const plan = JSON.parse(fs.readFileSync(path.join(root, "examples", "workflow-plan.valid.json"), "utf8"));
const recordedPlanDigest = plan.plan_digest;
delete plan.plan_digest;
if (crypto.createHash("sha256").update(canonicalize(plan), "utf8").digest("hex") !== recordedPlanDigest) {
  throw new Error("plan digest mismatch");
}
const receipt = JSON.parse(fs.readFileSync(path.join(root, "examples", "workflow-receipt.valid.json"), "utf8"));
const edge = receipt.artifact_edges[0];
if (crypto.createHash("sha256").update(canonicalize(edge.artifact), "utf8").digest("hex") !== edge.artifact_identity_digest) {
  throw new Error("artifact identity digest mismatch");
}
process.stdout.write(`CANONICAL_PARITY_PASS ${vectors.length}+${invalid.length}\n`);
