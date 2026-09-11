# MC-FastWiki — Build Plan

Phases are ordered by dependency. Each phase ends at something demonstrable, so progress is
visible before the whole thing works. Read `CLAUDE.md` / `AGENTS.md` first for architecture and
the verified data-source details.

**Resolved decisions** are recorded at the bottom alongside the remaining open questions, so the
reasoning survives even after the choice is made.

---
## Phase 6b - Obtain methods with no adapter

`pipeline/obtain` builds the graph from mcmeta loot tables and recipe files, plus the wiki's trade
and mob-drop tables.
That covers 14 methods and 4337 producers (12 loot-table families read, closing 27 gaps).
Every producer whose outcome is a draw rather than a certainty also carries its odds - the chance,
the stack range, and the expected yield per chest, catch, barter, shear, brush or kill.
A producer only carries them where the source states them: an entry under `minecraft:alternatives`
is picked by condition rather than by weight, and an entry with its own `conditions` has a real
probability no loot table writes down, so both forfeit the three fields rather than guess.
Decision 11 planned the opposite approach and was overtaken by what shipped; read that entry for
why the reversal happened and what it costs.

Nothing is left. `data/reports/obtain-report.json` lists 276 items with no producer of any kind,
and every one of them is correctly empty and always will be.
The count read 286 before the music disc note was expanded, and the breakdown below read 274 with
"the other 12" named as the discs. Both figures were wrong, and the groups are recounted here so the
correction survives: only 10 discs had no producer, because `music_disc_13` and `music_disc_cat`
already had chest-loot ones, and the empty groups summed to 276 rather than 274 because the
placed-block states were undercounted by two.
The groups are: 141 placed-block states (`potted_*`,
`*_wall_sign`, crop stages, plus `suspicious_sand` and `suspicious_gravel` which break to nothing),
88 spawn eggs, 22 technical and fluid blocks, 18 creative or operator blocks, and 7 `infested_*` blocks
(their loot tables drop the host stone when broken with silk touch, spawn silverfish otherwise, and no
vanilla recipe, trade, or drop produces them; they are world-generation-only for the same reason
`potted_cactus` is empty).
Nobody obtains a `potted_cactus` - the pot and the cactus are the obtainable things, and the potted
state is what the world holds after you combine them.

The 12 music discs were the last real gap, and they are closed. See the entry below.

The recipe-type cause is closed.
`pipeline/obtain/recipes.py` now reads eleven recipe types rather than six, and the 43 recipes it
still skips are the 18 `smithing_trim` files, the 21 remaining `crafting_special_*` files, and the
4 `dye_white_*` files, none of which makes an item that lacks another producer.

The pool-level tool gate bug is closed.
`pipeline/obtain/loot.py` previously checked only entry-level conditions, omitting silk-touch
requirements from 76 tables (stained glass, coral fans, ice, sculk, bee nest) and shears from 6 tables
(`vine`, `seagrass`, `tall_seagrass`, `hanging_roots`, `nether_sprouts`, `small_dripleaf`). Reading pool
conditions now notes the tool requirement while retaining odds.
The Block page states that gate too: `HarvestDrop` carries a named `gate` rather than the
`silkTouch` boolean it shipped with, so the 6 shears tables render a `requires shears` badge beside
their drop instead of an unbadged one, and gated drops still sort after the drop a player gets by
simply breaking the block.

The curated one-off cause is closed.
`data/curated/producers.json` carries 14 hand-verified producers that no recipe or loot table states,
read by `pipeline/obtain/curated.py`: the six bucket fillings the earlier bullet named, plus
`water_bucket` and `milk_bucket`, whose only producers were chest tables, plus `dragon_breath`
(bottling), `written_book` (signing a writable book, under the new `USING` method), and `elytra` and
the 3 pottery sherds (under the new `WORLD_GENERATION` method).
Every row names the wiki page it was read from.
Two claims the earlier version of this bullet made were wrong and are recorded here so the reversal
survives: the 3 sherds are not vault-only, because decorated pots carrying them generate naturally in
trial chambers at 1/13 per pot, and `filled_map` needed nothing because `minecraft:map_cloning`
already produces it.

The 12 music discs are resolved, and this phase now has no gap left in it.
The creeper drop row names `Music Disc`, which is the display name of all 23 discs.
Reading and expanding the note beside that row (`random_disc`), which lists the 12
skeleton-killed creeper drop discs by name, produces obtain producers for all 12 discs,
reducing `items_with_no_producer` from 286 to 276.
See Decision 25.

