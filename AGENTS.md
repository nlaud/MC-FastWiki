# MC-FastWiki

> **Sync note:** This file and `CLAUDE.md` are mirrors. Everything below the horizontal rule must
> stay byte-identical between them. If you edit one, apply the same edit to the other in the same
> commit.

---

A fast, keyboard-driven Minecraft **Java Edition** reference built for draftout matches. The
target user is mid-match and needs an answer in under two seconds without touching the mouse.

## Non-negotiables

These constrain every decision in the repo. Do not relax them without asking.

1. **Java Edition only.** Every upstream source we use carries Bedrock data mixed in. It must be
   filtered out at the pipeline stage, never at render time. A Bedrock number reaching the screen
   is a correctness bug, not a cosmetic one.
2. **Keyboard first.** Every action reachable without a mouse. The mouse is a fallback, not the path.
3. **Speed is the feature.** Budget: keystroke to updated suggestion list under 16 ms; Enter to
   rendered window under 100 ms. No network round trip on the hot path — search runs against a
   preloaded local index.
4. **Static output.** The site builds to static files. No runtime server, no runtime wiki calls.
   All scraping happens at build time.

### Build time and run time are separate — do not confuse them

This trips people up, so it is worth stating plainly. The **pipeline** runs on a developer machine
or in CI, on demand. It hits the network, reads upstream JSON, and writes files into `/data/dist`.
The **site** is what a browser loads: plain HTML, CSS, JS, and those pre-built JSON files.

Nothing from the pipeline ships to the browser. A heavy or slow pipeline does not make the site
less static and does not cost the user a millisecond mid-match. "We run a build step" and "the
site is static" are both true at once, and always will be.

The wiki API does send `Access-Control-Allow-Origin: *`, so fetching from the browser at runtime is
technically possible. **Do not do it.** It would put dozens of network round trips between a
keystroke and an answer, blowing the 100 ms budget outright; it would make the tool fail mid-match
whenever the wiki is slow, down, or changes a schema; and it would put load on a volunteer-run
service on every page load. Pre-building is faster, more reliable, and a better neighbor.

## Repo layout

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

## Architecture: three data tiers

Data is merged from three tiers. Later tiers win on conflict. Every field in the output records
which tier produced it, so wrong data is traceable to its source.

**Tier A — Vanilla game data (authoritative, auto-updates, machine-readable).**
Covers recipes, loot tables, advancements, registries, item components, block states, and tags.
This is ground truth for anything it covers, and it is the reason the project can track new
Minecraft versions with no human effort.

**No Java, and no jar downloads.** We do not run Mojang's data generator ourselves — `misode/mcmeta`
already publishes its output as plain JSON on GitHub, per version, updated within hours of a
release. We fetch that. This project has no JVM dependency of any kind.

**Tier B — Minecraft Wiki (human-facing detail the game files do not expose).**
Covers intro blurbs, mob health and damage, spawn conditions, effect sources, and breeding items.
Reached through the wiki API — see the data-source notes below.

**Tier C — Curated overrides (`/data/curated`).**
Hand-written JSON for the gaps and the mistakes. Every curated file carries a `verifiedFor`
version string. The build warns when a curated file was verified against an older Minecraft
version than the one being built, so overrides do not silently rot.

## Data sources (verified 2026-08-24, keep this section current)

**Mojang version manifest** — `https://launchermeta.mojang.com/mc/game/version_manifest_v2.json`

Used only to learn the current release ID, so `data:check` can tell whether a rebuild is needed.
Latest release at time of writing was **26.2**. We never download the jars it points at.

**`misode/mcmeta`** — `https://github.com/misode/mcmeta` — is Tier A in practice. It runs Mojang's
data generator and publishes the output to orphan branches, each also tagged per version
(`26.3-snapshot-9-summary`, `26.2-data`, and so on). Verified current: the `summary` branch was
updated for `26.3-snapshot-9` on the same day that snapshot released.

Branches worth knowing:

| Branch | Contents |
|---|---|
| `summary` | Condensed JSON: `item_components`, `blocks`, `registries`, `commands`, `sounds` |
| `data` | The full vanilla data pack — `recipe/`, `loot_table/`, `advancement/`, `tags/`, `enchantment/` (43), `worldgen/structure/` (52), `worldgen/biome/` (67) |
| `registries` | One flat ID list per registry (1,658 items in 26.x) |
| `atlas`, `assets` | Textures. We do not use these — icons come from the wiki. |
| `diff` | Per-version change summaries, useful for the update PR description |

