// Smoke-tests the deployed GitHub Pages site.
//
// Box 9: Smoke-test the deployed URL, not just the build output.
// Fetches the page, extracts referenced script and stylesheet assets,
// and fetches those too to confirm no 404s (e.g. relative base prefix issues).
// Also tests dynamic data payload fetches.

import { fileURLToPath } from "node:url";

const DEFAULT_TARGET_URL = "https://nlaud.github.io/MC-FastWiki/";
const MAX_RETRIES = 10;
const RETRY_DELAY_MS = 3000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Extracts asset URLs from HTML source text.
 *
 * @param {string} html
 * @returns {string[]}
 */
export function extractAssetHrefs(html) {
  const assets = new Set();

  // Match <script ... src="..."
  const scriptRegex = /<script\b[^>]*\bsrc=["']([^"']+)["']/gi;
  let match;
  while ((match = scriptRegex.exec(html)) !== null) {
    if (match[1]) assets.add(match[1]);
  }

  // Match <link ... href="..."
  const linkRegex = /<link\b[^>]*\bhref=["']([^"']+)["']/gi;
  while ((match = linkRegex.exec(html)) !== null) {
    if (match[1]) assets.add(match[1]);
  }

  return Array.from(assets);
}

/**
 * Performs smoke testing against a target URL.
 *
 * @param {string} targetUrl
 * @param {object} [options]
 * @param {number} [options.maxRetries]
 * @param {number} [options.retryDelayMs]
 * @returns {Promise<{ success: boolean, errors: string[], testedUrls: string[] }>}
 */
export async function smokeTest(
  targetUrl = DEFAULT_TARGET_URL,
  { maxRetries = MAX_RETRIES, retryDelayMs = RETRY_DELAY_MS } = {},
) {
  const errors = [];
  const testedUrls = [];

  // Ensure targetUrl ends with a slash if it's a directory
  const normalizedTarget = targetUrl.endsWith("/") ? targetUrl : `${targetUrl}/`;
  console.log(`Smoke testing target: ${normalizedTarget}`);

  // Step 1: Fetch main HTML page with retry
  let html = "";
  let response = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`Fetching root page (attempt ${attempt}/${maxRetries}): ${normalizedTarget}`);
      response = await fetch(normalizedTarget);
      if (response.ok) {
        html = await response.text();
        testedUrls.push(normalizedTarget);
        break;
      }
      console.warn(`Attempt ${attempt} returned status ${response.status}. Retrying...`);
    } catch (err) {
      console.warn(`Attempt ${attempt} failed: ${String(err)}. Retrying...`);
    }
    if (attempt < maxRetries) {
      await sleep(retryDelayMs);
    }
  }

  if (!response || !response.ok || !html) {
    errors.push(
      `Failed to fetch ${normalizedTarget} after ${maxRetries} attempts (status: ${response?.status ?? "unknown"}).`,
    );
    return { success: false, errors, testedUrls };
  }

  console.log(`Root page fetched successfully (${html.length} bytes).`);

  // Step 2: Extract asset URLs
  const assetPaths = extractAssetHrefs(html);
  if (assetPaths.length === 0) {
    errors.push("No script or stylesheet assets found in root HTML.");
  } else {
    console.log(`Found ${assetPaths.length} asset references in HTML:`, assetPaths);
  }

  // Step 3: Fetch each referenced asset
  for (const assetPath of assetPaths) {
    const resolvedUrl = new URL(assetPath, normalizedTarget).href;
    testedUrls.push(resolvedUrl);
    try {
      console.log(`Fetching asset: ${resolvedUrl}`);
      const assetRes = await fetch(resolvedUrl);
      if (!assetRes.ok) {
        errors.push(`Asset failed with HTTP ${assetRes.status}: ${resolvedUrl}`);
      } else {
        const body = await assetRes.text();
        if (body.length === 0) {
          errors.push(`Asset returned empty body: ${resolvedUrl}`);
        } else {
          console.log(`  ✓ ${resolvedUrl} (${body.length} bytes)`);
        }
      }
    } catch (err) {
      errors.push(`Asset fetch threw error: ${resolvedUrl} (${String(err)})`);
    }
  }

  // Step 4: Verify core static data endpoints
  const coreDataFiles = [
    "data/index.json",
    "data/manifest.json",
    "data/sprites.json",
    "data/sprites.png",
  ];

  for (const dataFile of coreDataFiles) {
    const dataUrl = new URL(dataFile, normalizedTarget).href;
    testedUrls.push(dataUrl);
    try {
      console.log(`Fetching data file: ${dataUrl}`);
      const dataRes = await fetch(dataUrl);
      if (!dataRes.ok) {
        errors.push(`Data asset failed with HTTP ${dataRes.status}: ${dataUrl}`);
      } else {
        const buf = await dataRes.arrayBuffer();
        if (buf.byteLength === 0) {
          errors.push(`Data asset is empty: ${dataUrl}`);
        } else {
          console.log(`  ✓ ${dataUrl} (${buf.byteLength} bytes)`);
        }
      }
    } catch (err) {
      errors.push(`Data asset fetch threw error: ${dataUrl} (${String(err)})`);
    }
  }

  return {
    success: errors.length === 0,
    errors,
    testedUrls,
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const urlArg = process.argv[2] || DEFAULT_TARGET_URL;
  const result = await smokeTest(urlArg);

  if (!result.success) {
    console.error("\nSmoke test FAILED with the following errors:");
    for (const err of result.errors) {
      console.error(`  - ${err}`);
    }
    process.exit(1);
  }

  console.log(
    `\nSmoke test PASSED: all ${result.testedUrls.length} URLs returned HTTP 200 with non-empty content.`,
  );
}
