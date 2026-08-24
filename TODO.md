# MC-FastWiki — Build Plan

Phases are ordered by dependency. Each phase ends at something demonstrable, so progress is
visible before the whole thing works. Read `CLAUDE.md` / `AGENTS.md` first for architecture and
the verified data-source details.

**Resolved decisions** are recorded at the bottom alongside the remaining open questions, so the
reasoning survives even after the choice is made.

---

## Phase 0 — Foundations

- [ ] Python 3.12+ pipeline package with `uv` or `pip-tools`; `ruff` + `mypy` strict
- [ ] Web app scaffold: **vanilla TypeScript + Vite, no UI framework** (see Decision 5)
- [ ] TypeScript strict config, ESLint, Prettier, Vitest; `pytest` for the pipeline
- [ ] `/pipeline/schema` — JSON Schema as the contract; generate TS types from it in `pnpm build`
- [ ] `.gitignore` — ignore `/data/.cache`, **commit** `/data/dist`
- [ ] `.gitattributes` — mark `/data/dist/**` as generated so diffs collapse in review
- [ ] README states Python and Node versions. **No Java requirement** — say so explicitly, since
      every other Minecraft data project needs it and contributors will assume this one does too.

## Phase 1 — Vanilla data (Tier A, from mcmeta)

No jars and no JVM — `misode/mcmeta` publishes the data generator output as JSON. See Decision 6.

- [ ] Fetch `version_manifest_v2.json` for the current release ID only (drives `check`)
- [ ] Resolve the matching mcmeta **version tag** (never a bare branch head — builds must be
      reproducible, and a snapshot must not slip into a release build)
- [ ] Fetch and cache by content hash:
  - [ ] `registries` — canonical ID lists for items, blocks, entities, effects
  - [ ] `data/recipe/` — crafting, smelting, smithing, stonecutting
  - [ ] `data/loot_table/` — entity, block, and chest tables
  - [ ] `data/advancement/` — criteria, requirements, parent chains
  - [ ] `data/tags/` — item, block, and entity_type tags
  - [ ] `summary/blocks` — block states and properties
  - [ ] `summary/item_components` — food, compostable, fuel (**keys are unprefixed** — `apple`,
        not `minecraft:apple`; a prefixed lookup fails silently)
- [ ] Derive block harvest requirements from `mineable/*` and `needs_*_tool` tags
- [ ] Fall back to running Mojang's generator only if mcmeta ever lags a release — document the
      escape hatch in `/docs`, but do not build it until it is actually needed
- [ ] Snapshot the extracted shape to a fixture so parser regressions are caught by tests

## Phase 2 — Wiki enrichment (Tier B)

- [ ] Bucket API client: Lua query builder, `offset()` pagination past the 5000-row cap, disk
      cache, rate limiting, retry with backoff
- [ ] Pull `resource_location` (Java rows only) and build the **display name to registry ID join
      table** — this unblocks everything else in this phase
- [ ] Pull `droptable`; parse the `json` column, **keep only the `java` key**, preserve
      per-looting-level distributions
- [ ] Pull `spawn_table`; filter `Edition == java`; group by mob into biome/weight/group-size rows
- [ ] Pull `crafting_recipe`; parse `A1`–`C3` grid slots into a shape comparable with Tier A
      recipes (used as a cross-check, not as the primary source)
- [ ] Pull `advancement`; join on `internal_id` to the Tier A advancement tree
- [ ] Pull `trade` (280 rows); **keep `java_probability`, drop `bedrock_probability`**; group by
      profession and level
- [ ] Fetch intro blurbs via `prop=extracts&exintro&explaintext`, batched
- [ ] Wikitext infobox parser for what Bucket does not cover: health, damage, size, usable items
  - [ ] Strip `{{IN|BE}}` / `{{only|bedrock}}` regions **before** reading any value
  - [ ] Handle difficulty-tiered damage (easy/normal/hard) rather than assuming one number
  - [ ] Unresolvable fields go to an `unparsed-report.json`, never a silent guess
- [ ] Pull `spritefile` (paginated past 5000) to build the sprite ID to `File:` name map
- [ ] Resolve `File:` pages to image URLs via `prop=imageinfo`, download with content-hash caching
- [ ] Report any entity that ends up with no icon — a missing icon is a broken join, not a
      cosmetic gap
- [ ] Reconcile Tier A against Tier B: report entities present in one but missing in the other

## Phase 3 — Normalization and emit

