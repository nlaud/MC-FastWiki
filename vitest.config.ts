import { defineConfig } from "vitest/config";

// Vitest reads this file instead of vite.config.ts. The app config sets
// `root: "web"`, which would resolve every glob below against that directory
// and hide anything outside it. The test runner needs the repository root,
// because the suite covers the build configuration as well as the web app.
export default defineConfig({
  test: {
    // The shell code touches the DOM, so the default node environment is not
    // enough. A test of the tooling config runs under jsdom too; jsdom adds
    // browser globals and takes none of Node's away.
    environment: "jsdom",
    // Repository-wide, not `web/**`, so a root-level test of the build
    // configuration is collected. Vitest's default `exclude` already drops
    // `node_modules` and `dist`, and its globber skips dot-directories, so
    // `.venv` and the tool caches stay out.
    include: ["**/*.test.ts"],
  },
});