One claim the earlier version of this bullet made was wrong and is recorded here so the reversal
survives: it said the fix meant "reading the wikitext note beside that row", which implied a new
page wikitext fetch.
It needed none.
The note already arrives inside the `droptable` bucket row the build reads on every run, and
`pipeline/enrich/droptable.py` was already parsing it into a `DropNote` for its conditions.
The whole change is one branch in `pipeline/obtain/loot.py`.
The count was wrong too: 12 discs are named in the note, but only 10 lacked a producer, because
`music_disc_13` and `music_disc_cat` already carried chest-loot producers and gained a fourth
rather than their first.

Two things the earlier version of this phase asked for are dropped on purpose: fetching each item
page's rendered `Obtaining` section, and rate-limiting one request per item page.
Neither is needed now that the graph comes from data files.

## Phase 6c — Additional entity kinds

### Enchantments: done

All 43 enchantment pages carry an `EnchantInfo` section, built entirely from Tier A.
`pipeline/extract/enchantment.py` reads `data/minecraft/enchantment/` and the enchantment tags, which
cost no new fetch because the `data` archive was already downloaded and only `DATA_GROUPS` had to name
the group.
The section states max level, rarity from `weight`, anvil cost, equipment slots, the modified
enchantment level range per level, the applicable items, the exclusive set, and the treasure, curse and
tradeable flags.

The cost figures are the modified enchantment level, not the 1 to 30 number on the table slot, and the
row is labelled that way on purpose.
Naming it an XP cost would be the plausible-looking wrong answer.

`primary_items` renders as its own row only for the 5 enchantments whose table set differs from their
anvil set: Bane of Arthropods, Fire Aspect, Sharpness, Smite, and Thorns.
The other 38 render one row, because stating two identical lists would imply a distinction the data
does not make.
An `exclusive_set` tag lists the enchantment itself, so the extractor removes it; without that,
Sharpness conflicts with Sharpness.

Every applicable item is drawn as a link, with no disclosure to open first.
The plan approved a collapsing disclosure and it was built that way, then reversed after seeing it:
a link the reader can see is a jump they can take, and a click that only reveals links is a step
between the question and the answer.
The widest case is Curse of Vanishing at 92 items, which wraps inside a half-width window with no
horizontal overflow.
The group label spells the last segment of the tag rather than printing it, so a row reads
"Mining loot (28 items)" instead of `enchantable/mining_loot`.

Two things are left out on purpose.
The reverse lookup, opening Diamond Pickaxe to see what goes on it, is a separate pass: it needs its
own section type and renderer and would attach a list to roughly 150 item entities.
The `effects` block is not read at all, because rendering it means interpreting 30 effect types of a
game-internals format and the wiki blurb already states what an enchantment does.

### Enchantment icons: a kind, not an identity

`web/render/entry-icon.ts` draws the Enchanted Book frame for any enchantment that resolves no icon of
its own, which is all 43 of them.
This is the fallback the Phase 8 potion bullet below prescribes, and it holds more exactly here: the
game draws every enchanted book with one identical texture, so there is no per-enchantment art being
approximated, because there is none.
The icon therefore says "this row is an enchantment" and does not claim to tell Fortune from
Efficiency.

`ICON_RULES["enchantment"]` keeps `has_icons=False` and the registry stays an exemption in the icon
report, because the pipeline's record of what the wiki publishes is still correct.
The wiki does publish a `DungeonsEnchantmentSprite` family and it is the trap rather than the answer:
it is Minecraft Dungeons artwork, a dozen of its names collide with Java Edition's, and
`VANILLA_FAMILIES` already excludes every `Dungeons*` family.
Picking a representative tool per enchantment, a diamond pickaxe for Fortune, was rejected as the guess
Decision 3 forbids, since it chooses one arbitrary member of a 28-item set.

- [x] **Villager professions** — searching `librarian` opens a page listing that profession's
      trades grouped by level (Novice through Master). The `trade` bucket carries profession,
      level, quantities, price multiplier, max uses, and XP. **Keep `java_probability`, drop
      `bedrock_probability`**
- [x] **Structures** (34, Tier A) — where they generate, and the chests inside them. The `biomes`
      field is a tag reference (`#minecraft:has_structure/village_plains`), so resolve it through
      tag data rather than reading it as a literal (34 in 26.2, corrected from 52)
