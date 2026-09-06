# MC-FastWiki — Build Plan

Phases are ordered by dependency. Each phase ends at something demonstrable, so progress is
visible before the whole thing works. Read `CLAUDE.md` / `AGENTS.md` first for architecture and
the verified data-source details.

**Resolved decisions** are recorded at the bottom alongside the remaining open questions, so the
reasoning survives even after the choice is made.

---
## Phase 6 — Content renderers

- [ ] **Block** — drops and natural generation.
      Harvest tool and tier ship as the `HarvestInfo` section from `pipeline/extract/harvest.py`.
      Block drops ship in `HarvestInfo.drops` from mcmeta loot tables via `pipeline/normalize/merge.py`,
      rendering interactively on web alongside tool and tier requirements.
      Natural generation is still open: no natural-generation data reaches `data/dist` at all.
- [ ] **Effect** — every source of the effect, and what it actually does.
      Zero `EffectSources` sections exist in the build, so the effect renderer is blocked on a pipeline emit.

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
- [ ] Lint pass: flag any renderer printing a known entity name as plain text instead of a link.
      The named cases this bullet was written for are resolved: `Potato`, `Pufferfish (item)`,
      `Arrow of Poison` and `Music Disc <Song>` all carry an `itemRef` now, through the rules
      Decision 20 records. What is left is the general case, and it is still worth a lint, because
      the rules were found by reading a rendered page rather than by any check that would have
      reported them.
      The remaining ref-less names are the ones a lint has to learn not to flag, and the 33 the
      26.2 build still reports fall into three groups, none of them a fault: `Any color Wool`,
      `Any color Bed` and the rest of that family name a variant group rather than one registry
      entry; `Explorer Map`, `Ocean Explorer Map` and `Banner` name map or pattern data carried on
      a stack; and `Cold Chicken`, `Pale Wolf` and the other mob-variant names are wiki names for
      a texture variant that shares one `entity_type`.
      `data/reports/merge-report.json` lists all 33 as `unplaced`, which is where such a lint
      should read from rather than re-deriving the set.

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

14. **`uv`, not `pip-tools`.** Phase 0 left the choice open. `uv` resolves and installs in one
    tool, writes a `uv.lock` that pins every transitive version so a build is reproducible, and
    supports `package = false` for a project that is run from the repository root and never
    published to an index. `pip-tools` would need a separate virtualenv step and gives no
    equivalent lock across dependency groups.

15. **No maximum frame size in the sprite packer.**
    Measured by re-packing the committed frames through the real `pack_atlas` twice, once as-is and
    once with every frame over 32px resampled nearest-neighbour to 32x32.
    As-is packs to 512x2812 at 644925 bytes.
    Capped at 32px it packs to 512x2228 at 626338 bytes.
    So a 32px cap removes 584 canvas rows, 20.8% of the canvas height, and saves 18587 bytes, 2.9%
    of the PNG.
    The two figures diverge so far because the rows a cap reclaims are transparent, and deflate
    compresses a run of zero bytes to almost nothing.
    Nearest-neighbour is the optimistic end of that saving; a smoother resampling filter compresses
    worse, not better.

    The cap is rejected for three reasons.
    First, it buys 2.9% of the download, measured, which is not enough to justify the second and
    third reasons below.
    Second, it would put a resampling filter choice inside the one module that writes a committed
    binary, which is exactly the Pillow-version-drift hazard `pipeline.emit.atlas.encode_png`'s own
    docstring already refuses to accept for PNG row filters, and the same reasoning applies with
    more force to resampling.
    Third, it would not even fix the icon: the two sculk frames are full block renders in
    perspective, not inventory icons, so no resampling makes them read correctly beside a flat
    16x16 item sprite, which makes this a data fault, not a packing one.

    The curated per-sprite overrides naming verified `File:` titles for `InvSprite:Sculk`
    (`BlockSprite:sculk`), `InvSprite:Sculk Shrieker` (`BlockSprite:sculk-shrieker`), and
    `InvSprite:Zombie Horse Spawn Egg` (`ItemSprite:zombie-horse-spawn-egg`) were added to
    `/data/curated/overrides.json`, packing the atlas cleanly to 512x2228 without any packer-level
    resizing.
    The seven 1x1 frames (`Cave Air`, `Void Air`, and the five marker and display entities) are
    correct and need nothing, because the thing they draw really is invisible.