Pin to a version tag rather than tracking a branch head, so a build is reproducible and a snapshot
never lands in a release build by accident.

`summary/item_components/data.json` deserves special mention. Keys are **unprefixed** (`apple`, not
`minecraft:apple`) — a real trap, since a `minecraft:`-prefixed lookup silently returns nothing.
It carries data that used to require hand-curation:

- `minecraft:food` → `{nutrition, saturation}` — **44 items**
- `minecraft:compostable` → `{layers}` — **122 items**
- `minecraft:cooking_fuel` → `{burn_time, speed_multiplier}` — **347 items**

That covers the `unique_food` and `compostable` collection pages straight from Tier A.

**Minecraft Wiki API** — `https://minecraft.wiki/api.php` (MediaWiki 1.45).

The wiki runs Weird Gloop's **Bucket** extension, which exposes structured data through
`action=bucket`. **This is the primary wiki interface — prefer it over parsing wikitext.**
The `query` parameter takes a Lua statement:

```
action=bucket&format=json&query=bucket('droptable').select('item','json').limit(500).offset(0).run()
```

Rules learned the hard way: bucket names are lowercase snake_case (`spawn_table`, not
`Spawn table`); `select()` is mandatory; `limit()` caps at **5000** rows; `offset()` works, so
paginate with it. Schemas live on the `Bucket:` wiki pages (namespace 9592) as JSON.

**`page_name` is selectable on every bucket and appears in no schema page.** It names the wiki page
a row was written on, and it is worth selecting every time: it is the attribution URL, it is the
grouping key for the buckets whose rows sit on the page of the thing they describe (`spawn_table`
rows are on biome pages, `trade` rows on profession pages), and it carries the namespace.

**Filter on that namespace, or the tables are unusable.** The buckets index the whole wiki, user
sandboxes and translation projects included. Of the 3,690 Java `resource_location` rows, 966 come
from `User:`, `Minecraft Wiki:`, and `Forum:` pages — and a translation row is the dangerous kind,
because it is well-formed: it maps `Taş` to `stone` and `poki moku` to `bowl` with nothing in the
row to say so. A main-namespace title holds no colon, so that is the test. `advancement` needs a
second filter on top: 615 rows describe 126 advancements, and the extra 489 are April Fools' and
version-page snapshots whose `internal_id` values collide exactly with the live ones, so take only
the rows on the `Advancement` page.

Buckets that matter to us, with row counts observed at time of writing:

| Bucket | Rows | Contents |
|---|---|---|
| `resource_location` | 5000+ | `display_name` to `resource_location` per edition. **The join key** between wiki pages and vanilla data. |
| `crafting_recipe` | 640 | Grid recipes with `A1`–`C3` slot positions, ingredient/output page arrays, category |
| `droptable` | 233 | Mob drops with per-looting-level distributions, drop chance, min/max/average — **already split into `java` and `bedrock` keys** |
| `spawn_table` | — | Biome, spawn category, weight, group size, edition |
| `advancement` | — | Title, `internal_id` (e.g. `story/root`), parent, wiki description, reward |
| `trade` | 280 | Villager trades: profession, level, quantities, price multiplier, max uses, XP — **`java_probability` and `bedrock_probability` are separate fields** |
| `spritefile` | 3524 `InvSprite` + 1361 `BlockSprite` | Sprite ID to wiki `File:` page. **The icon source** — see below. |

**The wiki collapses variants, which is why the row counts look low.** 640 crafting recipes is not
a partial scrape — a single row covers every wood type at once:

```
output: ['Matching Wooden Stairs', 'Oak Stairs', 'Spruce Stairs', ..., 'Warped Stairs']
```

**Rendering them collapsed is the intended behavior, not a compromise.** One row reading "Wooden
Stairs — any plank type" is easier to read mid-match than thirteen near-identical entries, and it
means the pipeline never has to expand `Matching <X>` groups or guess which variants a group covers.

The thing this must not break: **every variant still needs its own searchable page.** Typing
`oak stairs` has to land somewhere. So entity enumeration comes from Tier A, which lists all 1,658
items exactly, while the recipe *display* stays collapsed. Enumeration and presentation are
separate concerns and only the first one needs to be exhaustive.

**Tier A is the completeness and correctness layer. Tier B is the presentation layer.**

**Biome climate splits across two sources.** Do not assume one covers everything.

Biome pages *do* have a **Climate** group in the infobox — it is a group label inside
`Infobox biome`, not a `== Climate ==` heading, so searching the wikitext for a section heading
will miss it. It holds three values:

