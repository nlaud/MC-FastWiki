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
That covers 14 methods and 4340 producers (12 loot-table families read, closing 27 gaps).
The figure read 4337 until the first weekly wiki refresh, and the three it gained are worth naming
because of where they came from rather than what they are.
Run 34990992207 picked up three Wandering Trader trades the wiki had added for 26.x content: Poplar
Log at 8 for an emerald, Poplar Sapling at 1 for five emeralds, and Shelf Mushroom at 3 for an
emerald.
No code changed. The trades live in the wiki's own tables, the build reads those tables on every
run, and this is the first time a count in this file moved on its own - which is the whole point of
the weekly job. Expect it to keep moving, and treat a changed count here as data rather than as a
regression.
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
- [x] `compostable` — all 116 compostable items with their composting chance (30%, 50%, 65%, 85%,
      100%). Hand-maintained tier map in `data/curated/compostable.json` expanding item tags via
      `TagIndex` with explicit ID precedence, loaded at build time to attach `CompostInfo` sections to
      item entities, and resolved into a collection via a new `section` membership rule. See Decision 32.
- [x] `unique_food` — all food items with nutrition and saturation, from the `minecraft:food`
      component (**44 items, Tier A** — the one claim of the original three that holds)
- [x] `fuel` — all 280 furnace fuel items with burn duration in seconds/ticks and smelted items count.
      Curated tier map in `data/curated/fuel.json` with tag expansion and `excludeTags` filtering
      (stripping `minecraft:non_flammable_wood`), attaching `FuelInfo` sections to item entities and
      resolved into a collection via the `section` rule. See Decision 32.
- [x] Mob type groups — `undead` (17) and `arthropods` (5), both from `entity_type` tags. The rest
      are one manifest file each whenever they are wanted: `illager` (4), `raiders` (6),
      `skeletons` (6), `zombies` (9), and `aquatic` (14) all exist as tags and need no code.
- [x] `armor_trims` — all 18 trim templates, with a "Found in" column reading the same obtain graph
      the member pages render. 13 trims come from chest loot across structures, 4 from brushing
      suspicious gravel in Trail Ruins, and Tide from the Elder Guardian drop. Stated as an explicit
      18-ID list rule because no tag or component separates trim templates from the Netherite Upgrade,
      guarded against upstream drift by `tests/test_collections_drift.py`. Borrowed icon from the
      Smithing Table.
- [x] `banner_patterns` — all 10 physical pattern items, selected via a component rule on
      `minecraft:provides_banner_patterns`. A pattern item is used at a loom and is not consumed
      when crafting. Selected via component rule so it re-derives itself on every build; the other 33
      registry entries require no item and are crafted directly from dyes. Borrowed icon from the Loom.
- [x] `workstations` — all 13 villager job site blocks, titled "Villager Workstations" so utility
      blocks like crafting tables are not expected. Sourced from the workstation ref each profession
      entity carries in `profession-0.json` (13 job sites across 14 professions, the nitwit having
      none). Guarded by `tests/test_collections_drift.py`. Borrowed icon from the Villager.
- [x] `minecarts` — all 7 minecart variants (the standard minecart, 4 craftable variants with installed
      blocks, plus the creative-only spawner and command block minecarts, stated clearly in the blurb).
      Guarded by `tests/test_collections_drift.py`. Borrowed icon from the Minecart.
- [x] `advancements` — all 126 advancements, ordered depth-first across the 5 in-game root tabs
      (Minecraft: 16, Nether: 23, The End: 9, Adventure: 47, Husbandry: 31). Sourced from `AdvancementInfo`
      sections on each advancement entity. Emitted as a tree layout with grouped `CollectionTree` sections,
      rendered with depth-based indentation (`--depth`) and guide lines. Guarded by
      `tests/test_collections_drift.py`. Borrowed icon from `minecraft:story/root`.
- [x] Every member renders as a link that opens the real entity window — enforced by lint B
      (`web/render/cross-link.test.ts`), which picked up the new shard with no exemption added

New collections the added data makes nearly free:

- [x] `fuel` — its own search keyword, with burn times. Shipped in commit `d6f8d18` via the curated tier
      file `data/curated/fuel.json`, overtaking the earlier note that called it blocked on a missing
      upstream source.
- [x] `enchantments` — the full list (43), with each one's maximum level. Flat rather than grouped
      by what they apply to: an enchantment applies to a set of items, so the grouping is
      many-to-many and wants its own section type rather than a member list
- [x] `structures` — every structure (35). That is the 34 worldgen structures plus Monster Room,
      which has a page of its own per Decision 27, because the collection lists structure *pages*
      rather than `worldgen/structure` registry entries. Each member links to its own page, which
      already carries the biomes
