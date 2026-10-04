import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const moduleRoot = process.env.PDX_AJV_MODULE_ROOT;
if (!moduleRoot) throw new Error("PDX_AJV_MODULE_ROOT is required");
const require = createRequire(pathToFileURL(path.resolve(moduleRoot, "package.json")));
const Ajv2020 = require("ajv/dist/2020").default;
const addFormats = require("ajv-formats").default;
const ajv = new Ajv2020({ strict: true, allErrors: true });
addFormats(ajv);

const parent = path.resolve(root, "..", "..", "runtime-provider-workflow", "schemas");
const schemas = [
  ...fs.readdirSync(parent).filter((name) => name.endsWith(".schema.json")).map((name) => JSON.parse(fs.readFileSync(path.join(parent, name), "utf8"))),
  ...fs.readdirSync(path.join(root, "schemas")).filter((name) => name.endsWith(".schema.json")).map((name) => JSON.parse(fs.readFileSync(path.join(root, "schemas", name), "utf8"))),
];
for (const schema of schemas) ajv.addSchema(schema);
for (const schema of schemas.slice(-5)) ajv.getSchema(schema.$id);
process.stdout.write("ERRATUM_AJV_STRICT_PASS 5 schemas\n");