| Field | Jungle |
|---|---|
| Temperature | 0.95 |
| Downfall | 0.9 |
| Precipitation | Yes |

Those same three are already in mcmeta's `worldgen/biome/<id>.json` as `temperature`, `downfall`,
and `has_precipitation`, with identical values. **Take them from mcmeta** — Tier A, no scraping,
no parsing.

The other four parameters that drive Overworld placement — **continentalness, erosion, weirdness,
and depth** — are not in the infobox, and mcmeta gives only a preset reference:

```json
{"preset": "minecraft:overworld"}
```

The real ranges are hardcoded in game code, but the wiki documents them in full. **They live on
`World generation`, section 4 (Biomes → Overworld) — not on the `Biome` page.** The `Biome` page
here has only a `Climate` section covering temperature, downfall, and precipitation; the older
Fandom wiki put Continentalness/Erosion/Weirdness on `Biome`, which is why searching for them
there comes up empty.

`World generation` §4 carries the level definitions (temperature and humidity have 5 levels each,
erosion has 7: `-1.0..-0.78`, `-0.78..-0.375`, …) plus **8 tables** mapping parameter space to
biomes, using `T=`/`H=`/`PV=` shorthand and inland categories:

```
E=0 | Valleys | Frozen River [T=0] / River [T>0] | Middle biomes [T<4] / Badland biomes [T=4]
```

Two warnings about this data:

1. **The noise `temperature` parameter is not the biome's `temperature` property.** The wiki says
   so outright. The infobox value (Jungle `0.95`) and the noise level (`T=0`..`T=4`) are different
   things that happen to correlate. Conflating them is a subtle, plausible-looking data bug.
2. **These tables are conditional, not scalar.** They map parameter ranges *to* biomes; a biome
   page needs the inverse. Full 6D inversion is not worth it — extract the rows that mention the
   biome and render those conditions, rather than pretending each biome has one erosion value.

**Use minecraft.wiki, not Fandom, for this.** Fandom is still edited but runs behind: as of writing
its `Biome` page was last touched 2026-06-18 against 2026-08-02 for `World generation` here, and it
was already missing 26.x content such as Poplar. Mixing wikis would also mean two scrapers and two
attribution obligations for the same facts.

One more mcmeta gap: `spawners` in the biome JSON is **empty**, so per-biome mob lists come from
the wiki's `spawn_table` bucket rather than Tier A.

**Intro blurbs** come from the TextExtracts extension, which is installed:

```
action=query&prop=extracts&exintro=1&explaintext=1&titles=Creeper
```

**Wikitext fallback** — `action=parse&prop=wikitext` for the infobox fields Bucket does not cover
(health, damage, size, usable items). Expect this to be messy. A real `Infobox entity` field mixes
prose, HTML line breaks, and both editions inline, roughly:

```
| damage = '''{{IN|JE}}:''' ... Easy: {{hp|22.5}} ... '''{{IN|BE}}:''' ... Easy: {{hp|14.75}}
```

So the wikitext parser must strip `{{IN|BE}}` and `{{only|bedrock}}` blocks before reading values,
and must handle difficulty-tiered numbers rather than assuming a single scalar. Anything this
parser cannot resolve confidently should fail loudly into a report, not guess — the curated tier
exists to absorb those cases.

**Licensing.** Minecraft Wiki content is CC BY-NC-SA 3.0 and requires attribution; every entity
keeps a `wikiUrl` and the UI must surface a visible credit. Game textures and fonts remain
Mojang's regardless of where we fetch them from. Mojang's brand guidelines permit non-commercial
fan projects to use game assets, which is what this is — so keep the project free and
non-commercial, and keep the attribution visible.

## Sprites and icons

**Icons come from the wiki, not from `client.jar`.** The `spritefile` bucket maps a sprite ID to
its wiki `File:` page, and the file resolves to a direct URL through the standard imageinfo API:

```
action=query&titles=File:Invicon Diamond.png&prop=imageinfo&iiprop=url|size|mime
```

Naming conventions confirmed against the live wiki:

| Kind | Pattern | Size |
|---|---|---|
| Items | `Invicon <Display Name>.png` | 16×16, ~200 B |
| Blocks | `BlockSprite <id>.png` | 16×16 |
| Mobs | `EntitySprite <id>.png` | 16×16, ~450 B |
| Effects | `EffectSprite <id>.png` | 18×18, ~420 B |

**Always resolve filenames through the `spritefile` bucket — never construct them by hand.** The
mapping is not derivable: `Raw Iron` resolves to `Invicon Raw Iron.png`, but `Pancake Stack`
resolves to `PancakeInvSprite.png`. Guessing will silently produce broken icons for exactly the
irregular entries nobody checks.

