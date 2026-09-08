import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";

// `eslint .` walks the whole repository. It skips `node_modules` on its own,
// but it does descend into dot-directories, so anything the config does not
// name in `ignores` gets linted: the Python virtual environment, the ruff and
// mypy and pytest caches, and the agent tooling directory. One vendored or
// generated JavaScript file in any of those turns `pnpm lint` red for a fault
// that belongs to nobody. These cases pin the scope of the gate.
//
// No `cwd` option: ESLint defaults to `process.cwd()`, and Vitest runs from
// the repository root, which is where the paths below are rooted.
const eslint = new ESLint();

// `new ESLint()` above does not load anything by itself -- `eslint.config.js`
// and its `typescript-eslint` import are resolved lazily, on the first call
// that actually needs the config, which is the first `isPathIgnored` below.
// Timed against this repository: a cold first call took 13.5s, comfortably
// over Vitest's 5s default `it` timeout, and every call after it took under
// 10ms. Whichever `it.each` case runs first paid that cost and failed on a
// timeout that had nothing to do with what it was testing -- observed here as
// 39.8s and one failure on a first run, 4.3s and all green on the second, with
// no change to the file in between.
//
// So the config is warmed once, here, before any case runs, with its own
// timeout generous enough for a cold resolve. Every `it.each` case below then
// starts from a warm config and keeps Vitest's default timeout.
beforeAll(async () => {
  await eslint.isPathIgnored("warm-eslint-config.js");
}, 60_000);

const ignored = [
  ".venv/Lib/site-packages/vendored/bundle.js",
  ".mypy_cache/probe.js",
  ".ruff_cache/probe.js",
  ".pytest_cache/probe.js",
  ".claude/hooks/hook.js",
  "node_modules/some-package/index.js",
  "web/dist/assets/index-abc123.js",
  "data/dist/entities/shard.js",
  "data/.cache/mcmeta/probe.js",
  // `pnpm schema:types` writes this file from the JSON Schema. A rule here
  // would report the generator rather than an author.
  "web/types/entity.ts",
];

const linted = [
  "web/main.ts",
  "web/shell/mount.ts",
  "web/shell/mount.test.ts",
  "eslint.config.js",
  // Hand-written build tooling. It is JavaScript that Node runs, so the lint
  // gate has to cover it even though it sits outside `web/`.
  "scripts/generate-schema-types.js",
];

describe("lint scope", () => {
  it.each(ignored)("keeps %s out of the lint gate", async (path) => {
    await expect(eslint.isPathIgnored(path)).resolves.toBe(true);
  });

  it.each(linted)("keeps %s inside the lint gate", async (path) => {
    await expect(eslint.isPathIgnored(path)).resolves.toBe(false);
  });
});