- [x] **Biomes** (66 in 26.2, Tier A) — what spawns there, what generates there, which structures appear
- [x] **Biome climate — two sources, do not assume one covers it**
  - [x] Temperature, downfall, precipitation: take from mcmeta `worldgen/biome/<id>.json`
        (**Tier A**, no scraping). The biome infobox has a `Climate` group with the same three
        values, but there is no reason to parse it when the data is already in Tier A
  - [x] Continentalness, erosion, weirdness, depth: in **neither** the infobox nor mcmeta, which
        gives only `{"preset": "minecraft:overworld"}`. Parse **`World generation` section 4**
        (Biomes → Overworld) — 8 tables plus the level definitions. Not the `Biome` page: that has
        only temperature/downfall/precipitation. Fandom put these on `Biome`, this wiki did not
  - [x] Handle the `T=`/`H=`/`PV=` shorthand and inland categories in those tables
  - [x] **Do not conflate the noise `temperature` parameter with the biome `temperature` property.**
        Jungle's infobox says `0.95`; the noise level is `T=0`..`T=4`. Different things that
        correlate — an easy and very plausible-looking bug
  - [x] Render the matching table rows per biome rather than inverting the full 6D space into one
        scalar per biome. The tables are conditional; pretending otherwise would be wrong
  - [x] Do not try to extract erosion/depth from biome page prose — mentions like "bordering
        mangrove swamps at high erosion" are not structured values
  - [x] Source from minecraft.wiki, not Fandom — Fandom lags (last edit 2026-06-18 vs 2026-08-02
        here) and was already missing 26.x content like Poplar
- [x] **Per-biome mob lists** — sourced from Tier A mcmeta biome `spawners` (64 biomes, 677 spawners,
      52 unique mobs), with wiki `spawn_table` demoted to an overlay for conditional notes.
      (The previous claim that `spawners` was empty was false; see Decision 29).
- [x] **Brewing folded into the recipe tree** — not a separate renderer. See Phase 3

### Cross-linking

- [x] Mob spawns in a biome → the biome is a link (and mob page spawn biomes link to biomes)
- [x] Structure generates in a biome → link, both directions
- [x] Structure → its chests → the items in them
- [x] Trade → the item traded; item → the professions that sell it
- [x] Enchantment → the items that accept it. Rendered on the enchantment page; the item-page reverse
      lookup is deferred, per the Phase 6c record above
- [x] Lint pass: flag any renderer printing a known entity name as plain text instead of a link.
      Built as two complementary lints:
      - **Lint A (`pipeline/validate/references.py`):** a third half of the build gate, beside
        conformance and regression, reading `MergeReport.unplaced`.
        The 26.2 build reports 16 rows and every one classifies: `variant_group` (6), `stack_data`
        (5), and `not_in_this_version` (5).
        Anything outside those groups fails the build, downgradeable with `--allow-regression`.
        Every group is a rule rather than a list of names, so a variant-group name a later snapshot
        adds classifies itself while `Potato` still fails and names itself.
        Two rules carry the weight: a name the merge resolved to a real ID this build has no entity
        for is `not_in_this_version`, and a table whose registry this build left empty is skipped
        the way regression skips a `None` baseline, which is what keeps a 3-entity smoke-test build
        from reporting all 40 wiki effect names as misses.
        The count corrects this bullet's earlier claim of 33 rows in three groups: the mob-variant
        group it named (`Cold Chicken`, `Pale Wolf`) no longer appears at all.
        `Dappled Forest` was checked against the pinned archive before being called benign; it is
        absent from mcmeta 26.2 and reaches the build only through the wiki.
      - **Lint B (`web/render/cross-link.test.ts`):** renders all 2176 entities from the 17
        committed shards and asserts that every ref the search index can resolve came out as an
        `a.entity-link`.
        No section type is skipped, and the one documented exemption is the self-referential
        `professionRef` on a seller's own trade table.
      - Lint B found two renderer bugs on its first run, both fixed here.
        `StructureInfo` gated its sibling row on `siblings.length > 1`, but
        `pipeline/extract/structure.py` excludes self from that list, so all 8 single-sibling
        structures rendered no link at all -- Bastion Remnant never linked to Nether Fortress.
        `RENDERERS.TradeTable` returned `null` for any page that was not the seller's own, so the
        170 item and block pages carrying a populated trade table showed nothing, which is also why
        the "item → the professions that sell it" bullet above was only half true.

## Phase 7 — Collections (the special search terms)

Build these data-driven from a `/pipeline/collections/manifests/*.json` manifest — a title, a blurb,
and a member-resolution rule. Adding a new collection should mean adding one manifest file, never
writing code.

The manifests are JSON, not the YAML this section originally specified. Every hand-maintained file
in `/data/curated` is already JSON, the repository has no YAML parser and its dependency list is
held to three packages with a written justification each, and this file's own convention for
explaining a curation choice is a `"note"` field rather than a comment. One data format, no new
dependency.

- [x] Collection manifest format and resolver — `pipeline/collections`, running as build stage 7a,
      between `merge_entities` and the sprite atlas. Four rules: `component`, `tag`, `kind`, and
      `list`. A tag rule names its own registry, because `arrows` and `frog_food` are each both an
      item tag and an `entity_type` tag in 26.2 and resolve differently in each, which is the same
      trap `TagIndex` refuses a default registry over. Two faults raise rather than shipping a
      broken page: a member ID with no entity, and a rule that resolves to zero members.