- [x] `chest_loot` — every lootable chest (31 structures), as a structure-level hub into the structures
      that contain them, with container counts and distinct item counts via derived counting facts.
      Resolved via `section` rule on `ChestLoot`. Borrowed icon from `minecraft:chest`. Guarded by
      `tests/test_collections_drift.py`. Note: `spawn_bonus_chest` has no structureRef and belongs to no
      structure page, so it has no row here per Decision 27.
- [x] `villager_trades` — all 13 villager professions as an index into trade tables, with workstation name
      (nested `EntityRef.name`) and trade count. Resolved via `kind` rule on `profession`. Borrowed icon
      from `minecraft:emerald`. Guarded by `tests/test_collections_drift.py`.
- [x] `bartering` — the full piglin bartering table (18 items from 19 producers off
      `loot_table/gameplay/piglin_bartering.json`), with chance, stack range, and per-barter rate.
      Resolved via new `obtain` rule with `method: "bartering"`. Borrowed icon from
      `minecraft:gold_ingot`. Guarded by `tests/test_collections_drift.py`. Note: `minecraft:potion`
      carries two bartering producers (2.132% and 1.706%) that merge into one row at 3.838% with quantity 1
      because potion variants are not distinguished in the obtain graph.
- [x] **A fact cell cannot be a link, and Lint B cannot see that it should be.** `CollectionMember.values`
      is `dict[str, str]`, so a fact that reads an `EntityRef` has to flatten it to a name before the
      payload is written. The Villager Trades workstation column prints `Blast Furnace` as dead text
      while the Armorer page prints the same name as a link, and Lint B misses it because the ref is
      already gone by the time the renderer runs. Fixing it means letting a member row carry refs
      alongside its strings, which changes the pipeline-to-web schema contract and every collection
      renderer, so it is its own task rather than a rider on the one that surfaced it.
      Shipped: `CollectionMember.refs` carries `EntityRef` tuples keyed by column name (omitted when empty
      to preserve byte-identical payloads across unaffected collections), with `FactValue` producing both
      display text and refs in a single extraction step. Guarded by a two-way `SectionFact.ref` rule.
      `villager_trades` workstations (13) and `armor_trims` found-in locations (17 across structures,
      expanding multi-variant families like Shipwreck while Tide drops cleanly to plain text) now render
      as real entity links. Lint B caught the missing links when tested and now enforces them across all
      collection member rows.
      Two things the first cut of this got wrong, recorded so the reversals survive. A fact cell drew its
      links with `entityLink` rather than `proseEntityLink`, and the standalone link's horizontal padding
      reads as a word space before punctuation, so the Coast row rendered `Shipwreck , Beached Shipwreck`.
      Every link in a fact cell now uses the prose form, single-ref rows included, so one column keeps one
      left edge. `web/render/link.ts` had already named this rule and two other renderers were ignoring it
      the same way: the `GenerationInfo` biome list (`Crimson Forest , Nether Wastes`, the very example
      that docstring cites) and the `BiomeInfo` noise sibling (`(sibling: Eroded Badlands )`). Both are
      fixed here.
      `obtain.foundIn` also built a ref named by the family label when it had no entity map to resolve
      against, which would print `Shipwreck, Shipwreck` for a two-variant family and claim a display name
      no entity carries. A caller with no entity map now gets no refs and falls through to the family
      text, because `ChestSource.structure` names a family and only the entity knows the variant's name.

## Phase 8 — Minecraft theming

- [x] Pixel typeface - Monocraft v4.2.1 (SIL OFL 1.1), vendored rather than linked because Phase 10
      needs the app to work offline and a Google Fonts stylesheet is a runtime call on the hot path.
      Subset to Latin with `pyftsubset --flavor=woff2`, which lands at 3.0 KB, under Vite's 4 KB
      inline limit, so the build emits it as a data URI and the shipped site makes no font request
      at all.
      `web/theme/fonts/README.md` records the source, the release tag and the exact subset
      command, next to the file it describes rather than in `/scripts`, which holds build scripts.
      It is applied to chrome only - titles, badges, headings, table headers, `kbd`, the search bar,
      numeric stat values - while blurbs and table body text keep the system sans stack, because the
      product promise is an answer in under two seconds and monospace body prose costs reading speed.
      Crispness is not automatic: a pixel face antialiases at a fractional size whatever the
      smoothing property says, so every pixel-font rule carries `-webkit-font-smoothing: none` plus
      `font-smooth: never` and a fixed px size rather than a `rem` expression.