- [ ] Define the `Entity` model and the `Section` discriminated union in shared types
- [ ] Merge tiers with per-field provenance (`sourceTiers`)
- [ ] Curated override loader; warn when `verifiedFor` is behind the target version
- [ ] Alias generation — the quality bar for search. Cover:
  - [ ] Registry ID segments (`golden_apple` matches "golden", "apple")
  - [ ] Effect and potion cross-linking (`weak` finds Weakness *and* Potion of Weakness)
  - [ ] Common community shorthand (`gapple`, `efficiency 5`, `pearl`, `blaze rod`)
  - [ ] Hand-written extras in `/data/curated/aliases.json`
- [ ] Build one unified obtain-tree: recipes, smelting, **brewing**, loot, chest loot, trades,
      natural generation. Brewing is a node type in this tree, not a separate structure — a potion
      expands into its brewing step, each ingredient expands into whatever produces it (fermented
      spider eye into its crafting recipe, and on down), and the brewing stand expands into its own
      recipe. One set of rules, no special cases.
  - [ ] Cycle detection and memoization
  - [ ] Depth cap with expandable nodes
  - [ ] Repeated-subtree collapse to back-reference
- [ ] Pack all sprites into a single atlas image plus a JSON coordinate map (keeps the site under
      Cloudflare's 20,000-file cap and avoids ~4,900 requests)
- [ ] Emit: `index.json` (search payload), sharded entity JSON, sprite atlas, `manifest.json`
      (version + build time). Keep shard count in the tens — never one file per entity.
- [ ] Validation gate: Pydantic models validated against `/pipeline/schema`, plus a regression
      check that fails the build if entity count
      drops more than 5% or a required field disappears across versions

## Phase 4 — Search

- [ ] Choose the matcher — recommend `@leeoniya/uFuzzy` (tiny, fast, built for short prefix queries)
- [ ] Load `index.json` at boot; measure and record the gzipped size
- [ ] Ranking: exact match, then prefix, then alias hit, then fuzzy — with a popularity/kind tiebreak
      so `villager` surfaces the mob above every villager-adjacent item
- [ ] Benchmark: keystroke to updated list under 16 ms on the full index

## Phase 5 — Shell UI

- [ ] Blank canvas, search bar pinned to the bottom, layered above all windows
- [ ] Autofocus the bar on any click anywhere on the page, and on any printable keypress
- [ ] Suggestion list above the bar, first item selected by default
- [ ] Up/Down to move selection, Enter to open, Esc to clear the query
- [ ] Window manager, maximum 4 windows; **bar hides at 4** and returns when one closes
- [ ] Grid layout: 1 full-screen, 2 side by side (left | right), 3 as a 2x2 with one empty cell,
      4 as a full 2x2. Window positions must stay stable as the count grows — opening the fourth
      window must not move the first three.
- [ ] Per-window independent scroll, X button top-right, keyboard close shortcut
- [ ] Window focus model — which window a link click or a new search targets when 4 are open
- [ ] Full keyboard map documented in-app (a `?` overlay or similar)

## Phase 6 — Content renderers

- [ ] **Mob** — HP and damage badges beside the name (damage only when hostile), spawn conditions,
      loot table with looting tiers, breeding items when breedable
- [ ] **Item** — obtain tree, crafting and smelting, with the correct tool shown for blocks
- [ ] **Block** — harvest tool and tier, drops, natural generation
- [ ] **Effect** — every source of the effect, and what it actually does
- [ ] **Advancement** — how to earn it, parent chain, reward
- [ ] Intro blurb rendered at the top of every entity that has a wiki page
- [ ] Inline `EntityRef` links open the target in a new window
- [ ] Visible CC BY-NC-SA attribution and a link back to the source wiki page
- [ ] Render crafting recipes **collapsed** — "Wooden Stairs — any plank type" rather than
      thirteen near-identical rows (see Decision 9)

## Phase 6b — Obtaining, scraped from the wiki

The wiki already aggregates every acquisition path per item. Take it rather than rebuilding it from
loot tables (see Decision 11).

- [ ] Resolve the `Obtaining` section index per page via `prop=sections` — it varies, so never
      hardcode a section number
- [ ] Fetch the **rendered** section (`prop=text`), not wikitext — wikitext holds only unexpanded
      template calls like `{{LootChestItem|name-tag}}` and `{{Trade sources}}`
- [ ] Parse the **embedded JSON** in generated-loot rows rather than the table markup:
      `{"item":"Name Tag","stacksize":1,"chance":0.2529...,"structure":"Monster Room",
      "container":"Chest"}`
- [ ] Parse the Trading table, keeping the JE column and dropping BE
- [ ] Keep the other subsections that appear — Crafting, Fishing, and anything else the page lists
- [ ] Tables headed "Java Edition and Bedrock Edition" mean the two agree; still apply edition
      filtering where they diverge
- [ ] Rate-limit and cache: this is roughly one request per item page. It is a one-time cost per
      Minecraft version, but be a good citizen about it
- [ ] An empty Obtaining result is a **scrape failure, not an unobtainable item** — report it

## Phase 6c — Additional entity kinds

- [ ] **Enchantments** (43, Tier A) — max level, applicable items, anvil cost, enchanting table
      cost range, and `exclusive_set` so the page answers "can I combine Sharpness and Smite"
- [ ] **Villager professions** — searching `librarian` opens a page listing that profession's
      trades grouped by level (Novice through Master). The `trade` bucket carries profession,
      level, quantities, price multiplier, max uses, and XP. **Keep `java_probability`, drop
      `bedrock_probability`**
- [ ] **Structures** (52, Tier A) — where they generate, and the chests inside them. The `biomes`
      field is a tag reference (`#minecraft:has_structure/village_plains`), so resolve it through
      tag data rather than reading it as a literal
- [ ] **Biomes** (67, Tier A) — what spawns there, what generates there, which structures appear
- [ ] **Biome climate — two sources, do not assume one covers it**
  - [ ] Temperature, downfall, precipitation: take from mcmeta `worldgen/biome/<id>.json`
        (**Tier A**, no scraping). The biome infobox has a `Climate` group with the same three
        values, but there is no reason to parse it when the data is already in Tier A
  - [ ] Continentalness, erosion, weirdness, depth: in **neither** the infobox nor mcmeta, which
        gives only `{"preset": "minecraft:overworld"}`. Parse **`World generation` section 4**
        (Biomes → Overworld) — 8 tables plus the level definitions. Not the `Biome` page: that has
        only temperature/downfall/precipitation. Fandom put these on `Biome`, this wiki did not
  - [ ] Handle the `T=`/`H=`/`PV=` shorthand and inland categories in those tables
  - [ ] **Do not conflate the noise `temperature` parameter with the biome `temperature` property.**
        Jungle's infobox says `0.95`; the noise level is `T=0`..`T=4`. Different things that
        correlate — an easy and very plausible-looking bug
  - [ ] Render the matching table rows per biome rather than inverting the full 6D space into one
        scalar per biome. The tables are conditional; pretending otherwise would be wrong
  - [ ] Do not try to extract erosion/depth from biome page prose — mentions like "bordering
        mangrove swamps at high erosion" are not structured values
  - [ ] Source from minecraft.wiki, not Fandom — Fandom lags (last edit 2026-06-18 vs 2026-08-02
        here) and was already missing 26.x content like Poplar
- [ ] **Per-biome mob lists** — mcmeta's biome `spawners` field is empty, so these come from the
      wiki `spawn_table` bucket, not Tier A
- [ ] **Brewing folded into the recipe tree** — not a separate renderer. See Phase 3

### Cross-linking

- [ ] Mob spawns in a biome → the biome is a link
- [ ] Structure generates in a biome → link, both directions
- [ ] Structure → its chests → the items in them
- [ ] Trade → the item traded; item → the professions that sell it
- [ ] Enchantment → the items that accept it
- [ ] Lint pass: flag any renderer printing a known entity name as plain text instead of a link

## Phase 7 — Collections (the special search terms)

Build these data-driven from a `/pipeline/collections/*.yaml` manifest — a title, a blurb, and a
member-resolution rule (a vanilla tag, a Bucket query, or an explicit list). Adding a new
collection should mean adding one manifest file, never writing code.

- [ ] Collection manifest format and resolver
- [ ] `compostable` — all compostable items with their tier, straight from the
      `minecraft:compostable` component (**122 items, Tier A** — no curation needed)
- [ ] `unique_food` — all food items with nutrition and saturation, from the `minecraft:food`
      component (**44 items, Tier A**)
- [ ] Consider a `fuel` collection too — `minecraft:cooking_fuel` covers 347 items and comes free
- [ ] Mob type groups: `arthropods`, `undead`, and the rest — prefer `entity_type` tags, fall back
      to curated lists where no tag exists
- [ ] `armor_trims` — every trim, how to obtain it, and which chests it generates in
- [ ] `banner_patterns` — all unique banner pattern recipes
- [ ] `workstations` — all workstation block recipes
- [ ] `minecarts` — all minecart recipes
- [ ] Every member renders as a link that opens the real entity window

New collections the added data makes nearly free:

- [ ] `fuel` — its own search keyword, 347 items with burn times, from `minecraft:cooking_fuel`
- [ ] `enchantments` — the full list, grouped by what they apply to
- [ ] `structures` — every structure and its biome
- [ ] `chest_loot` — every lootable chest, as a hub into the structures that contain them
- [ ] `villager_trades` — professions as an index into the trade tables

## Phase 8 — Minecraft theming

- [ ] Pixel typeface — use an open font that reads as Minecraft rather than shipping Mojang's own
- [ ] GUI panel styling: beveled 3D borders, stone/dirt surfaces, inventory-slot framing
- [ ] Sprite atlas rendering with `image-rendering: pixelated`; no smoothing, ever
- [ ] Icons beside every entity name, in suggestion rows, and inside recipe grids
- [ ] Hostile/passive and rarity color coding consistent across every renderer
- [ ] Accessibility pass: contrast, focus rings, and a reduced-motion path — the pixel aesthetic
      must not make the tool unreadable under match pressure

## Phase 9 — Auto-update

- [ ] `python -m pipeline check` compares the latest Mojang release to the built manifest
- [ ] Scheduled CI (daily) runs the check; on a new version it runs the full pipeline (no JDK
      needed in the runner — Python and Node only)
- [ ] CI opens a PR with the regenerated data and a human-readable diff summary
      (entities added, removed, changed)
- [ ] Validation gate blocks the PR on suspicious diffs rather than auto-merging
- [ ] Weekly wiki-only refresh so blurb and stat corrections land without a Minecraft release
- [ ] Deploy to Cloudflare Pages on merge to `main` (see Decision 4)
- [ ] Assert the build stays under 20,000 files and 25 MiB per file, so a deploy never fails on a
      platform limit that a passing local build would not catch

## Phase 10 — Performance and offline

- [ ] Service worker precaches the index and shell
- [ ] Entity payloads cached in IndexedDB, versioned by build manifest
- [ ] Measure and enforce the two budgets: 16 ms per keystroke, 100 ms to rendered window
- [ ] Confirm the app works fully offline after first load

---

## Decisions made

1. **Two-window split — side by side (left | right).** Suits widescreen and extends naturally into
   the 2x2 grid.
2. **Three windows — 2x2 grid with one empty cell.** Windows keep their position when the fourth
   opens, rather than reflowing the whole layout on every open.
3. **Sprites from the wiki, not from `client.jar`.** Confirmed working: the `spritefile` bucket
   maps sprite IDs to `File:` pages, and `prop=imageinfo` resolves those to direct URLs. Item icons
   are `Invicon <Name>.png` at 16×16 and ~200 bytes; mobs use `EntitySprite <id>.png`, effects use
   `EffectSprite <id>.png` at 18×18.

   This beats jar extraction on every practical axis: no 40 MB `client.jar` download, no Java
   needed for icons, and the sprites arrive already cropped and normalized. The licensing picture
   is also no worse — the textures are Mojang's wherever we get them, and Mojang's brand guidelines
   permit non-commercial fan projects, which is what this is.

   The one hard rule: **resolve filenames through the bucket, never construct them.** `Raw Iron`
   maps to `Invicon Raw Iron.png`, but `Pancake Stack` maps to `PancakeInvSprite.png`. Guessing
   breaks exactly the irregular entries nobody thinks to check.

   The font is a separate matter — use an open pixel typeface rather than shipping Mojang's.

4. **Deploy to Cloudflare Pages.** For a purely static site it is strictly better than Vercel:
   static bandwidth and requests are unmetered, where Vercel's Hobby plan caps at 100 GB/month and
   *pauses the project* when exceeded, with no option to pay the overage. Vercel Hobby also forbids
   commercial use, defined broadly enough to cover a paid contributor. Vercel's whole pricing model
   is built around function invocations, and this project has none.

   Cloudflare's free-plan limits that actually shape the build: **20,000 files per site** (which is
   why sprites are atlased and entity JSON is sharded into tens of files), **25 MiB per file**, and
   500 builds/month. None of these bind us in practice, but CI asserts them so a deploy never fails
   on a limit a passing local build would not catch.

   GitHub Pages stays a viable fallback if you would rather not add an account — the cost is a 1 GB
   site limit and softer bandwidth guarantees.