- [ ] `compostable` — all compostable items with their composting chance. **Not Tier A.** See
      Decision 30: `minecraft:compostable` does not exist in 26.2, and neither does a wiki Bucket.
      Needs a curated file or a parse of the Composter page table.
- [x] `unique_food` — all food items with nutrition and saturation, from the `minecraft:food`
      component (**44 items, Tier A** — the one claim of the original three that holds)
- [ ] Consider a `fuel` collection too — **not Tier A either.** `minecraft:cooking_fuel` does not
      exist in 26.2. Same options and same blocker as `compostable`; see Decision 30.
- [x] Mob type groups — `undead` (17) and `arthropods` (5), both from `entity_type` tags. The rest
      are one manifest file each whenever they are wanted: `illager` (4), `raiders` (6),
      `skeletons` (6), `zombies` (9), and `aquatic` (14) all exist as tags and need no code.
- [ ] `armor_trims` — every trim, how to obtain it, and which chests it generates in
- [ ] `banner_patterns` — all unique banner pattern recipes
- [ ] `workstations` — all workstation block recipes
- [ ] `minecarts` — all minecart recipes
- [ ] 'advancements' -- All minecraft advancements, ordered via the tree depth first, separated by what menu they are in.
      Needs a tree-shaped section; the flat member list cannot express it
- [x] Every member renders as a link that opens the real entity window — enforced by lint B
      (`web/render/cross-link.test.ts`), which picked up the new shard with no exemption added

New collections the added data makes nearly free:

- [ ] `fuel` — its own search keyword, with burn times. Blocked on the same missing source as the
      bullet above; it is not free after all
- [x] `enchantments` — the full list (43), with each one's maximum level. Flat rather than grouped
      by what they apply to: an enchantment applies to a set of items, so the grouping is
      many-to-many and wants its own section type rather than a member list
- [x] `structures` — every structure (35). That is the 34 worldgen structures plus Monster Room,
      which has a page of its own per Decision 27, because the collection lists structure *pages*
      rather than `worldgen/structure` registry entries. Each member links to its own page, which
      already carries the biomes
- [ ] `chest_loot` — every lootable chest, as a hub into the structures that contain them
- [ ] `villager_trades` — professions as an index into the trade tables
- [ ] `bartering` — the full bartering table for piglin bartering

## Phase 8 — Minecraft theming

- [ ] Pixel typeface — use an open font that reads as Minecraft rather than shipping Mojang's own
- [ ] GUI panel styling: beveled 3D borders, stone/dirt surfaces, inventory-slot framing
- [ ] Sprite atlas rendering with `image-rendering: pixelated`; no smoothing, ever
- [ ] Icons beside every entity name, in suggestion rows, and inside recipe grids
- [ ] **All 46 potion entities carry no icon.** The wiki publishes four potion sprites in total
      (`InvSprite:Potion`, `ItemSprite:potion`, `ItemSprite:splash-potion`, `ItemSprite:lingering-potion`),
      because the game tints one texture rather than shipping a sprite per variant, so there is no
      `Potion of Swiftness` file to resolve and Decision 3 forbids constructing one.
      Every potion page and every potion row of an Effect page therefore renders iconless.
      This predates the Effect work but became visible there: those rows used to borrow the generic
      `minecraft:potion` icon because they wrongly linked to it, and now that they link to the right
      variant they show none.
      The fix is a renderer fallback from `minecraft:potion/<path>` to the generic potion sprite,
      not a new sprite, because the texture really is the same one.
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
    `minecraft:food` component. Dropping it would push five of the planned pages back onto
    hand-curation to save one HTTP fetch.

    This entry used to say "the food/compostable/fuel components". Only food is true, and the
    correction is recorded here rather than quietly deleted: see Decision 30. It does not weaken
    the decision, because every other item on the list still holds and the mob-group entity tags
    named above are what `undead` and `arthropods` are actually built from.

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

    **Reversed by what shipped.** The obtain graph reads mcmeta loot tables and recipe files
    directly, and borrows the wiki only for trades and mob drops.
    That is the inverted-loot-table approach this entry rejected.
    Nothing above turned out to be wrong. The reasoning was simply overtaken.
    Building the tree needed a producer graph -- what makes this item, and what makes each of its
    inputs, all the way down -- and the wiki's `Obtaining` section is a flat list per page, not a
    graph.
    A scrape would have had to be re-joined into the same producer shape the data files already
    state exactly, so it would have added a network dependency, a per-page rate limit, and a parse
    of rendered HTML, to arrive at data the pipeline could read offline.

    Three things the scrape would have carried are now genuinely missing, and only the first is
    worth acting on.
    Chest loot rows drop their `chance` figure, so the tree says an item is in a chest but not how
    often.
    Fishing has no adapter at all.
    Anything the wiki lists under `Obtaining` that no data file states -- archaeology, world
    generation, and the one-off interactions -- has to be recovered another way, which is what
    Phase 6b now tracks.

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