- [x] GUI panel styling - beveled 3D borders and inventory-slot framing.
      A 3px border, light on top and left, dark on bottom and right, inside a 1px black outline,
      with `border-radius: 0` everywhere; an inset surface flips the two, and a slot is an inset
      with 2px borders and the game's own `#8b8b8b` / `#373737` / `#ffffff`.
      Recipe slot icons doubled to 32px through `createIconElement`'s `allowUpscale` path, which
      scales by whole numbers only, so the slots read as slots rather than as empty boxes.
      **Stone and dirt surfaces were deliberately dropped, not forgotten.** They would sit behind
      body text and cost reading speed, which is the one thing this tool cannot spend.
      Chrome gets the Minecraft treatment; reading surfaces stay flat `#1c1c1c`.
- [x] Sprite atlas rendering with `image-rendering: pixelated`; no smoothing, ever.
      Audited after the panel rules landed, since a background-image on a new element is how this
      regresses. Two rules cover `img`, `canvas`, `.sprite` and `.entity-icon`, `web/render/icon.ts`
      integer-scales every atlas frame, and the new 32px slots stay on whole-number scaling.
      "No smoothing, ever" now covers text as well as sprites - see the typeface entry.
- [x] Icons beside every entity name, in suggestion rows, and inside recipe grids.
      Of 2,191 index entries, two still draw nothing, and both are correct:
      `minecraft:spawner_minecart` and `minecraft:sulfur_cube_bucket`.
      The wiki publishes no sprite for either, and composing one from a Minecart plus a Spawner would
      invent art the game does not have, which Decision 3 forbids. The reason is recorded in
      `web/render/entry-icon.ts` so the next audit does not re-litigate it.
      `minecraft:breeze_wind_charge` borrows `InvSprite:Wind Charge`: the entity is the same object
      as the item, thrown rather than flying, so that is an identity rather than a guess.
- [x] **All 46 potion entities carry no icon.** The wiki publishes four potion sprites in total
      (`InvSprite:Potion`, `ItemSprite:potion`, `ItemSprite:splash-potion`, `ItemSprite:lingering-potion`),
      because the game tints one texture rather than shipping a sprite per variant, so there is no
      `Potion of Swiftness` file to resolve and Decision 3 forbids constructing one.
      Every potion page and every potion row of an Effect page therefore rendered iconless.
      The fix routes `entryIconKey()` through `potionIconKey()`, giving each effect-bearing potion
      its distinct coloured effect sprite (`EffectSprite:<effect>`) that says which potion it is,
      while falling back to the generic bottle sprite for the four effectless variants
      (`water`, `mundane`, `thick`, `awkward`).
- [x] Hostile/passive color coding consistent across every renderer.
      `.stat-behavior.is-hostile`, `.is-passive` and `.is-neutral` cover it.
- [x] Rarity color coding across pipeline and web.
      Extracted `minecraft:rarity` from `item_components/data.json` into typed `ItemRarity` (`common`,
      `uncommon`, `rare`, `epic`) via `pipeline/extract/rarity.py`. Schema contracts updated in
      `entity.schema.json` (`itemRarity`) and `index.schema.json` (`r`), generated into TypeScript types.
      Non-common tiers attached at merge time and search index emission. Rebuilt `data/dist` with 115
      tiered items. Rendered in web via CSS tokens (`--mc-yellow`, `--mc-aqua`, `--mc-purple`) across
      window titles (`.window-title`), suggestion names (`.suggestion-name`), and entity links (`.entity-name`).
- [x] Accessibility: contrast and focus rings.
      Every colour was measured against the surface it actually sits on. Body prose 12.9:1, headings
      5.9:1 on content and 4.5:1 on chrome, links 8.1:1 and 6.2:1, muted labels 6.5:1, hostile red
      5.4:1 - all at or above 4.5:1.
      Focus is one white outline rather than the old blue glow, on the focused window, the search bar
      and every control alike, so one visual language answers "where am I".
