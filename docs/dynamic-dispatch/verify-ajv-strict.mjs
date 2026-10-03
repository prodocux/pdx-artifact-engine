import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const dependencyRoot = process.env.PDX_AJV_MODULE_ROOT;
if (!dependencyRoot) {
  throw new Error("PDX_AJV_MODULE_ROOT must name a project with ajv and ajv-formats installed");
}
const require = createRequire(path.join(dependencyRoot, "package.json"));
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;
const here = path.dirname(fileURLToPath(import.meta.url));
const schemaRoot = path.join(here, "schemas");
const runtimeCommon = path.join(
  here,
  "..",
  "runtime-provider-workflow",
  "schemas",
  "pdx_runtime_provider_common_v1.schema.json",
);
const schemas = fs.readdirSync(schemaRoot)
  .filter((name) => name.endsWith(".json"))
  .sort()
  .map((name) => JSON.parse(fs.readFileSync(path.join(schemaRoot, name), "utf8")));
schemas.push(JSON.parse(fs.readFileSync(runtimeCommon, "utf8")));
const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
for (const schema of schemas) ajv.addSchema(schema);
for (const schema of schemas) ajv.compile(schema);
process.stdout.write(`AJV_STRICT_PASS ${schemas.length - 1} dynamic schemas\n`);
