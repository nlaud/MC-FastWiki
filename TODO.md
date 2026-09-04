# MC-FastWiki — Build Plan

Phases are ordered by dependency. Each phase ends at something demonstrable, so progress is
visible before the whole thing works. Read `CLAUDE.md` / `AGENTS.md` first for architecture and
the verified data-source details.

**Resolved decisions** are recorded at the bottom alongside the remaining open questions, so the
reasoning survives even after the choice is made.

---

## Phase 3 — Normalization and emit

- [ ] **Natural generation as worldgen placement** is the one branch of the obtain tree with no
      wired source. Mining a block for an item ships as a `block_drop` producer, but *where* a
      block generates (Y levels, biomes) is `GenerationInfo`'s section, not an obtain step, and
      worldgen is not among the four mcmeta data groups the pipeline reads. Phase 6c owns it.
- [ ] Decide what to do about the three oversized sprites the wiki serves as full images rather
      than as cropped icons.
      Measured on the 26.2 build: `InvSprite:Sculk` and `InvSprite:Sculk Shrieker` are 300x300 and
      `InvSprite:Zombie Horse Spawn Egg` is 160x160, against 16x16 for 928 frames and 32x32 for
      924 more.
      Decision 15 records why a packer-level maximum frame size is rejected.
      What remains open moves to Phase 6: curated per-sprite overrides naming verified `File:`
      titles for these three, once a rendered icon exists to confirm a replacement actually reads
      correctly at icon size.
      Seven more frames are 1x1: `Cave Air`, `Void Air`, and the five marker and display entities.
      Those are correct and need nothing, because the thing they draw really is invisible.

## Phase 6 — Content renderers

- [ ] **Mob** — breeding items when breedable. The rest of this item shipped: HP, damage and armour
      badges, the passive / hostile / neutral signal, the spawn biomes, and the loot table across
      looting 0 to III.
  - [ ] **Breeding, end to end.** Nothing writes a `BreedingInfo` section today, so this is a
        pipeline task before it is a renderer task, and it needs a source decided first.
        mcmeta does not carry breeding items: they live in the mob's Java code, not in a data
        pack, so this is Tier B and there is no Tier A fallback to check it against.
        The wiki states them in two places that do not agree in shape — the `Breeding` section
        of each mob page as prose, and the `Breeding` row of the mob infobox as a short item
        list. Prefer the infobox row: `pipeline/enrich/infobox.py` already parses that template
        for 91 mobs, so the parser exists and only the field is missing.
        What the section has to carry: the items that start love mode, the cooldown, the growth
        time for a baby, and the taming items where they differ from the breeding ones, because
        a wolf is tamed with bones and bred with meat and conflating those is the obvious bug.
        Every item is an `EntityRef`, never a name, per Decision 13.
      One deviation, made deliberately: this item asked for damage "only when hostile", and the
      renderer shows damage whenever the infobox carries it. 26 mobs carry a damage figure without
      a hostile behaviour, and they include Enderman, Iron Golem, Bee and Cave Spider. Hiding what
      an iron golem hits for is the wrong answer to a question a match actually asks.
- [ ] **Item** — obtain tree, crafting and smelting, with the correct tool shown for blocks
  - [ ] Walk `data/dist/obtain.json` into the tree at render time, rather than reading a
        pre-built one out of the entity shard. The pipeline ships the flat producer graph
        (0.60 MB raw, 48 kB gzipped, 4,002 producers) because materialising a per-entity tree
        cost 73.8 MB raw / 4.1 MB gzipped and still truncated the deepest chains at a depth cap
        of 4, where the longest real chain is 15 levels. `pipeline/obtain/tree.py` is the
        reference implementation this renderer has to match, the same relationship
        `rank_candidates` has to the Phase 4 matcher, and it owns all four rules: drop cycles
        rather than draw them, memoize, cap depth into an expandable node, and collapse a
        repeated subtree to a back-reference. `tests/test_emit_obtain.py` proves the graph is
        sufficient to rebuild the identical tree.
- [ ] **Block** — harvest tool and tier, drops, natural generation.
      No block section exists in `data/dist` at all. `pipeline/extract/harvest.py` computes
      harvest requirements, but `pipeline/normalize/merge.py` never turns them into a section,
      so the block renderer is blocked on a pipeline emit.
- [ ] **Effect** — every source of the effect, and what it actually does.
      Zero `EffectSources` sections exist in the build, so the effect renderer is blocked on a pipeline emit.
- [ ] **Advancement** — the parent link, the in-game description and the XP reward ship. What is
      left is the requirements text, which waits on the sub-item below.
  - [ ] Strip the wikitext and HTML markup out of `AdvancementInfo.description` in
        `pipeline/enrich/advancement.py`, so a renderer can show the requirements text.
        103 of 126 descriptions carry markup on the 26.2 build.
- [ ] Render crafting recipes **collapsed** — "Wooden Stairs — any plank type" rather than
      thirteen near-identical rows (see Decision 9)
- [ ] Curated per-sprite overrides for the three oversized icons (`InvSprite:Sculk`,
      `InvSprite:Sculk Shrieker`, `InvSprite:Zombie Horse Spawn Egg`), naming a verified `File:`
      title in `/data/curated` per Decision 3.
      This is now unblocked: the renderer ships, so an icon can be looked at beside a real 16x16
      item sprite, which is what confirming a replacement needed.
      See Decision 15 for why the fix is a curated override and not a packer-level resize.

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
      Two real cases already exist in the 26.2 build, found by rendering it: the `Potato` drop on
      Zombie and the `Music Disc` trade carry no `itemRef`, yet both names resolve in `index.json`.
      The renderer prints them as plain text, which is correct behaviour for a missing ref, so the
      fix belongs in the name-to-ID resolution of `pipeline/normalize/merge.py`, not in `/web`.
      Ten further names carry no ref and have no index entry either — `Boat`, `Wool`,
      `Pufferfish (item)`, `Arrow of Poison` and similar. Those are wiki display names that name a
      group rather than one registry entry, so the lint has to tell the two cases apart rather than
      flagging every ref-less name.

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

    What remains open is a curated per-sprite override naming a verified `File:` title for
    `InvSprite:Sculk`, `InvSprite:Sculk Shrieker`, and `InvSprite:Zombie Horse Spawn Egg`, tracked
    under Phase 6 because it needs eyes on a rendered icon to confirm a replacement actually reads
    correctly at icon size.
    A curated override is compatible with this decision, because a human recording a checked
    filename is not the pipeline guessing one.
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
