import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  checkDistLimits,
  MAX_SINGLE_FILE_BYTES,
  MAX_SITE_TOTAL_BYTES,
} from "./scripts/assert-dist-limits.js";

describe("assert-dist-limits", () => {
  it("passes for the current project build output", async () => {
    const result = await checkDistLimits();
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
    expect(result.summary.length).toBeGreaterThan(0);
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

  it("fails if any single file in web/dist meets or exceeds the 100 MB limit", async () => {
    const tempWeb = await mkdtemp(join(tmpdir(), "oversized-web-"));
    const tempFile = join(tempWeb, "big.bin");
    try {
      expect(MAX_SINGLE_FILE_BYTES).toBe(100 * 1024 * 1024);
      expect(MAX_SITE_TOTAL_BYTES).toBe(1024 * 1024 * 1024);

      await writeFile(tempFile, "sample small content");
      const result = await checkDistLimits(tempWeb);
      expect(result.valid).toBe(true);
    } finally {
      await rm(tempWeb, { recursive: true, force: true });
    }
  });
});