5. **No UI framework.** Vanilla TypeScript, with Vite as a build tool rather than a runtime. The
   deployed artifact is plain HTML, CSS, and JS. The app is a search bar, a suggestion list, four
   windows, and a set of renderers — React would add runtime weight to the one thing that has to
   stay fast. Note that a build step is unavoidable regardless, because the data pipeline needs one.

6. **No Java. Tier A comes from `misode/mcmeta`.** That project runs Mojang's data generator and
   publishes the output as JSON on GitHub, tagged per version. Verified current: `summary` was
   updated for `26.3-snapshot-9` the same day that snapshot released. So the pipeline fetches JSON
   instead of downloading a 61 MB jar and shelling out to a JVM.

   This removes the only reason the project needed Java, and it makes the pipeline pure I/O — which
   is what makes Python a sensible choice for it (Decision 7).

   Keep Tier A rather than going wiki-only. The wiki **collapses variants**: one recipe row covers
   all 13 wood types as `['Matching Wooden Stairs', 'Oak Stairs', ...]`. Expanding those groups back
   into exact per-item recipes is guesswork, and a wrong recipe is exactly the failure that costs a
   match. mcmeta gives exact per-item data for free, so there is no reason to guess.

7. **Pipeline in Python, web in TypeScript.** Now that Tier A is plain JSON fetching, the pipeline
   is pure data munging and Python fits it well. The two sides never import from each other — they
   meet at the JSON in `/data/dist`, with `/pipeline/schema` holding the JSON Schema that defines
   the boundary. The pipeline validates its output against it; the web app generates its TS types
   from it.