22. **A block generates in one dimension *per scope*, and a placement that states no band gets none.**
    `GenerationInfo` carries one `GenerationScope` per dimension rather than one dimension per
    block, and three blocks need it: `gravel` (`ore_gravel` plus `ore_gravel_nether`), and
    `brown_mushroom` and `red_mushroom`, whose `*_normal` placed feature is itself listed by
    `crimson_forest`, `nether_wastes` and `warped_forest` alongside its 44 overworld biomes.

    The first cut carried one dimension per block, preferred the overworld when a block's features
    disagreed, and special-cased the two mushroom features by id so the disagreement would not
    raise. That dropped every nether vein and its biomes with it, so a Gravel page said "Overworld"
    and a Brown Mushroom page counted 44 biomes instead of 47. The plan this work was approved from
    asked for the opposite of both -- raise rather than pick -- and raising is not available either,
    because the disagreement is what the files actually say. A scope per dimension is the only
    reading that keeps the three rows that depend on it truthful, since a band, an attempt count and
    a biome list are all facts about one world: the same `above_bottom 0` anchor is Y -64 in the
    overworld and Y 0 in the nether.

    Two rules of the same kind sit beside it, both fixing a fabricated number rather than a missing
    one.

    A `heightmap` placement states a surface, not a band, so those veins carry `surface` and no Y
    numbers. Filling in the dimension's build range instead made 19 blocks -- sweet berry bush, dead
    bush, short grass, lily pad and the rest of the surface plants -- claim "Y -64 to 320", which is
    the whole world.

    A `count` modifier ahead of the position modifier is an attempt per chunk; a `count` behind it
    scatters blocks around a position already chosen, which is patch density. 38 of the 86 placed
    features state their count that way, and reading the first cut's `pre_height` scan past them
    fell through to a `tries: 1` default, so Dead Bush summed a rate out of numbers no file states.
    Such a vein now carries no attempt count at all, which is the same answer `pipeline.obtain.loot`
    gives when a loot table stalls short of a real probability.

    The dimension biome counts come from resolving `is_overworld`, `is_nether` and `is_end` rather
    than from the literals 55, 5 and 5, so a version that adds a biome cannot quietly turn "every
    biome" into "all but one".

23. **Wandering Trader is a mob, not a profession entity, and is still a seller.**
    The wiki `trade` bucket includes 97 trades for `Wandering Trader` alongside the 13 villager
    professions. Wandering Trader is not in `villager_profession` (which only contains the 13
    professions and `none`/`nitwit`). Because Wandering Trader is already an entity in `entity_type`,
    its 97 trades attach directly to `minecraft:wandering_trader` under `TradeTable`. No duplicate
    or synthetic 14th profession entity is created.

    Being a mob does not stop it being a seller, and the first cut of this conflated the two.
    `professionRef` names the seller a trade group belongs to, and leaving the trader out of that
    map made it the one heading of fourteen that stayed dead text on every item page while every
    sibling became a link, which is the exact fault the Phase 6c lint bullet exists to catch.
    Its name now resolves to the mob, so all 366 trade rows on item and block pages carry a ref and
    none prints a seller as plain text.

    Two consequences on the trader's own page, both found by reading the rendered page rather than
    by any test:

    A trade table on the seller's own page groups by level alone, the same as a profession page.
    Grouping it by seller printed a "Wandering Trader" heading under the window titled Wandering
    Trader, and once the heading carried a ref it linked the reader to the page they were reading.

    `renderRecipeTree` must not embed a seller's own trade table under Obtaining.
    It embeds an item's `TradeTable` because there the section lists the trades that *give* that
    item, which is a way to get it. On a seller's page the same section lists what that seller
    *offers*, so embedding it answered "how do I obtain a wandering trader" with the trader's own
    shop and printed all 97 rows a second time directly below the Trades section that had just
    shown them. Suppressing it removes the page's spurious Obtaining section entirely.