**Pack everything into a single atlas at build time.** Roughly 4,900 sprites at ~250 bytes each is
small in total, but shipping them as individual files would mean 4,900 HTTP requests and would eat
most of Cloudflare Pages' 20,000-files-per-site limit. Emit one atlas image plus a JSON coordinate
map. All sprite rendering uses `image-rendering: pixelated` — no smoothing, ever.

Downloads are cached on disk by content hash so a rebuild does not refetch unchanged icons.

## Deployment

### What actually ships

The whole deployed site is a directory of ordinary files. Nothing here needs a server, a runtime,
or a database:

```
index.html
assets/app-<hash>.js          Vanilla TS, bundled and minified
assets/app-<hash>.css
data/index.json               Search payload, loaded at boot
data/entities/<shard>.json    Tens of shards, fetched on demand
data/sprites.png              One atlas
data/sprites.json             Atlas coordinate map
data/manifest.json            Version + build time
```

Drop that on any static host — GitHub Pages, Cloudflare Pages, Netlify, S3, or a plain nginx root.
Expected total is well under 20 MB, against a GitHub Pages limit of 1 GB, so size is not a
constraint on any host worth considering.

**GitHub Pages works, and always will.** The pipeline is the only thing that touches the network,
it runs on your machine or in CI, and its entire output is the `data/` files above, committed to
the repo. The browser never talks to the wiki, mcmeta, or Mojang.

One thing to watch, not a blocker: committing `/data/dist` means regenerated JSON lands in git
history on every Minecraft release. At a few MB per release and a handful of releases a year, this
is fine for years. If it ever bloats, move `/data/dist` to its own branch rather than un-committing
it — the site build depending on committed data is what keeps deployment this simple.

### Choosing a host

Static output, so this deploys anywhere. **Cloudflare Pages is the recommended target**: static
asset bandwidth and requests are unmetered, which matters because Vercel's Hobby plan caps at
100 GB/month and *pauses the project* when exceeded, with no overage option. Vercel Hobby also
forbids commercial use, defined broadly enough to include a paid contributor.

Cloudflare Pages free-plan limits that actually constrain us: **20,000 files per site** (hence the
sprite atlas, and why entity JSON is sharded into tens of files rather than one file per entity),
**25 MiB per file**, and 500 builds/month.

GitHub Pages is a fine fallback if you want one less account — the tradeoff is a 1 GB site limit
and softer bandwidth guarantees. Vercel works too; just be aware of the pause behavior above.

## The Entity model

Everything searchable is an `Entity`, discriminated by `kind`:
`mob | item | block | effect | advancement | enchantment | structure | biome | collection`.

Shared fields: `id` (namespaced, e.g. `minecraft:creeper` or `collection:compostable`), `name`,
`aliases[]`, `icon`, `blurb`, `wikiUrl`, `sections[]`, `sourceTiers`.

`sections[]` is an ordered discriminated union of render blocks — `StatBlock`, `SpawnInfo`,
`DropTable`, `RecipeTree`, `ObtainList`, `BreedingInfo`, `EffectSources`, `AdvancementInfo`,
`TradeTable`, `ChestLoot`, `EnchantInfo`, `GenerationInfo`, `LinkList`. The renderer switches on
section type, so adding a new kind of content means adding one section type and one renderer, not
touching the window system.

### "Where do I get X" — take it from the wiki, do not rebuild it

The wiki already aggregates every acquisition path on each item page under `== Obtaining ==`, with
subsections for Crafting, Generated loot, Fishing, and Trading. **Use that. Do not build inverted
indexes off the raw loot tables** — it is duplicated effort against a source that already did it.

The wikitext is not what you want, though. It contains bare template calls:

```
=== Generated loot ===
{{LootChestItem|name-tag}}
=== Trading ===
{{Trade sources}}
```

Fetch the **rendered** section instead (`action=parse&prop=text&section=N`) and the templates
expand into full tables. Better still, the loot rows carry a machine-readable JSON blob inline:

```json
{"item": "Name Tag", "stacksize": 1, "chance": 0.25295067443987196,
 "structure": "Monster Room", "container": "Chest"}
```

So parse the embedded JSON rather than scraping the surrounding table markup. Two cautions: the
section index for `Obtaining` varies per page, so resolve it from `prop=sections` rather than
hardcoding; and these tables can be headed "Java Edition and Bedrock Edition" when the two agree,
so edition filtering still applies wherever they diverge.