- [x] Accessibility: a reduced-motion path — deliberately dropped.
      Built once, reviewed, and reverted on purpose. The reversal is recorded here rather than
      dropped, so the next attempt does not rebuild the thing that was rejected.
      The shipped attempt honoured `(prefers-reduced-motion: reduce)` four ways: it froze the
      multi-member slot ticker in `web/render/station/ticker.ts`, added Left/Right stepping and a
      visible `›` button on every cycling slot, moved click/Enter/Space onto a full-member-list
      modal, and zeroed transition and animation durations globally via a media query in
      `web/theme/base.css`.
      It was reverted because freezing the cycle is the wrong trade for this product. The cycle is
      not decoration: it is the only thing on screen that says a torch takes coal *or* charcoal and
      that a plank slot accepts any of twelve woods. Windows sets the preference whenever "Show
      animations" is off, which is a display preference rather than a vestibular one, so the freeze
      reached readers who had asked for no such thing and deleted the information rather than the
      motion. `ticker.ts` already argued this in its docstring, the plan overrode it, and seeing it
      run settled it the other way.
      Two further faults the review found, worth keeping whoever tries next:
      the `›` step button and the list modal were built ungated, so they changed the default path
      for every reader rather than only the reduced-motion one; and routing click onto the modal
      displaced navigation on the two-second path, which no part of the plan asked for.
      What is still worth having, and is the whole of what a retry should attempt first, is the
      pure-CSS half: a `@media (prefers-reduced-motion: reduce)` block zeroing
      `transition-duration` and `animation-duration`. It touches no slot behaviour, costs nothing,
      and was removed only because it shipped inside the same commit as the part that was rejected.

### Palette, after review

The plan proposed Minecraft's own `§` codes throughout. Review changed three of them, and the
reasoning is recorded here because the code now disagrees with the plan.

- **Links are `#8bb3ff`, not aqua `#55ffff` and not blue `#5555ff`.** `#5555ff` was tried first and
  measured 3.35:1 on the content surface and 2.56:1 on chrome panels, under the 4.5:1 gate.
  `#8bb3ff` reaches 8.1:1 and 6.2:1.
- **The accent is `#00aaaa`, not yellow `#ffff55`.** It carries every heading, badge, chip and odds
  figure, so there is one accent rather than a heading colour and a badge colour.
- **Selection is quiet.** A selected suggestion row is an 8% white fill with no outline, and a
  focused window is a 20% white ring, replacing a 28% fill with a solid white outline and a solid
  4px white ring. Both are keyboard cursors, not alerts, and the old treatment was the loudest thing
  on the page.
- **No text shadows.** The 29 `text-shadow: 1px 1px 0 #3f3f3f` rules that imitated the game's GUI
  drop shadow are gone, along with the token that fed them.

## Phase 9 — Auto-update

- [x] `python -m pipeline check` compares the latest Mojang release to the built manifest.
      Implemented in `pipeline/cli/check.py`. Calls `fetch_version_manifest` and compares ordering
      in Mojang's `versions` array rather than string inequality, ensuring pinned snapshots ahead
      of the current release are not misidentified as behind. Supports `--json` machine-readable
      output on stdout and human lines on stderr, with `--dist` path selection.
- [x] Scheduled CI (daily) runs the check; on a new version it runs the full pipeline (no JDK
      needed in the runner — Python and Node only).
      `.github/workflows/auto-update.yml` triggers daily at 06:00 UTC and supports `workflow_dispatch`.
      Runs `python -m pipeline check --json`, evaluates `rebuild_owed`, and runs full build if owed.
      Generous 60-minute timeout accommodates 1,929 sprite fetches at the 10 rps polite rate limit.
- [x] CI opens a PR with the regenerated data and a human-readable diff summary
      (entities added, removed, changed).
      Implemented `python -m pipeline diff` in `pipeline/cli/diff.py`. Reads `index.json`, calculates
      net differences per entity kind, formats added and removed entity lists with names and IDs,
      truncates at 50 items for PR bodies, and exports full untruncated diffs to run artifacts.
      Actions PR creation setting enabled via `gh api` repository configuration: the repository
      default stays `read` and only this workflow asks for more, in its own `permissions:` block.
      Proven by run 34990992207, which opened PR #45 with a real body: the counts-by-kind table, the
      added and removed sections, and the gate's own 54-row check table as the "changed" report.
      Note what a reviewer of that PR does not get. A pull request opened with `GITHUB_TOKEN` does
      not trigger other workflows, so CI never runs on it. That is a GitHub rule rather than a
      choice made here, and the alternative, a stored Personal Access Token, was rejected during
      plan review because it needs rotation.
- [x] Validation gate blocks the PR on suspicious diffs rather than auto-merging.
      `.github/workflows/auto-update.yml` runs `pipeline build` without `--allow-regression`.
      On gate failure, the workflow catches failure, reads `data/reports/validation.json`, opens an
      issue naming the failed regression, conformance, and reference checks, and halts without
      opening a PR.
      One claim the first cut of this made was wrong, and the correction is recorded here so the
      reversal survives. It titled *every* build failure a validation-gate rejection, whatever had
      actually gone wrong. The first real run died fetching an upstream tag, never reached the gate,
      and opened an issue blaming the gate anyway, which sends a reader to the wrong subsystem.
      The report now claims a gate rejection only when `validation.json` recorded failed checks, and
      otherwise names the real cause and quotes the last 30 lines of the build log. See Decision 36.
