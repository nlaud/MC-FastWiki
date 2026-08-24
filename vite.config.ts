import { defineConfig } from "vite";

// The web app lives in `web/`. The pipeline writes to `data/dist`, so the two
// output directories never collide.
export default defineConfig({
  root: "web",
  // Emit relative asset URLs. Vite's default base of "/" hardcodes the site to
  // a server root: a GitHub Pages project site serves this repo from
  // `/MC-FastWiki/`, so `<script src="/assets/...">` resolves outside the site
  // and 404s, leaving a blank unstyled page. CLAUDE.md names GitHub Pages as a
  // supported fallback host, so the build must not assume a root deploy. "./"
  // works at a root (Cloudflare Pages) and under any prefix. Safe because this
  // is one page with no path-based routing — revisit only if that changes.
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  server: {
    open: false,
  },
});