24. **Nitwit and none are excluded from profession entities.**
    `minecraft:villager_profession` exposes 15 paths in 26.2: 13 professions that trade, plus `none`
    and `nitwit`. Neither `none` nor `nitwit` has trades in the wiki's trade bucket. They are
    excluded from the 13 profession entities so that profession entries in search and navigation
    strictly represent trading professions.

    The rule is "a profession the trade index knows", not a hand-written exclusion list, so a
    release that gives the nitwit trades gives it a page without anyone editing a list.

    `none` would fail on its own merits regardless: it has no sprite, and "Unemployed" redirects to
    `Villager` rather than being a page, so it carries no `{{Infobox profession}}` and no blurb. An
    entity ID of `minecraft:none` would name the absence of a thing.

    `nitwit` is excluded by scope choice and not by the data, and that is worth recording because
    the data would have supported it: it has its own page, its own `{{Infobox profession}}` reading
    `workstation = None`, and its own sprite row. It is the one profession page this build could
    produce and chooses not to. The parser still treats `workstation = None` as absence rather than
    as a block named "None", but with the nitwit excluded that guard now protects a case no page in
    the build reaches, and its test says so.

25. **Music Disc mob drops expand to the 12 enumerated discs.**
    Creeper's drop table names `Music Disc`, which previously refused to resolve because `Music Disc`
    is the shared display name of 23 discs. Reading and expanding the wikitext note attached to that
    drop (`random_disc`) resolves the exact 12 discs dropped by a skeleton-killed creeper: 13, cat,
    blocks, chirp, far, mall, mellohi, stal, strad, ward, 11, and wait. Expanding this drop when all
    12 resolve provides obtain producers for these 12 discs, reducing `items_with_no_producer` from
    286 to 276.

    **All or nothing, on purpose.** A note expands only when every link in it resolves to an item.
    A note where some links resolve expands to nothing and the row is reported exactly as before,
    because a partial expansion would put a creeper drop on some discs and not others with nothing
    in the data to justify the split. A note where no link resolves is skipped rather than failing
    the row, which is what lets the creeper's second note, `killed_by_skeleton`, be passed over: it
    links mobs, not items, and the disc note is read instead.

    The rule is deliberately general rather than a creeper special case, and it currently fires on
    exactly one row because `Music Disc` is the only drop name left that resolves to nothing. The
    one other unresolved droptable name, `Wool`, names the 16 coloured wools and its note does not
    enumerate them, so it stays unresolved and is untouched by this.

26. **Structures are 34 entities from `worldgen/structure` (Java 26.2).**
    The Phase 6c bullet estimated 52 structures. Java Edition 26.2 defines exactly 34 structures across
    overworld, nether, and end in `worldgen/structure`. Each structure entity is populated with Tier A
    placement rules from `worldgen/structure_set` (random_spread spacing/separation/frequency/exclusion
    zones or concentric rings), sibling structures with weights, generation step, single dimension, mob
    spawn overrides, suppressed spawn categories, and biomes resolved from `#minecraft:has_structure/*`
    tags.
    Chest loot tables from curated `chest-sources.json` and `loot-sources.json` attach to structures via
    `structureRef` and render as `ChestLoot` tables sorted by chance descending. Biomes receive a
    `LinkList` section listing all structures generating within them.

    A `structureRef` is a list, not a single id, and that is the whole reason the join is curated
    rather than matched on the display name. One village chest generates in all five villages and one
    ruined portal chest in all seven portals, so a chest names every structure it belongs to. The item
    page reads the same list backwards: where it resolves to one structure the label's structure half
    becomes the link, and where it resolves to several the label stays text and the variants follow it
    as their own links, because picking one of five would be a guess and `Village` is not an entity to
    link the word to. The two curated files also disagreed on names before this
    (`Trial Chamber` against `Trial Chambers`, `Ocean Ruins (Cold)` against `Ocean Ruins`), which is
    why nothing matched on the string. `Dungeon`, `Desert Well`, `End Ship` and `Spawn` are correctly
    ref-less: none is a `worldgen/structure` member.

    Structures resolve no icon of their own and `ICON_RULES` still records that with
    `has_icons=False`, because the wiki publishes no structure sprite family at all -- measured across
    all 20,013 rows of the 26.2 `spritefile` bucket, the only hits on structure names are village
    *maps* and villager entity sprites. That record is about what the wiki publishes and it stays
    true. What each structure does carry is a Tier C borrowing in `overrides.json`: one characteristic
    block or item whose sprite is already in the atlas, so all 34 are recognisable in a mixed
    suggestion list without a single new sprite being fetched. Nether Bricks for the Nether Fortress,
    End Portal Frame for the Stronghold, Trial Spawner for the Trial Chambers. It states a kind and a
    place, not an identity, in the same spirit as the Enchanted Book frame every enchantment draws,
    and it does not claim to be Mojang's or the wiki's picture of the structure. An earlier cut of
    this entry said structures carry no icon "matching biomes", and both halves were wrong: biomes
    resolve real `BiomeSprite` art, and structures now draw a borrowed sprite rather than nothing.

    Five curated aliases land with this. `fort` now reaches the Nether Fortress, which
    `aliases.json` had refused once and recorded why: in a draftout match `fort` means the fortress
    far more often than Fortune, and the refusal said so while noting that structures did not exist
    yet. The three structure nicknames divide into two cases. `jungle temple` is a name the game
    itself uses, because the structure is `jungle_pyramid` while its loot table, its biome tag and
    its structure set are all `jungle_temple` -- the game disagrees with itself, so both names are
    real. `desert temple` and `witch hut` are not that: the game says `desert_pyramid` and
    `swamp_hut` in every file, and these two are community shorthand, which is what this file exists
    for. The `structure/village/desert/houses/desert_temple_*.nbt` files are not evidence for
    `desert temple`; they are village houses and have nothing to do with the desert pyramid.

    **A dungeon is a feature, not a structure, and that is why it has no page.** The question comes
    up because `chest-sources.json` attributes `chests/simple_dungeon.json` to a structure named
    `Dungeon` and that row is one of only two that get no `structureRef`. The dungeon is entirely
    real in the game and it is simply registered elsewhere: `worldgen/configured_feature/
    monster_room.json` holds it, and two placed features run it -- `monster_room` at 10 attempts per
    chunk from Y 0 to the world top, and `monster_room_deep` at 4 attempts per chunk from Y -58 to
    -1. It is absent from `worldgen/structure`, so this task does not enumerate it, and the chest
    label correctly renders `Dungeon - Chest` as plain text rather than as a dead link. Its
    configured feature carries `config: {}`, because the room's blocks are built in the game's Java
    code rather than described in data, so `extract_generation` could not describe its contents even
    if it read the type. `dungeon` therefore aliases to the Monster Spawner, which is the block a
    player typing it is actually looking for. Giving dungeons a page of their own means enumerating
    features as an entity kind, which is a separate piece of work and is not proposed here.

