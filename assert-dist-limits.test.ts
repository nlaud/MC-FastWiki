import { existsSync } from "node:fs";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  checkDistLimits,
  DEFAULT_WEB_DIST,
  MAX_SINGLE_FILE_BYTES,
  MAX_SITE_TOTAL_BYTES,
} from "./scripts/assert-dist-limits.js";

describe("assert-dist-limits", () => {
  it("passes when web/dist directory contains valid site files", async () => {
    const tempWeb = await mkdtemp(join(tmpdir(), "valid-web-dist-"));
    const tempFile = join(tempWeb, "index.html");
    try {
      await writeFile(tempFile, "<!doctype html><html><body>hello</body></html>");
      const result = await checkDistLimits(tempWeb);
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
      expect(result.summary.length).toBeGreaterThan(0);
    } finally {
      await rm(tempWeb, { recursive: true, force: true });
    }
  });

  it("passes for the built project output if web/dist exists", async () => {
    if (existsSync(DEFAULT_WEB_DIST)) {
      const result = await checkDistLimits();
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
      expect(result.summary.length).toBeGreaterThan(0);
    }
  });

  it("fails if web dist directory is missing or empty", async () => {
    const tempDir = await mkdtemp(join(tmpdir(), "empty-web-dist-"));
    try {
      const result = await checkDistLimits(tempDir);
      expect(result.valid).toBe(false);
      expect(result.errors[0]).toContain("contains no files");
    } finally {
      await rm(tempDir, { recursive: true, force: true });
    }
  });

  it("enforces the 100 MB single file and 1 GB site total constants", () => {
    expect(MAX_SINGLE_FILE_BYTES).toBe(100 * 1024 * 1024);
    expect(MAX_SITE_TOTAL_BYTES).toBe(1024 * 1024 * 1024);
  });
});
