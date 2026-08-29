# MC-FastWiki

> **Sync note:** This file and `AGENTS.md` are mirrors. Everything below the horizontal rule must
> stay byte-identical between them. If you edit one, apply the same edit to the other in the same
> commit.

---

## 1. What the project is

A fast, keyboard-driven Minecraft **Java Edition** reference built for draftout matches. The target user is mid-match and needs an answer in under two seconds without touching the mouse. The site builds to static files with no runtime server or runtime wiki calls.

## 2. Stack / Structure + Layout

- **Pipeline:** Python 3.12+ (Pydantic-validated data pipeline running at build time)
- **Web App:** Vanilla TypeScript + Vite (keyboard-first search, suggestion list, window manager, renderers)
- **Data & Dist:** Curated overrides (`/data/curated`), generated static payload (`/data/dist`)

### Repo Layout

```
/pipeline          Build-time data pipeline (Python 3.12+)
  /fetch           Upstream fetchers: mcmeta JSON, wiki Bucket API, wiki extracts, sprites
  /extract         Parse mcmeta into recipes, loot, advancements, tags, item components
  /enrich          Wiki-sourced data: blurbs, mob stats, spawn tables, effect sources
  /normalize       Merge tiers into the canonical Entity model, resolve IDs, dedupe
  /collections     Resolvers for the special aggregate pages (compostable, undead, trims, ...)
  /validate        Pydantic schemas + regression gate that blocks bad builds
  /emit            Writes search index, entity shards, sprite atlas, manifest
  /schema          JSON Schema — the contract between pipeline and web
/data
  /curated         Hand-maintained overrides and data upstream does not expose. Committed.
  /dist            Generated output. Committed so the site build is pure static.
/web               Vanilla TypeScript + Vite. Builds to plain static HTML/CSS/JS.
  /shell           Search bar, suggestion list, window manager, grid layout
  /render          Per-entity-kind content renderers
  /theme           Minecraft-themed CSS, fonts, sprite handling
  /types           TS types generated from /pipeline/schema. Never edit by hand
/scripts           Node build scripts. JSON Schema to TypeScript types
/docs              Design notes, data source reference
```

## 3. How to complete testing

Run these verification commands before committing:

- **Web tests:** `pnpm test` (syncs schema types and runs Vitest)
- **Web lint:** `pnpm lint` (ESLint)
- **Web format check:** `pnpm format:check` (Prettier report; `pnpm format` writes fixes)
- **Web typecheck:** `pnpm typecheck` (`tsc`)
- **Pipeline tests:** `pytest` (runs pipeline tests and repository invariants)
- **Pipeline lint:** `ruff check .`
- **Pipeline types:** `mypy` (strict mode)