27. **The dungeon has a page, built from the feature the game files it under.**
    Decision 26 recorded why it had none and called a page separate work. It was asked for, and it
    turned out not to need a new entity kind after all. `pipeline/extract/feature_place.py` reads a
    curated list of configured-feature ids from `data/curated/feature-places.json` and derives
    everything a page states from the pack: the dimension from the biomes that run the passes, and
    the band and the attempts from the placed features. Only the display name and the wiki page are
    curated, because the `resource_location` bucket has no row for a configured feature and cannot
    answer them. Today the file holds one entry. `desert_well` is the obvious second and is left out
    only because nobody asked; adding it is a data change and no code change.

    The dungeon renders `GenerationInfo`, not `StructureInfo`, and that is the honest shape rather
    than a convenience. A feature has no structure set, no separation and no generation step, so
    `StructureInfo` would be mostly empty and its placement field could not be filled at all. What a
    feature does have -- a dimension, a height band, attempts per chunk, a biome list -- is exactly
    what `GenerationInfo` already states for an ore vein, so the two share `band_of_placement` and
    `rate_of_placement` literally rather than restating the anchor arithmetic. The kind stays
    `structure`, because that is the badge and the renderer a player looking for a place expects,
    not a claim about which registry the id came from.

    Measured: Overworld, Y -58 to 320, 14 attempts per chunk, all 55 overworld biomes. The 14 is
    both passes summed and the band spans both; either pass alone halves the rate and cuts the band
    at zero. `chests/simple_dungeon.json` now points at `minecraft:monster_room`, so the chest label
    on an item page links, and `dungeon` aliases to the place rather than to the Monster Spawner,
    which was the stand-in used while it had no page. The spawner keeps its own name and aliases.

28. **A music disc is named after its track, because the wiki's page title says so.**
    The wiki's `display_name` is the in-game stack name, and for one family that name is
    deliberately not unique: all 22 discs are called `Music Disc`, which is what the game prints on
    the stack, with the track only in the tooltip. Repeating it gave 22 identically named entities,
    and it became unreadable the moment a dungeon chest listed three discs at three different odds
    with no way to tell which one was the 1.4%.

    `names_the_wiki_reuses` takes the page title instead, wherever several registry ids share a
    display name *and* keep their own pages. Both halves matter. Measured against 26.2 the set holds
    exactly one name, and the four other collisions in the build are correctly untouched: `Wind
    Charge` and `Eye of Ender` are each two ids for one page, so there is no better name to take,
    and `Hero of the Village` and `The End` collide across two different kinds, where the kind badge
    already separates them and renaming either would be wrong.

    The wiki's own casing is kept rather than normalized, so the data reads `Music Disc Pigstep`
    beside `Music Disc cat`. That is not an inconsistency to fix: those track titles really are
    lowercase.

    One thing this deliberately does not change: the creeper's drop row still reads `Music Disc` as
    plain text with a note naming the 12 discs a skeleton-killed creeper can drop. That row is a
    random pick of 12 rather than one disc, so refusing to resolve it to a single item stays the
    right answer, exactly as Decision 25 recorded. The 12 names inside that note are still plain
    text and remain a candidate for the Phase 6 lint bullet.

