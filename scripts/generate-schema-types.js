// Generates the TypeScript types of the web app from the JSON Schema files in
// `pipeline/schema`. CLAUDE.md names that directory as the contract between the
// Python pipeline and the web app, so the types must never be written by hand.
//
// `node scripts/generate-schema-types.js` writes the files.
// `node scripts/generate-schema-types.js --check` compares instead, and exits
// with code 1 on a difference. `pnpm build` runs the write mode, and the test
// suite runs the check mode.
//
// The script names each output after its schema. `entity.schema.json` becomes
// `web/types/entity.ts`, so a new schema file needs no edit here.
//
// This file stays plain JavaScript. Node runs it with no build step, the same
// way it runs `eslint.config.js`.

import { readdir, mkdir, readFile, writeFile, unlink } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const REPO_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const SCHEMA_DIR = join(REPO_ROOT, "pipeline", "schema");
const OUTPUT_DIR = join(REPO_ROOT, "web", "types");
const SCHEMA_SUFFIX = ".schema.json";

// `additionalProperties: false` closes every object that the schema leaves
// silent. A schema that wants an open payload says `true` itself, and the tool
// then writes an index signature. `unknownAny` keeps an untyped value as
// `unknown` rather than `any`, which the strict type check needs.
//
// `unreachableDefinitions` exports every entry of `$defs`, and not only the
// entries that the root object reaches. `EntityRef` is the reason: the section
// payloads arrive in Phase 3, so nothing reaches that definition yet, and the
// web app would lose a type that CLAUDE.md names as part of the contract.
const COMPILE_OPTIONS = {
  additionalProperties: false,
  bannerComment: "",
  unknownAny: true,
  unreachableDefinitions: true,
};

/** Returns the schema files, sorted, so the output never depends on disk order. */
async function schemaFiles() {
  const names = await readdir(SCHEMA_DIR);
  return names.filter((name) => name.endsWith(SCHEMA_SUFFIX)).sort();
}

/** Returns the name of the TypeScript file that one schema produces. */
function outputName(schemaFile) {
  return `${schemaFile.slice(0, -SCHEMA_SUFFIX.length)}.ts`;
}

function banner(schemaFile) {
  return [
    "// Generated from pipeline/schema/" + schemaFile + ". Do not edit.",
    "//",
    "// Run `pnpm schema:types` after a change to that schema. `pnpm build` runs",
    "// the same command, and `pnpm test` fails when this file is out of date.",
    "",
    "",
  ].join("\n");
}

/** Compiles one schema and returns the text of its TypeScript file. */
async function render(schemaFile) {
  const types = await compileFromFile(join(SCHEMA_DIR, schemaFile), COMPILE_OPTIONS);
  return banner(schemaFile) + types.trimStart();
}

/** Returns the current text of an output file, or null when it is absent. */
async function readOutput(name) {
  try {
    return await readFile(join(OUTPUT_DIR, name), "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

/** Returns the TypeScript files that the output directory holds now. */
async function existingOutputs() {
  try {
    return (await readdir(OUTPUT_DIR)).filter((name) => name.endsWith(".ts")).sort();
  } catch (error) {
    if (error.code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

async function main() {
  const check = process.argv.includes("--check");
  const files = await schemaFiles();
  if (files.length === 0) {
    throw new Error(`No ${SCHEMA_SUFFIX} file in ${SCHEMA_DIR}`);
  }

  const wanted = new Map();
  for (const schemaFile of files) {
    wanted.set(outputName(schemaFile), await render(schemaFile));
  }

  // A removed schema leaves a stale type file behind. The web app would keep
  // importing it, so the write mode deletes it and the check mode reports it.
  const stale = (await existingOutputs()).filter((name) => !wanted.has(name));
  const problems = [];

  for (const [name, text] of wanted) {
    if (check) {
      const current = await readOutput(name);
      if (current === null) {
        problems.push(`web/types/${name} is missing`);
      } else if (current !== text) {
        problems.push(`web/types/${name} does not match its schema`);
      }
      continue;
    }
    await mkdir(OUTPUT_DIR, { recursive: true });
    await writeFile(join(OUTPUT_DIR, name), text, "utf8");
  }

  for (const name of stale) {
    if (check) {
      problems.push(`web/types/${name} has no schema`);
    } else {
      await unlink(join(OUTPUT_DIR, name));
    }
  }

  if (check) {
    if (problems.length > 0) {
      const list = problems.map((problem) => `  ${problem}`).join("\n");
      console.error(`The generated types are out of date:\n${list}\n\nRun: pnpm schema:types`);
      process.exitCode = 1;
      return;
    }
    console.log(`The generated types match ${files.length} schema files.`);
    return;
  }

  console.log(`Wrote ${wanted.size} type files from ${files.length} schema files.`);
}

await main();
