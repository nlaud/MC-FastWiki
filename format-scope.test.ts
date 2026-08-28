import { getFileInfo } from "prettier";
import { describe, expect, it } from "vitest";

// `prettier --check .` walks the whole repository, and two writers cannot own
// one file. Anything a tool generates has to be named in `.prettierignore` or
// `pnpm format:check` reports it on a clean tree and `pnpm format` rewrites it,
// which the generator then undoes on its next run.
//
// The pair that made this gate necessary is the mcmeta block-tag snapshot of
// `tests/fixtures`. Python writes those two files with `json.dumps(indent=2)`,
// which puts every array element on its own line; Prettier keeps a short array
// on one line. So `"tools": ["axe"]` is a standing disagreement, 861 times over
// in one file.
//
// `getFileInfo` answers the question the CLI asks, for a path that need not
// exist. That last part is what lets the 26.3 rows below stand in for the next
// Minecraft version: the rules have to carry a `*` where the version sits, or
// the next snapshot arrives unignored and this gate goes red before the
// release does.
//
// `ignorePath` is passed because the API, unlike the CLI, reads no ignore file
// by default. The list is the CLI's own default for Prettier 3, so the answers
// here are the answers `pnpm format:check` gives.
const ignorePath = [".gitignore", ".prettierignore"];

const ignored = [
  // Written by `tests/fixtures/build_block_tag_snapshot.py`.
  "tests/fixtures/mcmeta_26_2_block_tags.json",
  "tests/fixtures/mcmeta_26_2_block_harvest.json",
  // The next Minecraft version, to prove the rules are not pinned to 26.2.
  "tests/fixtures/mcmeta_26_3_block_tags.json",
  "tests/fixtures/mcmeta_26_3_block_harvest.json",
  // Written by `tests/fixtures/build_bucket_row_snapshot.py`. Prettier agrees
  // with that file's formatting today only because the rows it selects hold no
  // arrays; the rule exists so a refresh that selects a repeated column does
  // not turn the format gate red on a clean tree.
  "tests/fixtures/wiki_bucket_rows.json",
  // The rest of the generated tree, already covered before this gate existed.
  "web/types/entity.ts",
  "data/dist/entities/mob-0.json",
  "web/dist/assets/index-abc123.js",
];

const formatted = [
  // The hand-written fixtures of the same directory. A person wrote them and
  // reads them in a review, so a rule widened to `tests/fixtures/**` would be
  // wrong and has to fail here.
  "tests/fixtures/version_manifest_v2.json",
  "tests/fixtures/mcmeta_ref_26_2_summary.json",
  // Ordinary source on both sides of the repository.
  "web/main.ts",
  "package.json",
];

describe("format scope", () => {
  it.each(ignored)("keeps %s out of the format gate", async (filepath) => {
    await expect(getFileInfo(filepath, { ignorePath })).resolves.toMatchObject({
      ignored: true,
    });
  });

  it.each(formatted)("keeps %s inside the format gate", async (filepath) => {
    await expect(getFileInfo(filepath, { ignorePath })).resolves.toMatchObject({
      ignored: false,
    });
  });
});
