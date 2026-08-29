# Pipeline Architecture & Data Sources

## Non-negotiables

1. **Java Edition only.** Every upstream source we use carries Bedrock data mixed in. It must be filtered out at the pipeline stage, never at render time. A Bedrock number reaching the screen is a correctness bug, not a cosmetic one.
2. **Static output.** The pipeline runs on developer machine or CI on demand, hitting network, reading upstream JSON, and writing files into `/data/dist`.

## Architecture: Three Data tiers

Data is merged from three tiers. Later tiers win on conflict. Every field in the output records which tier produced it, so wrong data is traceable to its source.

- **Tier A — Vanilla game data (authoritative, auto-updates, machine-readable).** Covers recipes, loot tables, advancements, registries, item components, block states, and tags via `misode/mcmeta`. No Java and no jar downloads required.
- **Tier B — Minecraft Wiki (human-facing detail the game files do not expose).** Covers intro blurbs, mob health and damage, spawn conditions, effect sources, and breeding items via Minecraft Wiki API (Bucket extension).
- **Tier C — Curated overrides (`/data/curated`).** Hand-written JSON for gaps and mistakes, carrying a `verifiedFor` version string.

## Data Sources

- **Mojang Version Manifest** — `https://launchermeta.mojang.com/mc/game/version_manifest_v2.json`
- **`misode/mcmeta`** — `https://github.com/misode/mcmeta` (summary, data, registries branches)
- **Minecraft Wiki API** — `https://minecraft.wiki/api.php` (MediaWiki 1.45, Bucket extension `action=bucket`, TextExtracts for blurbs, wikitext fallback).

## Pipeline Stages (`/pipeline`)

- `/fetch` — Upstream fetchers (mcmeta JSON, wiki Bucket API, extracts, sprites)
- `/extract` — Parse mcmeta into recipes, loot, advancements, tags, item components
- `/enrich` — Wiki-sourced data (blurbs, mob stats, spawn tables, effect sources)
- `/normalize` — Merge tiers into canonical Entity model, resolve IDs, dedupe
- `/collections` — Resolvers for special aggregate pages (compostable, undead, trims, etc.)
- `/validate` — Pydantic schemas + regression gate that blocks bad builds
- `/emit` — Writes search index, entity shards, sprite atlas, manifest
- `/schema` — JSON Schema defining the contract between pipeline and web