16. **Alias strength is recovered from the entity id, not from alias position.**
    `generate_aliases` tags every alias `FULL_PHRASE` > `CURATED` > `CROSS_LINK` > `SEGMENT`, but
    `EntityDraft._aliases` is a `dict[str, SourceTier]` and drops the strength tag at the merge
    boundary, so only the sorted order survives into `index.json`.

    Reading position as strength was tried first and is wrong. `generate_aliases` sorts
    strongest-first but **alphabetically inside one strength band**, so a position encodes
    spelling rather than strength: `diamond` sits at alias index 2 for `diamond_axe`, after
    `axe`, and at index 1 for `diamond_hoe`, before `hoe`. Comparing those indexes across
    entities made Diamond Ore, a block, outrank Diamond Axe for the query `diamond`. That
    reaches every entity whose registry path has more than one segment, so it is not an edge
    case.

    What the matcher does instead: an alias is a `FULL_PHRASE` alias exactly when it equals the
    registry path after the namespace, spelled with underscores or with spaces. That is what
    `_phrase_aliases` emits, so the strongest band is recovered exactly, from data the index
    already carries, and nothing depends on an ordering the pipeline is free to change.

    `CURATED`, `CROSS_LINK`, and `SEGMENT` remain indistinguishable, as do the two
    potion-specific `FULL_PHRASE` aliases that are not derived from the path; kind priority
    resolves the potion case. If a fault ever needs those finer bands, the verified alternative
    is a parallel `w` array of strength digits in `index.json` and the entity models, measured at
    +28 kB raw and +2.0 kB gzipped, and rejected here only because it changes the entity contract
    and grows every shard.

17. **Split name-clashing registry IDs into two pages only when their registries carry different display names.**
    Previously, one registry ID could produce only one entity page, causing the losing registry's
    meaning to be unreachable (e.g. `minecraft:chicken` was the Chicken mob, leaving Raw Chicken food
    item without a page).

    Rule: Split an ID only when its registries carry different wiki display names.
    This provides an objective, data-driven discriminator that excludes the 1,041 block + item pairs
    where both registries represent the identical concept to a player (e.g. Stone), while splitting
    genuinely distinct items and entities.

    Measured: Exactly 8 IDs split: `chicken`, `cod`, `egg`, `ender_pearl`, `experience_bottle`,
    `rabbit`, `salmon`, and `tnt`.
    The precedence winner (item/block) retains the bare ID (e.g. `minecraft:chicken` for Raw Chicken),
    while the entity side gains a qualified path `minecraft:entity_type/<path>` (e.g.
    `minecraft:entity_type/chicken` for the mob).

    Ranking: In `web/search/matcher.ts`, item ranks above entity/mob when both match an exact concept
    query (one by display name and the other by phrase alias), ensuring items take precedence while
    both pages remain discoverable.
    Also fixed: `minecraft:wheat` display name correctly resolves to "Wheat" rather than "Wheat Crops".

18. **Breeding is sourced from the wiki's `Breeding` page, and its timings are carried as data.**
    The mob infobox was the expected source, but all 179 cached mob infoboxes carry zero
    breeding parameters, so there was no field to read. The `Breeding` page's `Breeding foods`
    sortable wikitable carries structured `EntityLink` and `ItemLink` templates for the 26
    breedable mobs instead, filtered to Java through `markup.scope_editions`.

    Taming is kept in a separate field from breeding, never merged: the table marks a mob
    `(Tamed)` but does not say what tames it, so the items live in `/data/curated/taming.json`.
    A wolf is tamed with bones and bred with meat, and conflating those is the obvious bug.

    The cooldown and the baby growth time are `BreedingInfo.cooldownSeconds` and
    `BreedingInfo.babyGrowthSeconds` rather than strings the renderer invents. Both are stated in
    the page's prose rather than in the table -- "five minutes", and "Most baby mobs take 20
    minutes to grow up, while snifflets take 40 minutes" -- so `pipeline/enrich/breeding.py`
    owns them as constants keyed on the mob name the table's own `EntityLink` yields.
    Keying on the mob is the whole point: the first cut inferred the Sniffer from its food list,
    and a Chicken eats Torchflower Seeds too, so every chicken claimed a 40-minute baby.

