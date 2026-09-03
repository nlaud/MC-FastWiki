import fs from "node:fs";
import path from "node:path";
import { type Plugin, defineConfig } from "vite";

// `root` is `web/`, so nothing under `data/dist` is reachable by the browser on
// its own -- in dev or in the build. This plugin publishes that directory at
// `/data/`, the path `web/README.md` already documents as the shipped layout,
// and it does so the same way in both modes so a URL that resolves in `pnpm dev`
// also resolves in `pnpm preview`.
//
// Nothing under `web/` may be named `data/`: with `root: "web"`, a module at
// `web/data/x.ts` would be served at `/data/x.ts` and collide with this route.
// The search index loader lives at `web/search/load.ts` for exactly that reason.
function serveDataDist(): Plugin {
  const dataDistDir = path.resolve(import.meta.dirname, "data/dist");
  const mimeTypes: Record<string, string> = {
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
  };

  return {
    name: "serve-data-dist",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url) {
          next();
          return;
        }
        const pathname = new URL(req.url, "http://localhost").pathname;
        const base = server.config.base.endsWith("/")
          ? server.config.base
          : `${server.config.base}/`;
        const dataPrefix = base === "./" || base === "/" ? "/data/" : `${base}data/`;

        let subPath: string | null = null;
        if (pathname.startsWith("/data/")) {
          subPath = pathname.slice("/data/".length);
        } else if (pathname.startsWith(dataPrefix)) {
          subPath = pathname.slice(dataPrefix.length);
        }

        if (subPath === null) {
          next();
          return;
        }

        const decoded = decodeURIComponent(subPath);
        const filePath = path.resolve(dataDistDir, decoded);

        // Containment is checked with `path.relative`, not a `startsWith` on the
        // directory string. A plain prefix test passes for any *sibling* whose
        // name merely starts with "dist" -- a request for `/data/%2e%2e%2fdistX/f`
        // resolves to `data/distX/f`, which begins with the `data/dist` prefix and
        // would have been served. `path.relative` returns a path that escapes with
        // "..", or an absolute one, in exactly the cases that must be refused.
        const relative = path.relative(dataDistDir, filePath);
        const contained =
          relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);

        if (contained && fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
          const ext = path.extname(filePath);
          const contentType = mimeTypes[ext] ?? "application/octet-stream";
          res.setHeader("Content-Type", contentType);
          fs.createReadStream(filePath).pipe(res);
          return;
        }

        res.statusCode = 404;
        res.end("Not Found");
      });
    },
    closeBundle() {
      const outDataDir = path.resolve(import.meta.dirname, "web/dist/data");
      fs.mkdirSync(outDataDir, { recursive: true });
      fs.cpSync(dataDistDir, outDataDir, { recursive: true });
    },
  };
}

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
  plugins: [serveDataDist()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
  },
  server: {
    open: false,
  },
});
