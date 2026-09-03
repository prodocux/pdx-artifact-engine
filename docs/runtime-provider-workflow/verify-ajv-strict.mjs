import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const dependencyRoot = process.env.PDX_AJV_MODULE_ROOT;
if (!dependencyRoot) throw new Error("PDX_AJV_MODULE_ROOT must name a project with ajv and ajv-formats installed");
const require = createRequire(path.join(dependencyRoot, "package.json"));
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;
const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "schemas");
const schemas = fs.readdirSync(root).filter((name) => name.endsWith(".json")).sort()
  .map((name) => JSON.parse(fs.readFileSync(path.join(root, name), "utf8")));
const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);
for (const schema of schemas) ajv.addSchema(schema);
for (const schema of schemas) ajv.compile(schema);
process.stdout.write(`AJV_STRICT_PASS ${schemas.length}\n`);
