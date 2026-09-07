import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const moduleRoot = process.env.PDX_AJV_MODULE_ROOT;
if (!moduleRoot) {
  throw new Error("PDX_AJV_MODULE_ROOT is required");
}

const require = createRequire(path.join(moduleRoot, "package.json"));
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;
const schema = JSON.parse(
  fs.readFileSync(
    path.join(here, "pdx_runtime_provider_step_projection_v1.schema.json"),
    "utf8",
  ),
);
const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
ajv.compile(schema);
console.log("AJV_ADDITIVE_STEP_PROJECTION_PASS 1");