- [x] Weekly wiki-only refresh so blurb and stat corrections land without a Minecraft release.
      Scheduled weekly on Mondays at 08:00 UTC (and via `workflow_dispatch` mode `wiki`). Runs cold
      without `actions/cache` restore of `data/.cache`, forcing fresh fetches from the wiki.
      It builds the version `data/dist/manifest.json` pins, passed as `--minecraft-version`.
      The first cut passed no version at all, and that was wrong in a way worth recording: with no
      flag, `pipeline/cli/build.py:583` resolves `options.minecraft_version or
      manifest.latest.release`, so the "wiki-only" job silently became a version upgrade. A
      `mode=wiki` dispatch proved it, logging `version: 26.3` against a manifest pinned to 26.2.
      That also made the job useless in the one window where it matters most: a release Mojang has
      shipped but mcmeta has not tagged yet, which is exactly when a wiki-only refresh is wanted.
      Passing the flag also turns the fetch cache on, keyed by that version, and that costs nothing
      here for the reason the bullet above already gives - `data/.cache` is gitignored and no step
      restores it, so a runner starts cold either way.
      Proven end to end by run 34990992207, which built 26.2 in 3m51s and opened PR #45. The refresh
      earned its place on its first real run: it caught the wiki reclassifying the Ocelot from
      `Passive` to `Neutral (Wild)` plus `Passive (Trusting)`, and rewording the Polar Bear and
      Wandering Trader entries. Twenty files changed at an unchanged `mcmetaRef` of `26.2-data`,
      which is the shape a wiki-only refresh is supposed to have, and the gate passed every check
      with 2191 entities before and after.
- [x] Deploy to GitHub Pages on merge to `main` (see Decision 4).
      `.github/workflows/deploy.yml` runs `pnpm build` and publishes `web/dist` through
      `actions/upload-pages-artifact` and `actions/deploy-pages`.
      The site ships straight out of the Actions run rather than from a committed `gh-pages` branch.
- [x] Set the repository's Pages source to "GitHub Actions" once.
      Configured via `gh api -X POST repos/nlaud/MC-FastWiki/pages -f build_type=workflow`,
      confirming Pages publishes directly from the workflow.
- [x] Assert the build stays under the limits a deploy can fail on: 1 GB per published site, and
      GitHub's 100 MB ceiling on any single committed file.
      `scripts/assert-dist-limits.js` asserts both trees: total `web/dist` size < 1 GB and single-file
      < 100 MB, plus committed `data/dist` files < 100 MB. Measured at 4.9 MB across 26 files with
      the largest at 743 KB (`data/obtain.json`), serving as automated build tripwires.
- [x] Smoke-test the deployed URL, not just the build output.
      `scripts/smoke-test.js` fetches the live deployed site at `https://nlaud.github.io/MC-FastWiki/`,
      extracts script and stylesheet asset links, and verifies every asset and core data payload
      returns HTTP 200 with non-empty content. Succeeded against live deployment.

## Phase 10 — Performance and offline

- [x] Service worker precaches the index and shell.
      Implemented in `web/sw.ts` and registered in `web/main.ts` behind `import.meta.env.PROD`.
      Emitted and injected during Vite `closeBundle` hook in `vite.config.ts`, precaching all 26
      emitted files (shell `index.html`, hashed assets, `index.json`, 18 entity shards, `obtain.json`,
      `sprites.json`, `sprites.png`, `manifest.json`, totaling 5.0 MB).
- [x] Entity payloads cached in Cache Storage (reversal from IndexedDB), versioned by build manifest.
      Reversal from IndexedDB: With all 18 entity shards totaling 2.9 MB already precached in Cache
      Storage to satisfy offline and speed requirements, storing duplicate JSON in IndexedDB under a
      second version key offered no measurable gain (shards parse in 3-5 ms in memory). Cache bucket
      is named deterministically from `manifest.json` (`mc-fastwiki-${minecraftVersion}-${builtAt}`)
      and cleaned up on service worker activation with `skipWaiting` and `clients.claim`.
- [x] Measure and enforce the two budgets: 16 ms per keystroke, 100 ms to rendered window.
      Enforced in `web/perf/budget.test.ts` on median of runs with headroom thresholds (35 ms keystroke,
      180 ms render) to prevent CI runner noise flaking while strictly catching regressions.
      Measured medians in Vitest: 0.53 ms keystroke, 3.15 ms window render. Measured medians in
      real Chrome browser via DevTools: 0.80 ms per keystroke, 59.1 ms to rendered window.
