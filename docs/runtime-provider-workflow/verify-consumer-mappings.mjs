import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const dependencyRoot = process.env.PDX_AJV_MODULE_ROOT;
const consumerRoot = process.env.FARPALS_HUB_CONTRACT_ROOT;
if (!dependencyRoot || !consumerRoot) throw new Error("PDX_AJV_MODULE_ROOT and FARPALS_HUB_CONTRACT_ROOT are required");
const require = createRequire(path.join(dependencyRoot, "package.json"));
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;
const root = path.dirname(fileURLToPath(import.meta.url));
const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
for (const name of fs.readdirSync(path.join(root, "schemas")).filter((name) => name.endsWith(".json"))) {
  ajv.addSchema(JSON.parse(fs.readFileSync(path.join(root, "schemas", name), "utf8")));
}
const consumerSchemaPath = path.join(consumerRoot, "schema", "engine-check-update.v1.schema.json");
const consumerSchema = JSON.parse(fs.readFileSync(consumerSchemaPath, "utf8"));
ajv.addSchema(consumerSchema);
const sourceValidator = ajv.getSchema(consumerSchema.$id);
const targetValidator = ajv.getSchema("https://prodocux.dev/schemas/pdx/runtime-provider-workflow/check-update-v1.json");

function canonicalize(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(",")}}`;
}

const bindingFields = ["workflow_job_id", "workflow_step_id", "step_kind", "claim_id", "lease_token", "attempt_number", "check_definition_digest", "execution_constraints_digest", "idempotency_key"];
for (const name of ["check-event-mapping.valid.json", "check-outcome-mapping.valid.json"]) {
  const fixture = JSON.parse(fs.readFileSync(path.join(root, "examples", name), "utf8"));
  if (!sourceValidator(fixture.source)) throw new Error(`${name} source invalid: ${ajv.errorsText(sourceValidator.errors)}`);
  if (!targetValidator(fixture.target)) throw new Error(`${name} target invalid: ${ajv.errorsText(targetValidator.errors)}`);
  for (const field of bindingFields) if (fixture.source[field] !== fixture.target[field]) throw new Error(`${name} binding mismatch: ${field}`);
  if (fixture.source.sequence !== fixture.target.record.sequence) throw new Error(`${name} sequence mismatch`);
  if (fixture.source.payload_record_id !== fixture.target.record.record_id) throw new Error(`${name} record mismatch`);
  if (fixture.source.payload_digest !== fixture.target.record.payload_digest) throw new Error(`${name} digest binding mismatch`);
  if (JSON.stringify(fixture.source.payload) !== JSON.stringify(fixture.target.record.payload)) throw new Error(`${name} payload mismatch`);
  const digest = crypto.createHash("sha256").update(canonicalize(fixture.source.payload), "utf8").digest("hex");
  if (digest !== fixture.source.payload_digest) throw new Error(`${name} payload digest invalid`);
}
process.stdout.write("CONSUMER_MAPPING_PASS 2\n");