An item whose Obtaining section yields nothing is a scrape failure, not an unobtainable item.
Report it.

Cross-references between entities are `EntityRef` objects, never bare strings. They render as
clickable links that open the target in a new window, which is what makes the collection pages
work as navigation hubs.

**Link everything that names another entity.** If a mob spawns in a biome, that biome is a link. If
a structure generates in a biome, link. Loot table to structure, structure to its chests, trade to
the item, enchantment to what accepts it, ingredient to its own page. The rule for renderers: any
time you are about to print an entity's name as plain text, you are looking at a missing
`EntityRef`. Navigation by link is the fast path — faster than typing a new query — so a name that
does not link is a dead end where a jump should be.

## Recipe trees

Item pages show a single obtain-tree rooted at the item. **Brewing is part of this tree, not a
separate renderer.** A potion node expands into its brewing step, and each ingredient of that step
keeps expanding by whatever produces it — so Potion of Weakness walks down to fermented spider eye,
then into the crafting recipe for fermented spider eye, then into sugar and brown mushroom and
spider eye. The brewing stand itself expands into its own crafting recipe. One tree, one set of
rules, no special cases.

This is the most failure-prone renderer:

- **Cycles are real** (iron ingot to block of iron and back). Detect and cut them; never recurse
  blindly.
- **Memoize** by item ID within a single tree.
- **Default depth is 3**, expandable in the UI. Full expansion of something like a beacon is
  unreadable and slow.
- **Repeated subtrees collapse** to a back-reference rather than re-rendering.
- **Terminal nodes** are raw acquisition: mined, mob drop, chest loot, villager trade, natural
  generation. A leaf with no acquisition path is a data bug worth reporting.

## Commands

```
pnpm dev              Web app dev server
pnpm build            Build web app from committed data
pnpm test             Web tests. Fails first when /web/types is out of date
pnpm schema:types     Rewrite /web/types from /pipeline/schema. `pnpm build` runs it too
pnpm lint             ESLint over the web app, the build config, and the build scripts
pnpm format           Prettier writes; `pnpm format:check` only reports

python -m pipeline check      Compare latest Mojang release against data/dist/manifest.json
python -m pipeline build      Run the full pipeline (hits the network; no Java needed)
python -m pipeline validate   Re-run schema + regression checks on existing output
pytest                        Pipeline tests
ruff check .                  Lint the pipeline
mypy                          Type check the pipeline, strict mode
```

The web app never invokes the pipeline. Building the site reads `/data/dist` and nothing else.

## Conventions

- **Two languages, one contract.** The pipeline is Python (typed, Pydantic-validated); the web app
  is strict TypeScript. They never import from each other — they meet at the JSON in `/data/dist`.
  `/pipeline/schema` holds the JSON Schema that defines that boundary: the pipeline validates its
  output against it, and the web app's TS types are generated from it. Change the schema and both
  sides fail loudly, which is the point.
- **No UI framework.** The web app is vanilla TypeScript — a search bar, a suggestion list, at most
  four windows, and a set of renderers. React would add runtime weight to the one thing that must
  stay fast, for state that fits in a hundred lines. Vite is a build tool here, not a runtime; the
  deployed artifact is plain HTML, CSS, and JS. Do not introduce a framework without asking.
- Pipeline stages are pure functions from input files to output files. Every stage is independently
  runnable and writes intermediates to `/data/.cache` so a failing late stage does not force a
  re-fetch of the whole mcmeta tree or several thousand sprites.
- Network fetches are cached on disk by content hash and rate-limited. Be a good citizen with the
  wiki API — it is a volunteer-run service.
- Never hand-edit `/data/dist`. Fix the pipeline or add a curated override.
- Entity IDs are always namespaced. Display names are never used as keys.

## Gotchas

- Search must match on aliases, not just names. Typing `weak` needs to surface both the Weakness
  effect and the Potion of Weakness. The alias table is a first-class data file, not an afterthought.
- The wiki's `display_name` does not always match the vanilla registry name. Always join through
  the `resource_location` bucket.
- Composter values and food properties used to be hardcoded in game code, and older guides still
  say so. That is **out of date** — the component rework moved them into item data, and they now
  come from Tier A via `summary/item_components`. Mob attributes (health, damage) really are still
  code-side, so those stay Tier B.
- `item_components` keys are unprefixed. Looking up `minecraft:apple` returns nothing, silently.
- A build that produces fewer entities than the previous build is almost always a broken scrape,
  not a Minecraft update. The validation gate enforces this.