8. **No runtime fetching, and no "loading page" that scrapes on open.** The wiki API does send
   `Access-Control-Allow-Origin: *`, so this is technically possible — it is ruled out on merit,
   not feasibility. It would put dozens of round trips between a keystroke and an answer against a
   100 ms budget, break mid-match whenever the wiki is slow or down, and load a volunteer-run
   service on every page open. Pre-building is faster, more reliable, and a better neighbor.

   Worth being explicit, since this caused confusion once already: **the build step does not make
   the site less static.** The pipeline runs on your machine or in CI and writes JSON files. The
   browser only ever loads HTML, CSS, JS, and those files. Both things are true at the same time.

9. **Crafting recipes render collapsed.** "Wooden Stairs — any plank type" rather than thirteen
   near-identical rows. This is easier to read mid-match *and* saves the pipeline from expanding
   `Matching <X>` variant groups, so it is a simplification in both places.

   The constraint it must not break: every variant still needs a searchable page, because typing
   `oak stairs` has to land somewhere. Enumeration comes from Tier A (all 1,658 items, exactly);
   only the recipe *display* collapses. Keep those two concerns separate.

10. **Keep Tier A even though recipes are collapsed.** Worth restating, because "collapsed is fine"
    sounds like it removes the reason for mcmeta. It does not. mcmeta is one JSON fetch with no
    Java, and it is what supplies exhaustive item enumeration, entity tags for the mob-group
    collections, all 43 enchantments, 52 structures, 67 biomes, 31 chest loot tables, and the
    food/compostable/fuel components. Dropping it would push five of the planned pages back onto
    hand-curation to save one HTTP fetch.

