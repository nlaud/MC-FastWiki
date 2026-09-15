// Asserts that the build output stays within GitHub Pages and GitHub limits.
//
// Box 8: Published site total size must be under 1 GB, and no single file
// in the published site or committed data tree may be at or above 100 MB.
//
// `node scripts/assert-dist-limits.js` exits with code 0 on success, or code 1
// with descriptive errors if any limit is violated.

import { readdir, stat } from "node:fs/promises";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
export const DEFAULT_WEB_DIST = join(REPO_ROOT, "web", "dist");
export const DEFAULT_DATA_DIST = join(REPO_ROOT, "data", "dist");

export const MAX_SITE_TOTAL_BYTES = 1024 * 1024 * 1024; // 1 GB
export const MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024; // 100 MB

/** Recursively lists all files in a directory with their sizes. */
export async function listFilesRecursive(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      const subFiles = await listFilesRecursive(fullPath);
      files.push(...subFiles);
    } else if (entry.isFile()) {
      const fileStat = await stat(fullPath);
      files.push({
        path: fullPath,
        size: fileStat.size,
      });
    }
  }

  return files;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

/**
 * Checks that web/dist and data/dist fit within size limits.
 *
 * @param {string} webDistDir
 * @param {string} dataDistDir
 * @returns {Promise<{ valid: boolean, errors: string[], summary: string[] }>}
 */
export async function checkDistLimits(
  webDistDir = DEFAULT_WEB_DIST,
  dataDistDir = DEFAULT_DATA_DIST,
) {
  const errors = [];
  const summary = [];

  // 1. Check web/dist (published site)
  let webFiles;
  try {
    webFiles = await listFilesRecursive(webDistDir);
  } catch (err) {
    errors.push(`Failed to read web dist directory ${webDistDir}: ${String(err)}`);
    return { valid: false, errors, summary };
  }

  if (webFiles.length === 0) {
    errors.push(`Web dist directory ${webDistDir} contains no files.`);
    return { valid: false, errors, summary };
  }

  let totalWebBytes = 0;
  let largestWebFile = { path: "", size: 0 };

  for (const file of webFiles) {
    totalWebBytes += file.size;
    if (file.size > largestWebFile.size) {
      largestWebFile = file;
    }
    if (file.size >= MAX_SINGLE_FILE_BYTES) {
      const rel = relative(webDistDir, file.path);
      errors.push(
        `File in web/dist exceeds single-file limit (${formatBytes(MAX_SINGLE_FILE_BYTES)}): ${rel} (${formatBytes(file.size)})`,
      );
    }
  }

  if (totalWebBytes >= MAX_SITE_TOTAL_BYTES) {
    errors.push(
      `Total web/dist size exceeds site limit (${formatBytes(MAX_SITE_TOTAL_BYTES)}): ${formatBytes(totalWebBytes)}`,
    );
  }

  const largestWebRel = relative(webDistDir, largestWebFile.path);
  summary.push(
    `web/dist: ${formatBytes(totalWebBytes)} across ${webFiles.length} files (limit: ${formatBytes(MAX_SITE_TOTAL_BYTES)})`,
  );
  summary.push(
    `largest file: ${largestWebRel} (${formatBytes(largestWebFile.size)}, limit: ${formatBytes(MAX_SINGLE_FILE_BYTES)})`,
  );

  // 2. Check data/dist (committed directory)
  try {
    const dataFiles = await listFilesRecursive(dataDistDir);
    for (const file of dataFiles) {
      if (file.size >= MAX_SINGLE_FILE_BYTES) {
        const rel = relative(dataDistDir, file.path);
        errors.push(
          `File in data/dist exceeds GitHub single-file ceiling (${formatBytes(MAX_SINGLE_FILE_BYTES)}): ${rel} (${formatBytes(file.size)})`,
        );
      }
    }
    summary.push(`data/dist: ${dataFiles.length} files verified under single-file ceiling.`);
  } catch (err) {
    errors.push(`Failed to read data dist directory ${dataDistDir}: ${String(err)}`);
  }

  return {
    valid: errors.length === 0,
    errors,
    summary,
  };
}

// Run CLI directly if executed as main script.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const result = await checkDistLimits();
  for (const line of result.summary) {
    console.log(line);
  }
  if (!result.valid) {
    console.error("\nSize limit assertions failed:");
    for (const err of result.errors) {
      console.error(`  - ${err}`);
    }
    process.exit(1);
  }
  console.log("All site size assertions passed.");
}