- [x] Confirm the app works fully offline after first load.
      Verified end-to-end in real browser using `chrome-devtools-axi emulate --network Offline`:
      reloaded site offline, performed search for Golden Apple, and rendered full entity window with
      complete stats, recipe grids, sources, and pixel sprites directly from precached atlas.

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

4. **Deploy to GitHub Pages.** The site is static, the repository is already on GitHub, and the
   whole deploy is one workflow that builds and calls `actions/deploy-pages`.
   No second account, no second dashboard, and no API token to store or rotate: the deploy identity
   is the repository's own `GITHUB_TOKEN`, scoped by the workflow's `pages: write` permission.

   This reverses an earlier choice of Cloudflare Pages, and the reversal is worth recording because
   the old rationale is still quoted in code.
   `pipeline/emit/atlas.py` and `pipeline/emit/shard.py` both justify atlasing and sharding by
   Cloudflare's 20,000-file cap, which no longer applies.
   Both remain right for the reason that outlives the host: 1,900 PNG requests to open one window
   misses the two-second budget on its own, and a handful of shard files beats five thousand entity
   files on any host at all.
   Those comments need rewording; the code they describe does not.

   GitHub Pages limits that actually shape the build: **1 GB per published site**, a **soft 100
   GB/month** bandwidth limit, and **10 builds per hour** for sites published from a branch.
   That last one does not apply to an Actions-published site, which is bounded by the account's
   Actions minutes instead.
   Today's output is 4.7 MB across 23 files, so none of these bind in practice, but CI asserts the
   size ceilings anyway, because the failure they prevent is a red deploy after a green build.

   What GitHub Pages will not give us, and what the project does not need: custom response headers
   or redirect rules (there is no `_headers` and no `_redirects`), anything server-side, and
   per-branch preview URLs.
   Two constraints are real.
   The repository has to stay public, because publishing Pages from a private repository needs a
   paid plan.
   And a project site is served from a path prefix rather than a root, so every asset URL has to be
   relative: `vite.config.ts` already sets `base: "./"` and the loaders already read
   `import.meta.env.BASE_URL`.
   That costs nothing today and would cost a blank unstyled page to forget, because every local
   check passes without it.
   A custom domain would move the site back to a root, where a relative base still works.

   Cloudflare Pages stays the fallback for the day bandwidth stops being theoretical: its static
   bandwidth and requests are unmetered, where the GitHub Pages 100 GB is a documented soft limit.
   Vercel is not a candidate either way.
   Its Hobby plan caps static bandwidth at 100 GB/month and *pauses the project* past that with no
   option to pay the overage, it forbids commercial use broadly enough to cover a paid contributor,
   and its whole pricing model is built around function invocations, which this project has none of.
   The build is host-agnostic in any case - a directory of static files with a relative base - so
   moving hosts means changing which workflow publishes it.

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

31. **TreeLayout for hierarchical collections like `advancements`.** Collections previously only supported
    flat member tables (`ListLayout`) with optional custom columns and sort keys. Advancements require
    representing the in-game progression trees across 5 root tabs (Minecraft, Nether, The End, Adventure,
    Husbandry), where order, depth, and parent-child hierarchy are critical to mid-match navigation.

    Manifests now support a discriminated `layout` union (`ListLayout` vs `TreeLayout`). `TreeLayout`
    specifies the section type to traverse (`AdvancementInfo`), explicit `groupOrder` for root IDs, and
    forbids `columns` and `sortBy`. The tree resolver performs depth-first traversal of each tree component,
    sorting sibling branches alphabetically by entity name to guarantee deterministic ordering across runs,
    and computes the indentation depth for each member. A new `CollectionTree` section type (`collectionTree`
    in JSON schema) emits grouped trees rendered with indented CSS custom property styling (`--depth`)
    and repeating 1px guide rules, ensuring clear hierarchy without horizontal overflow in narrow viewports.