11. **Obtaining comes from the wiki's own section, not from inverted loot tables.** I had planned
    to build reverse indexes off the raw loot tables. Unnecessary — every item page already has an
    `== Obtaining ==` section covering crafting, generated loot, fishing, and trading in one place.

    The catch is that the wikitext holds only unexpanded template calls (`{{LootChestItem|name-tag}}`,
    `{{Trade sources}}`). Fetch the **rendered** section instead and they expand — and the loot rows
    carry machine-readable JSON inline, so this is structured extraction rather than prose scraping:

    ```json
    {"item":"Name Tag","chance":0.2529...,"structure":"Monster Room","container":"Chest"}
    ```

    Two gotchas: the `Obtaining` section index varies per page, so resolve it from `prop=sections`;
    and an empty result means the scrape broke, not that the item is unobtainable.

12. **Brewing is part of the recipe tree, not a parallel one.** A potion node expands into its
    brewing step; every ingredient of that step keeps expanding by whatever produces it. Potion of
    Weakness walks down to fermented spider eye, then into that item's crafting recipe, then to
    sugar and brown mushroom and spider eye. The brewing stand expands into its own recipe too.

13. **Link everything that names another entity.** Mob to biome, structure to biome, structure to
    its chests, trade to item, enchantment to what accepts it. Clicking is faster than typing a new
    query, so a name rendered as plain text is a dead end where a jump should be. Enforced with a
    lint pass rather than left to renderer discipline.

## Still open

1. **Match-specific extras.** Since this is for draftout matches — is there value in pinning
   frequently used entities, or a saved layout you can restore between rounds?
2. **Scope ceiling.** The additions in Phases 6b/6c are the ones with clear match value. Paintings,
   music discs, and sound events are all reachable but look like noise — leaving them out unless
   you disagree.

## Deliberately out of scope

Recorded so these do not creep in later: Bedrock Edition, mod content, full wiki article text,
editing or contributing back to the wiki, and multiplayer or sync features.