19. **A health row draws at most a full player bar of ten hearts, and marks the rest with `+`.**
    Hearts are drawn from the value's minimum and capped at 20 HP; a maximum above that appends
    a single `+`. The alternative the renderer shipped with -- one lone heart for anything over
    20 HP or for any range -- made the Warden's 500 HP read as one heart of health, weaker on
    screen than a chicken's four. Drawing 250 real hearts is the other wrong answer, since the
    row has one line to fit in. The exact figure is always in the text beside the icons.

    Damage is shown whenever the infobox carries it, not only for hostile mobs as first planned.
    26 mobs carry a damage figure without a hostile behaviour, Enderman, Iron Golem, Bee and
    Cave Spider among them, and hiding what an iron golem hits for is the wrong answer to a
    question a match actually asks.

20. **A display name the wiki writes but no registry carries is resolved by a named rule, or not at all.**
    Four families of name reached no registry ID and so rendered as dead plain text: `<Pattern>
    Armor Trim` (the elder guardian's `Tide Armor Trim` drop), `Arrow of <Effect>` (the Bogged,
    Parched and Stray drops), `<item> (item)` (the `Pufferfish (item)` and `Tropical Fish (item)`
    trades), and `Music Disc <Song>`. Each is a nickname for something that does have an ID -- an
    enchantment, a potion component and a page-title disambiguator are all data on a stack or on a
    page, not separate registry entries -- so each gets one rule that names the alternative, tried
    only after the exact name has already failed.

    The three rules both `pipeline.normalize.merge` and `pipeline.obtain.loot` need live in
    `pipeline.enrich.resource_location`, which owns the join table they both read. A second copy
    in the second module would have been the cheaper edit and is exactly the drift this repository
    keeps paying for elsewhere.

    Separately, a name matching several IDs is now disambiguated rather than dropped, but only on
    evidence: an ID that never became an entity loses to one that did (which is the whole of the
    `Potato` case -- the April Fools `snektato` shares the display name and reaches no page), then
    a wiki page titled exactly the name wins, then a registry path matching the name's slug wins.
    A name that survives all three with more than one candidate is still left unlinked, because
    `Music Disc` really does name all 23 discs and guessing one would put a wrong ID on a wiki fact.

    Measured against the committed build the change is strictly additive: 13 names newly resolve,
    no name changes target, and none stops resolving.

21. **An icon the join resolves imprecisely is corrected by a curated override, never by the packer.**
    Three advancements named an icon the atlas could not serve honestly. `Local Brewery` names
    `Uncraftable Potion`, which has no frame under any sprite family, and was the one advancement
    of 126 carrying `icon: None`. `Hero of the Village` and `Voluntary Exile` name `Ominous
    Banner`, which the registry has no separate item for -- it is a white banner carrying a
    pattern -- so the join answered `minecraft:white_banner` truthfully and the window drew a
    plain white banner.

    Both are data faults rather than route faults, so both are fixed the way Decision 3 requires
    and Decision 15 already applied to the three oversized sprites: a hand-recorded, verified
    `File:` title in `/data/curated/overrides.json`. A human recording a checked filename is not
    the pipeline guessing one.

## Still open

1. **Match-specific extras.** Since this is for draftout matches — is there value in pinning
   frequently used entities, or a saved layout you can restore between rounds?
2. **Scope ceiling.** The additions in Phases 6b/6c are the ones with clear match value. Paintings,
   music discs, and sound events are all reachable but look like noise — leaving them out unless
   you disagree.

## Deliberately out of scope

Recorded so these do not creep in later: Bedrock Edition, mod content, full wiki article text,
editing or contributing back to the wiki, and multiplayer or sync features.

## Data-source corrections

Findings that contradict the data-source notes in `CLAUDE.md` and `AGENTS.md`. Recorded here rather
than fixed in place, because the two files are byte-identical mirrors and a correction needs its
replacement source decided first.

- [ ] **`compostable` and `cooking_fuel` are not in `summary/item_components`.** `CLAUDE.md` states
      that file carries `minecraft:compostable` for 122 items and `minecraft:cooking_fuel` for 347.
      Checked against the live `26.2-summary` tag on 2026-08-26: it carries neither component, and
      the `data` branch holds no equivalent list either. `minecraft:food` (44 items) does match, so
      only two of the three claims are wrong. This removes the stated Tier A source for the Phase 7
      `compostable` and `fuel` collections.
  - [ ] Find where 26.x exposes composter chance and furnace burn time
  - [ ] Correct the claim in `CLAUDE.md` and `AGENTS.md` in one commit, or move both collections to
        the curated tier when no Tier A source exists