29. **Tier A biome `spawners` is authoritative; wiki `spawn_table` is demoted to a notes overlay.**
    Earlier docs and tests claimed mcmeta biome `spawners` was empty and forced mob spawn lists to
    come from the wiki's `spawn_table` bucket. Checked against 26.2 data on 2026-09-09: 64 of the 66
    biomes have populated `spawners` in `data/minecraft/worldgen/biome/*.json` (totaling 677 entries
    across 52 unique mob entity types). Only `deep_dark` and `the_void` are empty.

    Mob spawns are therefore extracted directly from Tier A, providing exact weights, category
    totals, and group size ranges. Inverting this index produces mob-side `SpawnInfo` (52 mobs),
    with `SpawnEntry.biomeRef` unconditionally resolved to the biome entity. The wiki's Tier B
    `spawn_table` bucket is retained solely as an overlay for conditional notes (`note`, `noteName`),
    such as slime chunk requirements. Mob texture variants in the wiki (e.g. Cold Chicken, Pale Wolf)
    which share an underlying `entity_type` are deferred until mob variants have first-class pages.

30. **`compostable` and `cooking_fuel` are not data in 26.2, so both collections move to the
    curated tier.** Phase 7 was written expecting three item components to carry three collections
    for free: `minecraft:food`, `minecraft:compostable`, and `minecraft:cooking_fuel`. Only the
    first exists. Composting chance and furnace burn time are hardcoded in the game in this
    version, exposed through no component, no registry, and no wiki Bucket.

    Three independent checks agree, and each is cheap to repeat:

    - Every component key in `item_components/data.json` at mcmeta `711a353`, counted.
      `minecraft:food` appears on 44 items and `minecraft:consumable` on 43. Neither
      `minecraft:compostable` nor `minecraft:cooking_fuel` appears at all.
    - All 9,030 files of the `26.2-data` tarball scanned for the strings `compostable`,
      `cooking_fuel`, and `burn_time`. Zero files matched. The only near hits by filename are the
      composter block's own loot table and recipe.
    - Live Bucket queries for `composting`, `compost`, `fuel`, and `smelting`. Each answered
      `"Bucket <name> does not exist."` This is the half the earlier data-source correction did not
      have, and it is what rules out the Tier B route as well as the Tier A one.

    The `122 items` and `347 items` figures the phase quoted are not wrong about Minecraft; they
    are counts of a thing this pipeline cannot read. Both collections therefore need either a
    curated file under `/data/curated` or a parse of the wiki's Composter and Smelting page tables,
    each with its own verification burden, and both are deferred rather than half-built.

    What it costs: two of the eight collections the phase opened with are not free, and the "no
    curation needed" claim beside `compostable` was the load-bearing part of it. What it does not
    cost: `unique_food` is exactly as free as promised, at exactly the 44 items named, and the
    manifest and resolver this phase actually needed were never blocked on any of it.


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

- [x] **`compostable` and `cooking_fuel` are not in `summary/item_components`.** `CLAUDE.md` stated
      that file carries `minecraft:compostable` for 122 items and `minecraft:cooking_fuel` for 347.
      Checked against the live `26.2-summary` tag on 2026-08-26: it carries neither component, and
      the `data` branch holds no equivalent list either. `minecraft:food` (44 items) does match, so
      only two of the three claims are wrong. This removes the stated Tier A source for the Phase 7
      `compostable` and `fuel` collections. Re-confirmed against the pinned archive on 2026-09-10
      and resolved in full; see Decision 30.
  - [x] Find where 26.x exposes composter chance and furnace burn time. **It does not.** Beyond the
        two checks above, the wiki Bucket API answers `"Bucket <name> does not exist."` for
        `composting`, `compost`, `fuel`, and `smelting`, so there is no Tier B route either. The
        remaining options are a curated file or a parse of the Composter and Smelting page tables.
  - [x] Correct the claim in `CLAUDE.md` and `AGENTS.md` in one commit, or move both collections to
        the curated tier when no Tier A source exists. **Both mirrors needed no edit:** each is 53
        lines today and carries no `item_components` claim at all, so a later rewrite had already
        removed it. Do not go looking for that text. Both collections are moved to the curated tier
        and Phase 7 now says so.