32. **Curated tiers, section attachment, and member resolution for `compostable` and `fuel`.**
    Decision 30 deferred `compostable` and `fuel` because upstream mcmeta 26.2 and wiki buckets omit
    composting chances and furnace burn times. However, mid-match players urgently need these lookup
    targets (e.g. finding quick smelting fuel or composter odds). Both mechanics are game constants
    that rarely shift between releases.

    Rather than hand-writing flat 116- and 280-item manifests, we established a tiered curated data
    pattern under `data/curated/` (`compostable.json` with 5 chance tiers; `fuel.json` with 12 tick
    tiers). Tiers reference item tags (`minecraft:leaves`, `minecraft:saplings`, `minecraft:planks`,
    `minecraft:wooden_doors`, etc.) expanded through `TagIndex`. `fuel.json` supports `excludeTags`
    to strip non-fuel wooden items (e.g. `minecraft:non_flammable_wood` Nether stems and doors).
    Explicit item IDs override tag expansions, which is how `flowering_azalea_leaves` sits at 50%
    while the rest of `minecraft:leaves` sits at 30%.
    Every such override is named in the build report rather than applied silently: this build applies
    four, and all four are compost tiers.

    A strict loader (`pipeline/normalize/curated_facts.py`) guards data integrity with five
    deterministic faults, listed in that module's own docstring: an ID stated explicitly in two tiers,
    an ID or tag member naming no entity in this build, a tag resolving to zero members, a chance
    outside 1 to 100 or a burn time that is not a positive integer, and a `verifiedFor` release
    `release_order` does not contain.
    The last of these reuses the Decision D3 position check rather than adding a second version
    comparison.

    The build pipeline loads curated facts after `merge_entities` (Stage 7) and attaches `CompostInfo`
    and `FuelInfo` sections directly onto member entities before collections run. Collections resolve
    members via a new `section` membership rule (`"rule": {"type": "section", "section": "CompostInfo"}`
    and `"rule": {"type": "section", "section": "FuelInfo"}`), eliminating duplicate member lists.

    The section is the single source for both surfaces, which is the point of attaching it to the
    entity rather than keeping a side table: an item page and the collection row read the same number,
    so Coal cannot say 80s in one place and something else in the other.
    Member entities render `CompostInfo` and `FuelInfo` cards in the web UI with burn duration, smelt
    count, and composting chance. In the collection views, members sort descending by the numeric value
    underneath the formatted cell. Drift tests (`tests/test_collections_drift.py`) enforce the exact
    116 and 280 item baselines.

33. **CI workflows and GitHub Pages static deployment.**
    Stage 0 implements continuous integration across both project halves via `.github/workflows/ci.yml`,
    running parallel Web (Node 22 / pnpm 11.23.0) and Pipeline (Python 3.12 / uv) verification jobs covering
    all six repo gates (`pnpm test`, `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pytest`,
    `ruff check .`, `mypy`).

    Stage 1 publishes the site to GitHub Pages via `.github/workflows/deploy.yml`. GitHub Pages build
    type is set to GitHub Actions (`workflow`) via `gh api -X POST repos/nlaud/MC-FastWiki/pages -f build_type=workflow`.
    The deploy workflow builds static assets with `pnpm build`, runs `scripts/assert-dist-limits.js` to enforce
    GitHub's 1 GB published site ceiling and 100 MB single-file ceiling (including committed `data/dist`), uploads
    the `web/dist` artifact, and deploys using the native repository `GITHUB_TOKEN`. On deployment to `main`,
    an end-to-end smoke test (`scripts/smoke-test.js`) verifies that the live site serves 200 OK across the root
    page, parsed script/style assets, and dynamic data shards (`data/index.json`, `data/manifest.json`, etc.),
    preventing blank unstyled page regressions caused by relative base path issues.

34. **Auto-update pipeline and validation-gated pull requests.**
    Phase 9 implements the headless update loop in `.github/workflows/auto-update.yml` with three triggers:
    daily release check (06:00 UTC), weekly wiki refresh (Monday 08:00 UTC), and manual `workflow_dispatch`
    with `mode` selection (`release` or `wiki`).
    `pipeline check` (`pipeline/cli/check.py`) determines release order from Mojang's manifest `versions` array
    position rather than string inequality, preventing pinned snapshot builds from falsely triggering rebuilds.
    On a detected release or weekly refresh, CI rebuilds cold without caching `data/.cache`.
    If the validation gate rejects the build, an issue is opened detailing the failed checks from
    `data/reports/validation.json` and the job fails without creating a PR (`--allow-regression` is never passed).
    On success, `pipeline diff` (`pipeline/cli/diff.py`) computes exact added and removed entities grouped by kind
    from `data/dist/index.json`, formats counts and gate status into Markdown, truncates lists exceeding 50 items
    for the PR body, and saves the full untruncated report as an artifact before opening a PR using `gh pr create`.

35. **Cache Storage offline precaching, IndexedDB reversal, and performance budgets.**
    Phase 10 establishes full offline operation and guarantees the two core speed promises: <= 16 ms keystroke
    and <= 100 ms window render.

    **IndexedDB reversal:** The original plan called for storing entity payloads in IndexedDB alongside a
    service worker precaching the index and shell. However, the entire site payload is only 5.0 MB across 26
    files (all 18 entity shards sum to 2.9 MB, `obtain.json` is 761 KB, `index.json` is 363 KB). Precaching the
    shards in Cache Storage makes the entire dataset available offline immediately upon first load. Adding
    IndexedDB would have introduced dual version management, duplicated 2.9 MB of storage, and added complexity
    for no measurable benefit, as shard JSON parsing takes under 5 ms in memory. We dropped IndexedDB in favor of
    pure Cache Storage.

    **Service Worker & Build Injection:** `web/sw.ts` is compiled by Vite and registered in `web/main.ts`
    behind `import.meta.env.PROD`. The `closeBundle` hook in `vite.config.ts` walks `web/dist` and injects the
    exact list of 26 emitted files and the manifest-derived cache name (`mc-fastwiki-${minecraftVersion}-${builtAt}`)
    directly into `sw.js`. The worker activates with `skipWaiting` and `clients.claim`, deletes stale cache buckets,
    and serves same-origin GETs cache-first with fallback to `index.html` for navigation.

    **Budget Enforcement:** Automated regression tests (`web/perf/budget.test.ts`) assert median latencies across
    repeated runs over committed production data with headroom thresholds (35 ms keystroke, 180 ms render) to
    prevent CI runner noise from flaking while strictly catching algorithmic regressions. In Vitest, medians
    measured 0.53 ms keystroke and 3.15 ms render. In a real browser trace via `chrome-devtools-axi`, end-to-end
    medians clocked at 0.80 ms per keystroke and 59.1 ms to open and render a full entity window.

36. **A scheduled build failure is classified before it is reported, and upstream lag is not an
    incident.**
    The first real run of the auto-update workflow found Minecraft 26.3, correctly decided a rebuild
    was owed, and then failed: `misode/mcmeta` had not yet tagged 26.3, so both `26.3-summary` and
    `26.3-data` answered 404.

    `docs/mcmeta-fallback.md` already covers that case and already states the answer. mcmeta has
    published within hours of every release so far, the pipeline pins one version, and `/data/dist`
    holds the last build, so the deployed site keeps serving while the tag is missing. A missing tag
    stops a rebuild. It does not break the site. Waiting is the documented response, and a daily
    schedule performs that wait by itself.

    Two faults turned that wait into an incident, and both are fixed.

    The failure handler titled every build failure a validation-gate rejection. The gate never ran,
    so the issue it opened pointed at the wrong subsystem entirely and its body quoted a rule about
    regressions that had nothing to do with the fault. It now claims a gate rejection only when
    `validation.json` recorded failed checks, and otherwise names the real cause and quotes the last
    30 lines of the build log.

    An expected upstream lag opened an issue at all. mcmeta lags every Mojang release by hours, so a
    daily check lands in that window on every release, and an issue per run for a self-healing
    condition is noise that buries the reports worth reading. The workflow now detects the
    missing-tag 404 specifically, says so in the log, leaves the run green, and opens nothing. Any
    other build failure still opens an issue and still fails the run.

    The build step carries `continue-on-error` so the classifier can run after it, so the three
    post-build steps require `steps.build.outcome == 'success'` rather than relying on the job
    stopping by itself.

    Proven by re-dispatch against the same untagged 26.3: run 34987104118 failed and opened a
    misattributed issue, and run 34988150368 went green, opened nothing, and logged the real reason.

37. **The weekly refresh builds the pinned version, not Mojang's newest.**
    `pipeline build` resolves `options.minecraft_version or manifest.latest.release`
    (`pipeline/cli/build.py:583`), so a build invoked with no `--minecraft-version` follows Mojang.
    The workflow passed no flag, which made the job named "wiki-only refresh" a silent version
    upgrade. A `mode=wiki` dispatch proved it: run 34988251993 logged `version: 26.3` against a
    manifest pinned to 26.2, then failed because mcmeta had not tagged 26.3.

    That is the wrong behaviour twice over. The refresh exists to land wiki corrections *without* a
    Minecraft release, and following the release defeats its purpose. It also disabled the job in
    the one window where it is most wanted, a release Mojang has shipped and mcmeta has not tagged,
    because the build it chose could not run at all.

    The wiki path now reads `minecraftVersion` out of `data/dist/manifest.json` and passes it. The
    release path is unchanged and still follows Mojang, which is what that path is for.

    The fix also unblocked the only piece of Phase 9 that had never run. See the Phase 9 wiki bullet
    for what run 34990992207 caught on its first real pass.


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
