"""Merge Tier A, Tier B, and Tier C into the `Entity` model the site ships.

`pipeline.normalize`'s package docstring calls this the step Phase 2 stopped
one short of: `reconcile.py` proved that Tier A and Tier B *can* be joined and
reported where the join fails, but it never built an `Entity`. This module is
that step. `merge_entities` takes every index the earlier stages already
built -- the mcmeta registries, the wiki join table and sprite index, the five
Tier B tables `pipeline.enrich` reads, and the curated documents of Tier C --
and returns one `Entity` per registry ID, plus a report of every gap the merge
found along the way.

## Enumeration: one entity per ID, over the union, never one per (registry, ID)

CLAUDE.md's ID collision warning is not a corner case here, it is the norm:
`minecraft:stone` is both a block and an item, and `minecraft:chicken` is both
the raw meat item and the mob. The wiki has one `Chicken` article covering
both, and a player typing "chicken" wants the one page that answers "what is
this," not a choice between two nearly-identical results. So this module
collects the *union* of IDs across the six registries it knows how to give a
`kind`, builds one entity per ID, and chooses which registry that entity
belongs to when an ID sits in several.

Two rules make that choice, and the second one wins when it applies.
`_REGISTRY_PRECEDENCE` is the default order -- `entity_type` (mob), `block`,
`item`, `mob_effect`, `worldgen/biome`, `enchantment`, highest first. But
precedence is only ever a guess about which of two meanings a player wants,
and the wiki has usually already answered the question by choosing what to
call each row, so **the registry whose wiki row names the ID by its own name
wins**: `minecraft:ender_pearl` is an `entity_type` and an `item`, the wiki
writes `Ender Pearl` for the item and `Thrown Ender Pearl` for the
projectile, and matching the display name back against the registry path
picks the item. `_registry_the_wiki_names_the_id_under` holds the rule and
the measurement; `minecraft:chicken` is the case that proves it does not
simply prefer items, since there the mob's row is the one that names the ID.

Every ID that appeared in more than one of these six registries is named in
`MergeReport.multi_registry`, alongside the kind chosen, so the choice is
auditable rather than invisible.

Only these six registries -- the same six `pipeline.normalize.reconcile.
ICON_RULES` already names -- ever produce an entity. `registries` here is the
same full mcmeta payload `reconcile` takes (every registry name mapped to its
IDs), not a hand-picked six, but the other roughly 180 registries mcmeta
publishes -- `loot_table`, `sound_event`, `particle_type`, and the rest --
name nothing this project has a renderer or a `kind` for, and are left alone
by this stage exactly as they are left alone by `ICON_RULES`.

**`entity_type` is classified, not assumed.** This module used to map every
`entity_type` ID onto `kind="mob"` unconditionally, which was named in this
docstring as a known simplification rather than fixed -- an arrow, an item
frame, and a spawner minecart are entity types and none of them are mobs in
the sense a player means the word. `pipeline.extract.entity_class.
classify_entity_types` closes that gap, from two Tier A signals the pipeline
already downloads: a spawn egg item, `<path>_spawn_egg` in the `item`
registry, and an entity loot table, `loot_table/entities/<path>.json` in the
vanilla data pack. Measured against the cached 26.2 mcmeta payloads on
2026-08-31, `entity_type` holds 158 paths, 88 have a spawn egg, and 93 have a
loot table -- and the spawn-egg set is a *strict subset* of the loot-table
set, so the two signals never disagree, they only differ in reach.

Three ordered clauses follow, and `entity_class.EntityClass` names each one:

1. **A spawn egg -> a mob.** `entity_type` keeps the top of `_REGISTRY_
   PRECEDENCE` for this ID, exactly as it always has.
2. **No spawn egg, but a loot table -> undecided.** Defaults to `kind=
   "mob"`, the same default the whole registry used to get, but every such ID
   is now named in `MergeReport.undecided_entity_types` alongside the kind it
   ended up with, so a future version's new one cannot slip in silently the
   way all 158 used to. This clause is exactly 5 IDs, because it is precisely
   the 93-ID loot-table set minus the 88-ID spawn-egg subset: `armor_stand`,
   `giant`, `illusioner`, `mannequin`, `player`. `data/curated/overrides.json`
   corrects two of the five -- see that file's own note for which two and
   why the other three keep the default.
3. **Neither -> demoted.** Not a living thing by either signal, so
   `entity_type` is moved to the *bottom* of that ID's own registry
   precedence, letting a `block` or `item` membership win instead. Only an ID
   with no other registry membership at all becomes the new
   `EntityKind.ENTITY`. This clause holds 65 IDs: 1 also sits in `block`
   (`tnt`), 41 also sit in `item`, and 23 sit nowhere else and become
   `kind="entity"`.

The demotion is what finally closes a split this module's own precedence
used to leave open. `acacia_boat` resolved to `item` before this rule existed
-- the wiki's `Acacia Boat` row names the ID exactly, so `_registry_the_wiki_
names_the_id_under` fired -- but `acacia_chest_boat` resolved to `mob`,
because the wiki titles that row `Boat with Chest` and nothing fired. Two
halves of the same concept, split by how the wiki happened to title a row.
The demotion settles both the same way regardless of wiki phrasing, because
neither boat has a spawn egg or a loot table.

**The demotion runs after clause 1, never before it**, which is the property
`tests/test_normalize_merge.py` pins as a regression test. `minecraft:
chicken` is a mob with a raw-meat item sharing its ID, and so are `cod`,
`salmon`, `pufferfish`, `tropical_fish`, and `rabbit` -- every one of them
has a spawn egg, so clause 1 fires first and `entity_type` keeps precedence
before the demotion logic ever runs. Resolving one of those mobs through its
item's wiki row instead of its own is a real past failure this module's
`_own_row` docstring records in full; the demotion exists to fix a different
problem and must never reopen that one.

Advancements enumerate separately, from `advancement_ids` --
`pipeline.extract.advancement.extract_advancement_ids`'s output -- as
`minecraft:<internal_id>` with `kind="advancement"`. They carry no registry
membership to precede against, because no other registry uses the `story/
mine_stone` shape of ID.

## The join direction, and the trap `pipeline.normalize.reconcile` already names

Every Tier B index this module reads is keyed by *wiki display name*, never
by registry ID: `DropIndex.by_mob`, `SpawnIndex.by_mob`, `TradeIndex.
by_given_item`. This module walks each of those indexes forward, resolving
one display name onto zero, one, or more than one registry ID, rather than
walking the entities and looking a name up -- the forward direction is what
lets an unresolvable row fall out as one `MergeReport.unplaced` entry instead
of a silent absence. Every resolution is narrowed by the wiki's own `kind`
vocabulary for the registry in question -- `WIKI_KIND` records the mapping,
reusing `ICON_RULES["item"].join_kinds` and `ICON_RULES["block"].join_kinds`
where those already exist and adding the three the icon route never needed
(`entity_type` is `entity` on the wiki, `mob_effect` is `effect`, `worldgen/
biome` is `biome`, per `IconRule`'s own docstring) plus `enchantment`, whose
rows the wiki leaves entirely unclassified. `IconRule.join_kinds`'s own
docstring records what skipping this narrowing already cost once: 5
correctly-iconed items pushed into a missing-icon report on 2026-08-30 by a
join that could not tell an item's row from a same-named entity's row. A
resolution that stays ambiguous after narrowing attaches nothing and is
reported -- a missing drop table is a visible gap, a drop table attached to
the wrong entity is a wrong answer mid-match.

## Field merge

`id` and `kind` are Tier A, chosen as above. `name` is the Tier B
`ResourceLocation.display_name` of the entity's own row; `_own_row` holds how
that row is chosen and what it refuses to guess at. Otherwise `name` falls
back to the Tier A path, title-cased with underscores turned to spaces. That
fallback is deliberately naive -- an ID the wiki has never heard of becomes
`Poplar Shelf`, and an unfortunate one would become `Tnt` -- and it only ever
reaches an ID with no wiki row at all. Measured against the live 26.2 data on
2026-08-31 it reaches 8 IDs, all of them genuinely ambiguous rather than
undocumented.
`icon` tries `resolve_icon` against every registry the ID belongs to, in the
same kind-precedence order, and stops at the first family that resolves --
unlike `name`, the icon route is allowed to fall back across an ID's
registries, because a mob that happens to have no `EntitySprite` but does
have a working `ItemSprite` should still get an icon rather than a reported
gap. `enchantment` stays exempt from that report, per `ICON_RULES["enchantment"
].has_icons`, the same exemption `reconcile` already gives it. `blurb` and
`wikiUrl` come from the resolved row's `page`/`wiki_url` and `ExtractReport.
blurbs()`, keyed by that page title.

## Alias ordering is part of the contract

`EntityDraft.add_aliases` preserves first-insertion order and `Entity.
aliases` emits it unchanged, so the order this module inserts aliases in is
the order Phase 4's matcher will see forever after. `pipeline.normalize.
aliases.generate_aliases` already returns its `(alias, strength)` pairs
strongest-first; this module inserts them one call per alias, in that order,
so each alias keeps the tier it actually came from (`SourceTier.C` for a
`CURATED` alias, `SourceTier.A` for everything `generate_aliases` derives
from the registry ID alone) while the emitted order stays strength-ordered.
Reordering this loop, or batching several aliases into one `add_aliases`
call, would silently collapse the ordering guarantee this whole module exists
to uphold -- see `pipeline.normalize.aliases`'s own module docstring for what
that guarantee is protecting.

## A curated `kind` override, and the one place it cannot reuse `EntityDraft.set`

`EntityDraft.__init__`'s own docstring is explicit that `kind` is set once,
at construction, "because it is the join key this draft was opened for
rather than a value a later merge step could overwrite" -- `EntityDraft.set`
refuses any field name it does not already know, and `kind` is deliberately
not one of them. A curated `kind` override therefore cannot be applied the
way a `name`/`icon`/`blurb`/`wikiUrl` override is: this module resolves the
*effective* kind (registry precedence, then a curated override if one names
this ID) before ever constructing the `EntityDraft`, and passes that resolved
kind to the constructor. The value written to `Entity.kind` is correct
either way. What is not perfectly precise is `sourceTiers["kind"]`: because
`id` and `kind` share one `tier` argument at construction and `id` is always
genuinely Tier A, an overridden `kind` is still recorded as Tier A
provenance rather than Tier C. `/data/curated/overrides.json` ships with an
empty `entities` map, so this path is untested by a live override today --
`tests/test_normalize_merge.py` exercises it directly with a synthetic
`CuratedData` instead. Widening `EntityDraft` to track `id` and `kind`
provenance separately would close this gap cleanly, and is a small, focused
follow-up to part 1's `entity.py` rather than something this task's brief
asked for or that this module reaches into `entity.py` to do uninvited.

## The report, and what still raises

Like `reconcile`, this module never fails a build over one entity's gap --
a missing icon, an unplaced drop table row, a stale curated document are all
`MergeReport` entries, not exceptions, for the same reason CLAUDE.md gives
throughout: Tier B disagreeing with Tier A is the presentation layer
disagreeing with the completeness layer, and a threshold on how much
disagreement is acceptable belongs to Phase 3's validation gate, not to this
merge. `NormalizeError` is reserved for a shape fault exactly as
`pipeline.normalize`'s package docstring defines it: an empty `registries`
mapping, an empty `join_table`, an empty `sprite_index`, or a registry this
module's precedence names that the mcmeta payload does not publish.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import advancement as enrich_advancement
from pipeline.enrich import breeding as enrich_breeding
from pipeline.enrich import droptable as enrich_droptable
from pipeline.enrich import effect as enrich_effect
from pipeline.enrich import infobox as enrich_infobox
from pipeline.enrich import spawn_table as enrich_spawn_table
from pipeline.enrich import trade as enrich_trade
from pipeline.enrich.profession_infobox import ProfessionInfobox
from pipeline.enrich.resource_location import (
    NAMESPACE,
    JoinTable,
    ResourceLocation,
    alternative_names,
    alternative_registry_id,
)
from pipeline.enrich.sprite import SpriteIndex
from pipeline.extract.biome import BiomeIndex
from pipeline.extract.enchantment import EnchantIndex
from pipeline.extract.entity_class import EntityClass, EntityClassification
from pipeline.extract.feature_place import FeaturePlaceIndex
from pipeline.extract.food import ConsumeEffectKind, FoodFacts
from pipeline.extract.generation import BlockGeneration, Dimension
from pipeline.extract.harvest import BlockHarvest, HarvestTier, HarvestTool
from pipeline.extract.profession import ProfessionIndex, extract_professions
from pipeline.extract.structure import (
    RandomSpreadPlacement as ExtractedRandomSpreadPlacement,
)
from pipeline.extract.structure import (
    StructureIndex,
)
from pipeline.fetch.extracts import ExtractReport
from pipeline.normalize import NormalizeError
from pipeline.normalize.aliases import AliasStrength, generate_aliases
from pipeline.normalize.curated import CuratedData, StaleDocument
from pipeline.normalize.entity import (
    AdvancementInfo,
    ApplicableItems,
    BiomeInfo,
    BiomeSpawnEntry,
    BreedingInfo,
    BreedingItem,
    ChestLoot,
    ChestLootContainer,
    ChestLootItem,
    ConcentricRingsPlacement,
    DamageValue,
    DistributionEntry,
    DropEntry,
    DropNote,
    DropTable,
    EffectLink,
    EffectSource,
    EffectSources,
    EnchantInfo,
    Entity,
    EntityDraft,
    EntityKind,
    EntityRef,
    ExclusionZone,
    FoodEffect,
    FoodInfo,
    GenerationInfo,
    GenerationScope,
    HarvestDrop,
    HarvestGate,
    HarvestInfo,
    IntegerRange,
    ItemAmount,
    JavaProbability,
    LabelledText,
    LabelledValue,
    LinkList,
    LootingDrop,
    Measure,
    NoisePlacement,
    ProfessionInfo,
    RandomSpreadPlacement,
    Ratio,
    Section,
    SizeValue,
    SourceTier,
    SpawnEntry,
    SpawnInfo,
    StatBlock,
    StructureInfo,
    StructurePlacement,
    StructureSibling,
    StructureSpawnEntry,
    TradeEntry,
    TradeTable,
    VeinInfo,
)
from pipeline.normalize.reconcile import ICON_RULES, resolve_display_name_icon, resolve_icon
from pipeline.obtain.brewing import POTION_ID_TEMPLATE
from pipeline.obtain.chests import ChestSource, by_structure
from pipeline.obtain.loot import SHEARS_NOTE, SILK_TOUCH_NOTE
from pipeline.obtain.producer import ObtainMethod, Producer

__all__ = [
    "DEFAULT_REPORT_PATH",
    "WIKI_KIND",
    "MergeReport",
    "MergeResult",
    "MissingBlurb",
    "MissingIconEntity",
    "MultiRegistryId",
    "UndecidedEntityType",
    "UnplacedRow",
    "block_drops_from_producers",
    "merge_entities",
    "names_the_wiki_reuses",
    "resolve_structure_pages",
    "write_report",
]

# Where `merge_entities`'s report lands by default, matching `pipeline.
# normalize.reconcile.DEFAULT_REPORT_PATH`'s precedent: `data/reports/` is
# gitignored, and the writer takes an explicit path so a later emit stage can
# redirect it without editing this module.
DEFAULT_REPORT_PATH = Path("data") / "reports" / "merge-report.json"

# The six registries this module can give a `kind`, highest precedence first.
# See the module docstring's enumeration section for the reasoning, and
# `ICON_RULES` for why these are the same six `reconcile` already reads.
_REGISTRY_PRECEDENCE: tuple[str, ...] = (
    "entity_type",
    "block",
    "item",
    "mob_effect",
    "worldgen/biome",
    "enchantment",
)

# `entity_type` is deliberately absent from this mapping. Its `EntityKind`
# depends on the ID's `entity_class.EntityClass` -- `MOB` for `SPAWN_EGG` and
# `LOOT_TABLE_ONLY`, `ENTITY` for a `NEITHER`-classified ID that reaches
# `entity_type` at all (which, after the demotion, only happens when
# `entity_type` is the ID's sole registry) -- so `_entity_type_kind` answers
# it instead of a static lookup. Every other registry's kind never varies by
# ID, so a static mapping is still the right shape for the other five.
_REGISTRY_KIND: Mapping[str, EntityKind] = {
    "block": EntityKind.BLOCK,
    "item": EntityKind.ITEM,
    "mob_effect": EntityKind.EFFECT,
    "worldgen/biome": EntityKind.BIOME,
    "enchantment": EntityKind.ENCHANTMENT,
}


# The wandering trader, named once for the three places that need it. The
# `trade` bucket groups its 97 trades under a `profession` column, but the
# `villager_profession` registry does not list it, so it is a mob here and not
# a profession entity: its trades attach to the mob page it already has, and
# its name resolves to that mob wherever a trade group is headed by a seller.
WANDERING_TRADER_ID = f"{NAMESPACE}:wandering_trader"
WANDERING_TRADER_NAME = "Wandering Trader"


def _entity_type_kind(entity_class: EntityClass) -> EntityKind:
    """Return the default `EntityKind` of an `entity_type` ID from its classification.

    Only ever called for the registry `_registries_of_id` chose as an ID's
    own -- which for `entity_type` means either the ID has a spawn egg or a
    loot table (clause 1 or 2, both default to `EntityKind.MOB`), or the ID
    was demoted for clause 3 (`EntityClass.NEITHER`) and had no other
    registry to fall back to, in which case `EntityKind.ENTITY` is the only
    honest answer -- see `EntityKind`'s own docstring for what that kind
    holds and, explicitly, what it never holds.
    """
    if entity_class is EntityClass.NEITHER:
        return EntityKind.ENTITY
    return EntityKind.MOB


# The wiki `Type` value(s) that name an ID of one Tier A registry, for
# narrowing a display-name join the way `IconRule.join_kinds` narrows the
# icon route. `item` and `block` reuse `ICON_RULES`'s own field rather than
# duplicate it with a chance to drift; the other three are recorded here
# because their icon route never reads a display name at all (`IconRule`'s
# docstring gives the reason), so `ICON_RULES` never had to carry them.
# `enchantment` rows carry no `Type` at all -- see `pipeline.enrich.
# resource_location`'s `KNOWN_KINDS` docstring -- so `None` is the wiki kind
# that means "an enchantment."
#
# Public, and named in `__all__`, because `pipeline.cli.build` needs the exact
# same rule to pick which wiki pages carry a mob's `{{Infobox entity}}` --
# "the row's own wiki `Type` reads `entity`" is one of the three clauses of
# that selection, and duplicating the mapping there would let the two drift
# the moment a future registry gains a `WIKI_KIND` entry here and not there.
# It was private until the CLI needed it; nothing about its own meaning
# changed, so every use inside this module keeps reading it exactly as before.
WIKI_KIND: Mapping[str, tuple[str | None, ...]] = {
    "item": ICON_RULES["item"].join_kinds,
    "block": ICON_RULES["block"].join_kinds,
    "entity_type": ("entity",),
    "mob_effect": ("effect",),
    "worldgen/biome": ("biome",),
    "enchantment": (None,),
}


# The wiki page title of every non-prefixed potion path that has one,
# verified live against the `resource_location` bucket on 2026-09-01
# (`bucket('resource_location').where('resource_location','potion')`). Only
# 24 of the 46 registry paths have a page at all: every `long_`/`strong_`
# variant is presentation of the base potion rather than a separate article,
# so none of the 22 modified paths appears here, and `_potion_name` derives
# their name instead of reading one.
#
# `"awkward"` is deliberately resolved by page title, `"Awkward Potion"`,
# rather than by the wiki's own `display_name` for it, which is the bare
# string `"Potion"` -- the same display name the generic `Potion` overview
# page also carries. Two registry-`minecraft:potion` rows sharing one
# display name is exactly the ambiguity `pipeline.normalize.resource_
# location.JoinTable.resolve` refuses to pick between, and matching on the
# page title this module already knows sidesteps the question entirely
# instead of asking the join table to break a tie it correctly won't.
_POTION_PAGE_TITLES: Mapping[str, str] = {
    "awkward": "Awkward Potion",
    "water": "Water Bottle",
    "mundane": "Mundane Potion",
    "thick": "Thick Potion",
    "weakness": "Potion of Weakness",
    "fire_resistance": "Potion of Fire Resistance",
    "regeneration": "Potion of Regeneration",
    "strength": "Potion of Strength",
    "swiftness": "Potion of Swiftness",
    "harming": "Potion of Harming",
    "poison": "Potion of Poison",
    "slowness": "Potion of Slowness",
    "healing": "Potion of Healing",
    "night_vision": "Potion of Night Vision",
    "invisibility": "Potion of Invisibility",
    "water_breathing": "Potion of Water Breathing",
    "leaping": "Potion of Leaping",
    "luck": "Potion of Luck",
    "turtle_master": "Potion of the Turtle Master",
    "slow_falling": "Potion of Slow Falling",
    "weaving": "Potion of Weaving",
    "oozing": "Potion of Oozing",
    # Irregular on purpose: the wiki's page and display name are "Potion of
    # Infestation" and "Potion of Wind Charging", not the effect's own name
    # ("Infested", "Wind Charged") with "Potion of" glued on the front.
    "infested": "Potion of Infestation",
    "wind_charged": "Potion of Wind Charging",
}

_LONG_POTION_PREFIX = "long_"
_STRONG_POTION_PREFIX = "strong_"

# The wiki writes a trade for an enchanted item under a display name the
# registry does not carry, because an enchantment is data on a stack rather
# than a separate item. `_wiki_rows` strips this prefix, but only after the
# full name has failed to resolve; see that function's own docstring.
ENCHANTED_PREFIX = "Enchanted "

# The wiki's own disambiguator between a mob and the item it drops -- `Pufferfish
# (item)` against the pufferfish mob. It is page-title punctuation, never part of
# a name the game uses, so `_wiki_rows` strips it on the same terms as the prefix
# above: only after the full name has failed to resolve.
ITEM_SUFFIX = " (item)"


def _potion_name(path: str) -> str:
    """Return the display name of the potion at `path`.

    Prefers `_POTION_PAGE_TITLES` for the 24 paths with a wiki page. A
    `long_`/`strong_` path with no page of its own is derived from its base
    potion's name, `"Potion of Regeneration (Long)"`, per this task's own
    brief -- there is no page to prefer, per the module docstring's
    ambiguity note above the title table.
    """
    for prefix, modifier in ((_LONG_POTION_PREFIX, "Long"), (_STRONG_POTION_PREFIX, "Strong")):
        if path.startswith(prefix):
            base = _potion_name(path[len(prefix) :])
            return f"{base} ({modifier})"
    title = _POTION_PAGE_TITLES.get(path)
    if title is not None:
        return title
    return f"Potion of {path.replace('_', ' ').title()}"


class UnplacedRow(BaseModel, frozen=True):
    """One Tier B row this merge could not attach to any entity, and why.

    Mirrors `pipeline.enrich.SkippedRow`'s shape for the same reason: a
    report that cannot say what it dropped is indistinguishable from a
    report with nothing wrong at all.
    """

    table: str
    subject: str
    reason: str


class MultiRegistryId(BaseModel, frozen=True):
    """One Tier A ID that sat in more than one of the six precedence registries."""

    id: str
    registries: tuple[str, ...]
    kind: EntityKind


class UndecidedEntityType(BaseModel, frozen=True):
    """One `entity_type` ID that clause 2 of the classification rule left undecided.

    Named alongside `kind`, the same shape `MultiRegistryId` already uses for
    the same auditability reason: the module docstring's classification
    section explains why the clause 2 default is `EntityKind.MOB` and why a
    curated override may have moved it since. Every ID here has no spawn egg
    but does have an entity loot table -- see `pipeline.extract.entity_class`
    for the two signals in full.
    """

    id: str
    kind: EntityKind


class MissingIconEntity(BaseModel, frozen=True):
    """One entity whose icon chain never resolved, across every registry it belongs to."""

    id: str
    routes_tried: tuple[tuple[str, str, str], ...]


class MissingBlurb(BaseModel, frozen=True):
    """One entity whose Tier B page carried no `TextExtracts` blurb."""

    id: str
    page: str


class MergeReport(BaseModel, frozen=True):
    """What one merge produced, beyond the entities themselves.

    Never fails a build on its own -- see the module docstring's closing
    section for the reason, which is the same one `pipeline.normalize.
    reconcile.ReconciliationReport` already gives.
    """

    unplaced: tuple[UnplacedRow, ...] = ()
    multi_registry: tuple[MultiRegistryId, ...] = ()
    undecided_entity_types: tuple[UndecidedEntityType, ...] = ()
    missing_icons: tuple[MissingIconEntity, ...] = ()
    missing_blurbs: tuple[MissingBlurb, ...] = ()
    unknown_curated_overrides: tuple[str, ...] = ()
    stale_curated_documents: tuple[StaleDocument, ...] = ()
    split_ids: tuple[str, ...] = ()
    advancement_reconciliation: enrich_advancement.Reconciliation
    counts: Mapping[str, int] = {}


class MergeResult(BaseModel, frozen=True):
    """The finished merge: every entity, indexed, and the report of the merge that built them."""

    entities: tuple[Entity, ...]
    by_id: Mapping[str, Entity]
    report: MergeReport

    @model_validator(mode="after")
    def _by_id_must_match_the_entities(self) -> "MergeResult":
        """Refuse an index that does not index its own entities."""
        expected = {entity.id: entity for entity in self.entities}
        if dict(self.by_id) != expected:
            raise NormalizeError("the by_id index does not match the entities of this result.")
        return self


def _fallback_name(path: str) -> str:
    """Return the naive Tier A fallback name of a registry path.

    Deliberately naive -- `tnt` becomes `Tnt`, not `TNT` -- because it only
    ever reaches an ID the wiki has no row for at all. See the module
    docstring's field-merge section for the measurement behind that claim.
    """
    return path.replace("_", " ").title()


def resolve_structure_pages(
    structure_index: StructureIndex, join_table: JoinTable
) -> dict[str, tuple[str, str]]:
    """Return each structure id's `(display_name, wiki_page)`.

    Public, and called from two places on purpose. `merge_entities` needs the
    pair to name the entity and to look its blurb up; `pipeline.cli.build` needs
    the *page* half before that, because a page nothing asked the extracts
    fetcher for has no blurb to look up by the time the merge runs.

    Deriving the page in only one of those places is exactly the fault this
    function exists to prevent. The village fallback below resolves three ids to
    `Village`, a page no other stage requests -- the join table lists it under a
    village variant's *display name*, never as that variant's own page -- so a
    build that resolved it here and fetched elsewhere left Savanna, Snowy and
    Taiga Village with a `wikiUrl` pointing at prose their entity did not carry.

    The village rule: the `resource_location` bucket maps every village variant
    to four candidate pages, so prefer the one whose title is the variant's own
    display name and fall back to `Village` otherwise. `Plains Village` and
    `Desert Village` have a page of their own; the other three do not, and share
    the one article the wiki actually wrote.
    """
    resolved: dict[str, tuple[str, str]] = {}
    for sid in structure_index.structures:
        rows = [r for r in join_table.by_registry_id.get(sid, ()) if r.kind == "env"]
        if not rows:
            rows = list(join_table.by_registry_id.get(sid, ()))
        if rows:
            row = rows[0]
            display_name = row.display_name
            if sid.startswith(f"{NAMESPACE}:village_"):
                page = row.page if row.page == display_name else "Village"
            else:
                page = row.page
        else:
            path = sid.split(":", 1)[-1]
            display_name = _fallback_name(path)
            page = display_name
        resolved[sid] = (display_name, page)
    return resolved


def names_the_wiki_reuses(join_table: JoinTable) -> frozenset[str]:
    """Return the display names several registry ids share while each keeps its own page.

    The wiki's `display_name` is the *in-game item name*, and for one family that
    name is deliberately not unique: all 22 music discs are called `Music Disc`,
    because that is what the game prints on the stack, with the track shown only
    in the tooltip. A reference tool that repeats it renders 22 identical rows,
    and a dungeon chest listing three discs at three different odds becomes
    unreadable -- the reader cannot tell which one is the 1.4%.

    The wiki has the better name and files it as the *page title*: `Music Disc 13`,
    `Music Disc Pigstep`, `Music Disc Creator (Music Box)`. So a name in this set
    tells the merge to take the page title instead of the shared display name.

    Both halves of the condition matter. Several ids must share the name, and
    their pages must actually differ. That second half is what keeps this from
    touching the four other collisions in the build, none of which is this
    problem: `Wind Charge` and `Eye of Ender` are each two registry ids for one
    page, so there is no better name to take, and `Hero of the Village` and
    `The End` collide across two different *kinds*, where the kind badge already
    tells them apart and renaming either would be wrong. Measured against the
    live 26.2 data, this set holds exactly one name.
    """
    pages_by_name: dict[str, set[str]] = {}
    ids_by_name: dict[str, set[str]] = {}
    for row in join_table.entries:
        pages_by_name.setdefault(row.display_name, set()).add(row.page)
        ids_by_name.setdefault(row.display_name, set()).add(row.registry_id)
    return frozenset(
        name
        for name, pages in pages_by_name.items()
        if len(pages) > 1 and len(ids_by_name[name]) > 1
    )


def _build_chest_loot(
    place_id: str,
    containers_by_place: Mapping[str, Sequence[tuple[str, ChestSource]]],
    producers_by_table: Mapping[str, Sequence[Producer]],
    drafts: Mapping[str, EntityDraft],
) -> ChestLoot | None:
    """Return the `ChestLoot` section of one place, or `None` when it holds no container.

    Shared by the 34 structures and by the curated feature places, because a
    dungeon's chest is read from the same curated attribution and the same loot
    producers as a bastion's. A place with no container gets `None` rather than an
    empty section, so its page omits the heading instead of printing one over
    nothing -- the rule `renderGenerationInfo` already follows.
    """
    container_tuples = containers_by_place.get(place_id, ())
    if not container_tuples:
        return None

    containers: list[ChestLootContainer] = []
    for table_path, chest_src in container_tuples:
        items: list[ChestLootItem] = []
        for prod in producers_by_table.get(table_path, ()):
            item_id = prod.output.item
            item_name = (
                drafts[item_id].name
                if item_id in drafts
                else _fallback_name(item_id.split(":", 1)[-1])
            )
            stack_max = prod.count_max if prod.count_max is not None else prod.output.count
            items.append(
                ChestLootItem(
                    item=EntityRef(id=item_id, name=item_name),
                    chance=float(prod.chance) if prod.chance is not None else 1.0,
                    stack_range=IntegerRange(minimum=prod.output.count, maximum=stack_max),
                )
            )
        items.sort(key=lambda it: (-it.chance, it.item.name, it.item.id))
        containers.append(ChestLootContainer(label=chest_src.container, items=tuple(items)))

    return ChestLoot(containers=tuple(containers)) if containers else None


def _biome_ref(biome_id: str, join_table: JoinTable) -> EntityRef:
    """Return an EntityRef for a biome, using its display name if known, else a fallback."""
    rows = join_table.by_registry_id.get(biome_id, ())
    for row in rows:
        if row.kind == "biome":
            return EntityRef(id=biome_id, name=row.display_name)
    path = biome_id.split(":", 1)[-1]
    return EntityRef(id=biome_id, name=_fallback_name(path))


def _wiki_rows(name: str, registry: str, join_table: JoinTable) -> tuple[ResourceLocation, ...]:
    """Return the rows of `join_table.by_display_name[name]` whose kind fits `registry`.

    `WIKI_KIND` is not optional here, for the reason `IconRule.join_kinds`'s
    own docstring gives in full: a raw chicken item and the chicken mob share
    one registry ID and, on some pages, one display name, and reading both
    kinds as candidates is how one gets silently resolved through the
    other's row.

    **`Enchanted <item>` falls back to `<item>`.** An enchantment is data on an
    item stack, not a separate registry entry, so there is no
    `minecraft:enchanted_diamond_chestplate` for that name to reach. The wiki
    still writes the trade as `Enchanted Diamond Chestplate`, because that is
    what the villager sells. Without the fallback those rows resolved to
    nothing and fell out as `MergeReport.unplaced`, which is why Diamond
    Chestplate, Diamond Pickaxe, Diamond Sword and Fishing Rod each carried no
    trades at all while Iron Chestplate and Diamond Hoe, whose trades are for
    unenchanted items, carried theirs. 15 trade rows were lost that way.

    The exact name is always tried first and the fallback only runs when it
    finds nothing, which is what keeps `Enchanted Book` and `Enchanted Golden
    Apple` pointing at themselves: both are real registry items, both resolve
    on the first attempt, and neither ever reaches the second.

    **`<item> (item)` falls back to `<item>`.** The parenthetical is the wiki's
    own disambiguator between a mob and the item it drops, not part of any
    name the game uses. `Tropical Fish (item)` and `Pufferfish (item)` are
    both written that way by `trade` and by the food lists, and neither has a
    registry entry under the suffixed spelling.

    **Two families resolve through `pipeline.enrich.resource_location`.**
    `<Pattern> Armor Trim` and `Arrow of <Effect>` are nicknames for a longer
    display name, and `Music Disc <Song>` is a page title that names a
    registry ID outright; that module owns all three because
    `pipeline.obtain.loot` reads the identical rules against the same join
    table, and a second copy of them here would be free to drift.

    **A page title is the last resort.** Some rows carry a display name the
    bucket never lists but a page title does -- `Leather Tunic` for
    `minecraft:leather_chestplate`, `The End (biome)` for `minecraft:the_end`.
    It runs last because a page title is a weaker claim than a display name:
    one page can name several rows, and a page match that is ambiguous is
    handled by `_disambiguate_ids` or dropped, never guessed.
    """
    wanted = WIKI_KIND.get(registry, ())

    def rows_for(display_name: str) -> tuple[ResourceLocation, ...]:
        return tuple(
            row for row in join_table.by_display_name.get(display_name, ()) if row.kind in wanted
        )

    rows = rows_for(name)
    if rows:
        return rows

    if name.startswith(ENCHANTED_PREFIX):
        rows = rows_for(name.removeprefix(ENCHANTED_PREFIX))
        if rows:
            return rows

    if name.endswith(ITEM_SUFFIX):
        rows = rows_for(name.removesuffix(ITEM_SUFFIX))
        if rows:
            return rows

    for alternative in alternative_names(name):
        rows = rows_for(alternative)
        if rows:
            return rows

    direct_id = alternative_registry_id(name)
    if direct_id is not None:
        rows = tuple(
            row for row in join_table.by_registry_id.get(direct_id, ()) if row.kind in wanted
        )
        if rows:
            return rows

    return tuple(row for row in join_table.entries if row.page == name and row.kind in wanted)


def _own_row(
    entity_id: str, registries: Sequence[str], join_table: JoinTable
) -> ResourceLocation | None:
    """Return the one Tier B row of `entity_id`, or `None` when none resolves cleanly.

    Reads `join_table.by_registry_id` -- the reverse of `_wiki_rows` -- and
    narrows it the same way, by the wiki kind(s) a registry may use. Each
    registry `entity_id` belongs to is tried in turn, in the kind precedence
    order `registries` already carries, and the first that answers with
    exactly one display name wins.

    **Every attempt is still kind-narrowed, and that is the part that must
    not be relaxed.** `IconRule.join_kinds`'s docstring records what an
    unnarrowed lookup costs: `minecraft:chicken` is the raw chicken *item*
    and the chicken *mob*, `by_registry_id` answers with both rows, and
    resolving the item through the mob's row is the wrong-answer failure this
    project ranks below a missing one. Narrowing keeps that closed. Trying
    `entity_type` first and then `item` does not reopen it, because the
    `entity` row and the `item` row are asked for separately and the first
    hit is the one whose registry has precedence: chicken still resolves
    through its `entity` row.

    Walking past the first registry is what the live data forced. Measured
    against the 26.2 registries on 2026-08-31, 209 IDs sit in `entity_type`
    and in `item` while the wiki documents only the item -- the boats and
    their chest variants, the minecarts, the spawn eggs. `acacia_boat` is one:
    `entity_type` wins the kind precedence, no `entity` row exists, and
    stopping there dropped the name, the page, the blurb and the `wikiUrl`
    of an entity whose icon still resolved through the id route. That left a
    Tier B provenance entry with no attribution link, which decision D1
    refuses outright, so the merge did not merely lose data -- it could not
    build at all.
    """
    all_rows = join_table.by_registry_id.get(
        f"{NAMESPACE}:{entity_id.removeprefix(f'{NAMESPACE}:entity_type/')}"
        if entity_id.startswith(f"{NAMESPACE}:entity_type/")
        else entity_id,
        (),
    )
    path = entity_id.removeprefix(f"{NAMESPACE}:entity_type/").split(":", 1)[-1]
    for registry in registries:
        wanted = WIKI_KIND.get(registry, ())
        rows = tuple(row for row in all_rows if row.kind in wanted)
        names = {row.display_name for row in rows}
        if len(names) == 1:
            return rows[0]
        path_matches = [
            row for row in rows if row.display_name.casefold().replace(" ", "_") == path
        ]
        if len({row.display_name for row in path_matches}) == 1:
            return path_matches[0]
        exact_kind = [row for row in rows if row.kind == registry]
        if len({row.display_name for row in exact_kind}) == 1:
            return exact_kind[0]

    # Nothing matched on kind. Narrowing is a *disambiguator*, so when there
    # is exactly one display name to choose from there is nothing left for it
    # to do, and refusing the row protects against a collision that does not
    # exist. The rows this reaches are the ones where the wiki's own `Type`
    # disagrees with the registry mcmeta filed the ID under. Measured on
    # 2026-08-31 there are 7 of them, and every one is a wiki classification
    # quirk rather than a real second meaning: `block_display`,
    # `item_display`, `text_display` and `interaction` are `entity_type` IDs
    # the wiki types `block`; `item` is typed `env`; `mannequin` and `marker`
    # the wiki leaves unclassified.
    #
    # The guard is the count, and it is doing real work. On the same
    # measurement 8 other IDs reach this point with more than one name, and
    # every one is a genuine ambiguity that must stay unresolved:
    # `minecraft:potion` carries 26 rows (every brewed potion shares the one
    # registry ID), `leather_leggings` answers to both `Leather Pants` and
    # `Leather Tunic`, and `weakness` shares its ID with the joke effect
    # `Sharing`. Picking one of those would be the wrong-answer failure this
    # module ranks below a missing one, so they fall through to `None` and
    # the caller reports them.
    names = {row.display_name for row in all_rows}
    if len(names) == 1:
        return all_rows[0]
    if not all_rows:
        return None

    # Several names for one ID. Giving up here is not free: without a row the
    # entity has no page, so it has no `wikiUrl`, and decision D1 then refuses
    # to build it the moment any wiki-authored section attaches to it. Two
    # signals pick a row safely, and anything they do not settle stays
    # unresolved and reported.
    #
    # First, a display name that normalises back to the registry path is the
    # ID's own name and cannot be anything else. `minecraft:weakness` carries
    # rows for `Weakness` and for the joke effect `Sharing`; `minecraft:potion`
    # carries 26, one per brewed potion, of which exactly one is `Potion`.
    for row in all_rows:
        if row.display_name.casefold().replace(" ", "_") == path:
            return row

    # Second, a name that maps back to exactly one registry ID is a
    # trustworthy label for it, and a name shared with another ID is not.
    # `minecraft:leather_leggings` is the case that needs this: the wiki calls
    # it `Leather Pants` on one page and `Leather Tunic` on another, and
    # `Leather Tunic` is also what it calls `minecraft:leather_chestplate`. So
    # `Leather Pants` is the only one of the two that names this item alone.
    # Only an outright single winner is accepted; two equally good names are
    # a genuine ambiguity, not a coin to toss.
    unambiguous = [
        row
        for row in all_rows
        if len({other.registry_id for other in join_table.candidates(row.display_name)}) == 1
    ]
    if len({row.display_name for row in unambiguous}) == 1:
        return unambiguous[0]
    return None


def _disambiguate_ids(
    name: str,
    ids: set[str],
    rows: Sequence[ResourceLocation],
    by_id: Mapping[str, object],
    *,
    registry: str,
) -> set[str]:
    """Disambiguate multiple candidate registry IDs for a display name.

    1. Filter candidates against `by_id` (accounting for entity_type prefixing).
       This safely removes joke/April Fools items such as `minecraft:snektato`
       sharing the display name 'Potato' with `minecraft:potato`.
    2. Prefer candidates whose wiki page title matches `name` exactly.
    3. Prefer candidates whose registry path matches the lookup name slug exactly.
    """
    if len(ids) <= 1:
        return ids

    def in_by_id(target: str) -> bool:
        if target in by_id:
            return True
        if registry == "entity_type":
            path = target.split(":", 1)[-1]
            if f"{NAMESPACE}:entity_type/{path}" in by_id:
                return True
        return False

    valid_ids = {i for i in ids if in_by_id(i)}
    if len(valid_ids) == 1:
        return valid_ids

    candidates = valid_ids if valid_ids else ids
    on_page = {
        row.registry_id for row in rows if row.page == name and row.registry_id in candidates
    }
    if len(on_page) == 1:
        return on_page

    slug = name.casefold().replace(" ", "_")
    exact = {i for i in candidates if i.split(":", 1)[-1] == slug}
    if len(exact) == 1:
        return exact

    return candidates


def _maybe_ref(
    name: str, registry: str, join_table: JoinTable, by_id: Mapping[str, object]
) -> EntityRef | None:
    """Return an `EntityRef` for `name` under `registry`, or `None` when it cannot resolve.

    Used for a *nested* cross-reference inside a section -- `item_ref`,
    `ref` on an `ItemAmount` -- where an unresolved name is expected,
    ordinary data (the schema's own `name`/`ref` pattern) rather than a gap
    worth a `MergeReport.unplaced` entry of its own. The row-level miss that
    matters is already reported at the point the whole row was resolved onto
    an entity; a reference inside it that cannot resolve just stays a name.
    """
    rows = _wiki_rows(name, registry, join_table)
    ids = {row.registry_id for row in rows}
    if len(ids) > 1:
        ids = _disambiguate_ids(name, ids, rows, by_id, registry=registry)
    if len(ids) != 1:
        return None
    target = next(iter(ids))
    if registry == "entity_type":
        path = target.split(":", 1)[-1]
        qualified = f"{NAMESPACE}:entity_type/{path}"
        if qualified in by_id:
            target = qualified
    if target not in by_id:
        return None
    return EntityRef(id=target, name=name)


# How a Causes row's qualifier spells the potion variant the row means, in the
# display names the `potion` registry entities already carry. The wiki writes
# `{{ItemLink|Potion of Swiftness}} (extended)` and `... II` where the registry
# writes `Potion of Swiftness (Long)` and `Potion of Swiftness (Strong)`.
_POTION_VARIANT_SUFFIXES: Mapping[str | None, str] = {
    None: "",
    "(extended)": " (Long)",
    "II": " (Strong)",
    "IV": " (Strong)",
}

_POTION_NAME_PREFIX = "Potion of "


def _potion_variant_ref(
    name: str, qualifier: str | None, by_id: Mapping[str, object]
) -> EntityRef | None:
    """Return the specific `minecraft:potion/<path>` entity a Causes row names.

    The join table resolves every "Potion of X" name to `minecraft:potion`, the
    generic potion *item*, because that is the registry entry the wiki page maps
    to. That makes all 45 potion rows of the 26.2 build link to the same page and
    carry a name their target does not match, which is the dead end Decision 13
    exists to prevent. The 46 potion entities already carry the exact display
    names this needs, so matching on the name plus the row's own qualifier
    resolves the variant without re-deriving a registry path here.

    Returns `None` for anything that is not a base potion row -- splash,
    lingering, and tipped arrows have no per-variant entity to target, and
    `pipeline.obtain.brewing` documents why their generic item is the right
    reference.
    """
    if not name.startswith(_POTION_NAME_PREFIX):
        return None
    suffix = _POTION_VARIANT_SUFFIXES.get(qualifier)
    if suffix is None:
        return None
    display = f"{name}{suffix}"
    for entity_id, draft in by_id.items():
        if not entity_id.startswith(f"{NAMESPACE}:potion/"):
            continue
        if getattr(draft, "name", None) == display:
            return EntityRef(id=entity_id, name=display)
    return None


def _any_registry_ref(
    name: str, join_table: JoinTable, by_id: Mapping[str, object]
) -> EntityRef | None:
    """Return the first `EntityRef` any registry resolves `name` to.

    A Causes row names its cause in prose, so the registry it belongs to is not
    known ahead of the lookup: `Beacon` is a block, `Golden Apple` an item, and
    `Illusioner` an entity type. Tries the registries in the order a reader would
    expect a name to mean, and the title-cased spelling as well, because the wiki
    writes `Suspicious stew` alongside `Suspicious Stew`.
    """
    for candidate_name in (name, name.title()):
        for registry in ("item", "block", "entity_type", "enchantment", "mob_effect"):
            ref = _maybe_ref(candidate_name, registry, join_table, by_id)
            if ref is not None:
                return ref
    return None


def _resolve_forward(
    name: str,
    registry: str,
    join_table: JoinTable,
    by_id: Mapping[str, object],
    *,
    table: str,
    unplaced: list[UnplacedRow],
) -> str | None:
    """Return the one entity ID `name` resolves to under `registry`, or report and return `None`.

    The forward-resolution helper the module docstring's join-direction
    section describes: walked once per key of a display-name-keyed Tier B
    index, never the other way around.
    """
    rows = _wiki_rows(name, registry, join_table)
    ids = {row.registry_id for row in rows}
    if not ids:
        unplaced.append(
            UnplacedRow(
                table=table, subject=name, reason="no Tier B display name resolves to a registry ID"
            )
        )
        return None
    if len(ids) > 1:
        ids = _disambiguate_ids(name, ids, rows, by_id, registry=registry)
    if len(ids) > 1:
        unplaced.append(
            UnplacedRow(
                table=table,
                subject=name,
                reason=f"ambiguous display name, candidates: {', '.join(sorted(ids))}",
            )
        )
        return None
    target = next(iter(ids))
    if registry == "entity_type":
        path = target.split(":", 1)[-1]
        qualified = f"{NAMESPACE}:entity_type/{path}"
        if qualified in by_id:
            target = qualified
    if target not in by_id:
        unplaced.append(
            UnplacedRow(
                table=table,
                subject=name,
                reason=f"resolved to {target}, which this build does not enumerate as an entity",
            )
        )
        return None
    return target


def _resolve_entity_icon(
    entity_id: str,
    registries_of_id: Sequence[str],
    join_table: JoinTable,
    sprite_index: SpriteIndex,
) -> tuple[str | None, tuple[tuple[str, str, str], ...], bool]:
    """Return `(icon_key, routes_tried, exempt)` for `entity_id`.

    Tries `resolve_icon` against every registry `entity_id` belongs to, in
    the same kind-precedence order enumeration already used, and stops at the
    first family that resolves. `icon_key` is `"<family>:<sprite_id>"` --
    Phase 3's future atlas packer has not been built yet, so there is no
    atlas coordinate map key to write; this is a stable, reversible key back
    into `sprite_index` that a later emit stage can look up without this
    module inventing the atlas format early. `exempt` is set when every
    registry `entity_id` belongs to has `has_icons=False` -- today, only
    when the ID is an enchantment and nothing else -- so `enchantment` never
    becomes 43 entries of `MergeReport.missing_icons`, matching `reconcile`'s
    own exemption.
    """
    raw_id = (
        f"{NAMESPACE}:{entity_id.removeprefix(f'{NAMESPACE}:entity_type/')}"
        if entity_id.startswith(f"{NAMESPACE}:entity_type/")
        else entity_id
    )
    tried_any_iconed_registry = False
    all_routes: list[tuple[str, str, str]] = []
    for registry in registries_of_id:
        rule = ICON_RULES.get(registry)
        if rule is None or not rule.has_icons:
            continue
        tried_any_iconed_registry = True
        resolution = resolve_icon(raw_id, rule, join_table, sprite_index)
        if resolution.sprite is not None:
            return f"{resolution.matched_family}:{resolution.sprite.sprite_id}", (), False
        all_routes.extend(
            (registry, family, sprite_id) for family, sprite_id in resolution.routes_tried
        )
    return None, tuple(all_routes), not tried_any_iconed_registry


# --- Section conversion: enrich-stage models to the closed `Entity` sections ---


def _convert_measure(value: enrich_infobox.Measure) -> Measure:
    return Measure(minimum=float(value.minimum), maximum=float(value.maximum))


def _convert_labelled_value(
    value: enrich_infobox.HealthValue | enrich_infobox.ArmorValue,
) -> LabelledValue:
    return LabelledValue(labels=value.labels, value=_convert_measure(value.value))


def _convert_labelled_text(value: enrich_infobox.LabelledText) -> LabelledText:
    return LabelledText(labels=value.labels, text=value.text)


def _convert_damage(value: enrich_infobox.DamageValue) -> DamageValue:
    return DamageValue(
        labels=value.labels,
        difficulties=tuple(difficulty.value for difficulty in value.difficulties),
        value=_convert_measure(value.value),
    )


def _convert_size(value: enrich_infobox.SizeValue) -> SizeValue:
    return SizeValue(labels=value.labels, height=float(value.height), width=float(value.width))


def _statblock_has_content(box: enrich_infobox.EntityInfobox) -> bool:
    """Return whether `box` carries anything `StatBlock` would show.

    `StatBlock` has no field for `usable_items` -- part 1's `entity.py`
    declares only the nine fields `D2` names, and `usable_items` is not one
    of them -- so it is read for nothing here and dropped, the same way every
    other field this section does not declare would be.
    """
    return bool(
        box.health
        or box.damage
        or box.armor
        or box.size
        or box.behavior
        or box.mob_type
        or box.speed
        or box.knockback_resistance
    )


def _build_stat_block(box: enrich_infobox.EntityInfobox) -> StatBlock:
    return StatBlock(
        health=tuple(_convert_labelled_value(item) for item in box.health),
        damage=tuple(_convert_damage(item) for item in box.damage),
        armor=tuple(_convert_labelled_value(item) for item in box.armor),
        size=tuple(_convert_size(item) for item in box.size),
        behavior=tuple(_convert_labelled_text(item) for item in box.behavior),
        mob_type=box.mob_type,
        speed=tuple(_convert_labelled_text(item) for item in box.speed),
        knockback_resistance=tuple(
            _convert_labelled_text(item) for item in box.knockback_resistance
        ),
    )


def _resolve_mob_id(entity_type: str, drafts: Mapping[str, EntityDraft]) -> str:
    """Resolve an entity_type ID to its mob draft key, respecting split IDs."""
    if entity_type in drafts and drafts[entity_type].kind is EntityKind.MOB:
        return entity_type
    path = entity_type.split(":", 1)[-1]
    qualified = f"{NAMESPACE}:entity_type/{path}"
    if qualified in drafts and drafts[qualified].kind is EntityKind.MOB:
        return qualified
    return entity_type


def _convert_ratio(value: enrich_droptable.Ratio) -> Ratio:
    return Ratio(numerator=value.numerator, denominator=value.denominator)


def _convert_looting_drop(value: enrich_droptable.LootingDrop) -> LootingDrop:
    return LootingDrop(
        looting_level=value.looting_level,
        minimum=value.minimum,
        maximum=value.maximum,
        average=_convert_ratio(value.average),
        drop_chance=_convert_ratio(value.drop_chance),
        quantity_text=value.quantity_text,
        distribution=tuple(
            DistributionEntry(count=count, chance=_convert_ratio(chance))
            for count, chance in sorted(value.distribution.items())
        ),
    )


def _convert_drop_entry(
    drop: enrich_droptable.MobDrop, join_table: JoinTable, by_id: Mapping[str, object]
) -> DropEntry:
    return DropEntry(
        item=drop.item,
        item_ref=_maybe_ref(drop.item, "item", join_table, by_id),
        notes=tuple(DropNote(name=note.name, content=note.content) for note in drop.notes),
        by_looting_level=tuple(_convert_looting_drop(level) for level in drop.by_looting_level),
    )


def _convert_item_amount(
    item: enrich_trade.TradeItem, join_table: JoinTable, by_id: Mapping[str, object]
) -> ItemAmount:
    return ItemAmount(
        name=item.item,
        ref=_maybe_ref(item.item, "item", join_table, by_id),
        quantity=IntegerRange(minimum=item.quantity.minimum, maximum=item.quantity.maximum),
        note=item.note_text if item.note_text is not None else item.note,
    )


def _convert_probability(value: enrich_trade.Probability) -> JavaProbability:
    return JavaProbability(text=value.text, low=value.low, high=value.high)


def _convert_trade_entry(
    trade: enrich_trade.WikiTrade,
    join_table: JoinTable,
    by_id: Mapping[str, object],
    *,
    profession_refs: Mapping[str, EntityRef] | None = None,
) -> TradeEntry:
    max_trades = trade.max_trades
    pref = profession_refs.get(trade.profession) if profession_refs else None
    return TradeEntry(
        profession=trade.profession,
        profession_ref=pref,
        level=trade.level,
        wanted=tuple(_convert_item_amount(item, join_table, by_id) for item in trade.wanted),
        given=_convert_item_amount(trade.given, join_table, by_id),
        java_probability=(
            _convert_probability(trade.java_probability)
            if trade.java_probability is not None
            else None
        ),
        max_trades=(
            IntegerRange(minimum=max_trades.minimum, maximum=max_trades.maximum)
            if max_trades is not None
            else None
        ),
        villager_xp=trade.villager_xp,
        price_multiplier=trade.price_multiplier,
    )


# --- Enumeration ----------------------------------------------------------------


def _should_split_entity_type(
    registries: Sequence[str], rows: Sequence[ResourceLocation]
) -> bool:
    """Return True when an ID present in entity_type and other registries should split.

    The wiki's own display names are the evidence: split an ID only when
    the entity_type registry's wiki display names and the other registries'
    wiki display names are disjoint. Leaves block + item pairs alone (they
    share identical names), but splits chicken (Chicken vs Raw Chicken) and
    ender_pearl (Ender Pearl vs Thrown Ender Pearl).
    """
    if "entity_type" not in registries or len(registries) < 2:
        return False
    wanted_entity = WIKI_KIND["entity_type"]
    entity_names = {row.display_name for row in rows if row.kind in wanted_entity}
    other_names = {row.display_name for row in rows if row.kind not in wanted_entity}
    return bool(entity_names and other_names and entity_names.isdisjoint(other_names))


def _registries_of_id(
    registries: Mapping[str, Sequence[str]],
    join_table: JoinTable,
    classification: EntityClassification,
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """Return every path of the six precedence registries, mapped to the registries it sits in.

    Each value lists the registries in the order the merge should try them, so
    `value[0]` is the entity's chosen registry: it decides the `kind` and it
    is the first registry `_own_row` looks for a wiki row under.

    The starting order is `_REGISTRY_PRECEDENCE`, and three adjustments run on
    top of it, in this order, for an ID that sits in more than one registry:

    **First, an ID sitting in `entity_type` and other registries whose wiki
    display names are disjoint is split into two entities.**
    The precedence winner keeps the bare ID (e.g. `minecraft:chicken` for the
    item) and `entity_type` gains a qualified path (e.g.
    `minecraft:entity_type/chicken` for the mob).

    **Second, the registry whose wiki row calls the ID by its own name wins.**
    Precedence alone is a guess about which of two meanings a player wants,
    and the wiki has already answered the question by choosing what to call
    each row.

    **Third, an `entity_type` ID that classifies as `EntityClass.NEITHER`
    is demoted to the bottom of its own list.** This runs after the name
    adjustment and unconditionally overrides whatever it decided, which is
    what makes the demotion a real settlement rather than one more input to a
    tie-break: `pipeline.extract.entity_class.classify_entity_types` already
    proved this ID has no spawn egg and no entity loot table, so nothing the
    wiki calls it changes what it is.

    Raises `NormalizeError` when a registry `_REGISTRY_PRECEDENCE` names is
    missing from `registries`, or when an ID sits in `entity_type` and
    `classification` names nothing for it -- the second is a sign that
    `classification` was built from a different registries payload than the
    one this call was given, which is a caller bug rather than a fact about
    the game.
    """
    per_id: dict[str, list[str]] = {}
    for registry in _REGISTRY_PRECEDENCE:
        ids = registries.get(registry)
        if ids is None:
            raise NormalizeError(
                f"{registry!r} is a registry this merge stage's precedence names, and this "
                f"mcmeta payload does not publish it. The precedence has gone stale against "
                f"the game."
            )
        for path in ids:
            per_id.setdefault(path, []).append(registry)

    ordered: dict[str, tuple[str, ...]] = {}
    split_ids: list[str] = []
    for path, regs in per_id.items():
        if "entity_type" in regs:
            entity_class = classification.by_path.get(path)
            if entity_class is None:
                raise NormalizeError(
                    f"{path!r} sits in the entity_type registry, and the entity classification "
                    f"this merge was given names nothing for it. The classifier and the "
                    f"registries payload have gone out of sync."
                )

        if len(regs) > 1:
            rows = join_table.by_registry_id.get(f"{NAMESPACE}:{path}", ())
            if _should_split_entity_type(regs, rows):
                split_ids.append(f"{NAMESPACE}:{path}")
                non_entity_regs = [r for r in regs if r != "entity_type"]
                named = _registry_the_wiki_names_the_id_under(path, non_entity_regs, rows)
                if named is not None:
                    non_entity_regs = [named] + [r for r in non_entity_regs if r != named]
                ordered[path] = tuple(non_entity_regs)
                ordered[f"entity_type/{path}"] = ("entity_type",)
                continue

            named = _registry_the_wiki_names_the_id_under(path, regs, rows)
            if named is not None:
                regs = [named] + [registry for registry in regs if registry != named]

        if "entity_type" in regs and entity_class is EntityClass.NEITHER and len(regs) > 1:
            regs = [registry for registry in regs if registry != "entity_type"] + [
                "entity_type"
            ]

        ordered[path] = tuple(regs)
    return ordered, tuple(sorted(split_ids))


def _registry_the_wiki_names_the_id_under(
    path: str, registries: Sequence[str], rows: Sequence[ResourceLocation]
) -> str | None:
    """Return the registry whose wiki row calls `path` by its own name, or `None`.

    "By its own name" means the display name normalises back to the registry
    path: `Ender Pearl` gives `ender_pearl`, `Thrown Ender Pearl` does not.
    A row that names the ID exactly is the wiki agreeing that this registry is
    what the ID primarily *is*, which is a better signal than any ordering
    this module could hard-code.

    Registries are walked in the order given, so an equally good match never
    displaces the one precedence already preferred.
    """
    for registry in registries:
        wanted = WIKI_KIND.get(registry, ())
        for row in rows:
            if row.kind in wanted and row.display_name.casefold().replace(" ", "_") == path:
                return registry
    return None


def _effect_link(
    effect_id: str, display_names: Mapping[str, str], by_id: Mapping[str, object]
) -> tuple[str, EntityRef | None]:
    """Return the display name of one status effect, and a ref to it when this build has one.

    The `name`/`ref` pattern, reached from the other direction than
    `_maybe_ref`. A consume effect names its target by registry ID rather than
    by wiki display name -- `minecraft:hunger`, straight out of Tier A -- so
    there is no join to walk and nothing to report as unplaced. The name comes
    from the draft set when the effect is an entity of this build, and falls
    back to the prettified registry path when it is not, which keeps the row
    readable rather than printing a raw ID at a reader.
    """
    if effect_id in by_id:
        name = display_names.get(effect_id) or _fallback_name(effect_id.split(":", 1)[-1])
        return name, EntityRef(id=effect_id, name=name)
    return _fallback_name(effect_id.split(":", 1)[-1]), None


def _build_food_info(
    facts: FoodFacts, display_names: Mapping[str, str], by_id: Mapping[str, object]
) -> FoodInfo | None:
    """Return the `FoodInfo` of one item, or `None` when it has nothing to show.

    Four of the five consume-effect kinds land somewhere in the section. The
    fifth, `PLAY_SOUND`, lands nowhere: a sound is not something a page can
    draw, and the extract parses it only so that a genuinely unknown sixth kind
    still raises rather than passing as a sound. `ominous_bottle` is the one
    item in 26.2 whose entire consume behaviour is a sound and which restores
    no hunger, so it is also the one item this function answers `None` for.
    """
    effects: list[FoodEffect] = []
    removes: list[EffectLink] = []
    clears_all_effects = False
    teleports_randomly = False

    for entry in facts.effects:
        if entry.kind is ConsumeEffectKind.APPLY_EFFECTS:
            for applied in entry.applied:
                name, ref = _effect_link(applied.effect, display_names, by_id)
                effects.append(
                    FoodEffect(
                        name=name,
                        ref=ref,
                        duration_ticks=applied.duration_ticks,
                        # The component counts from 0 and the screen counts
                        # from 1: amplifier 1 is the level a player reads as II.
                        level=applied.amplifier + 1,
                        probability=applied.probability,
                    )
                )
        elif entry.kind is ConsumeEffectKind.REMOVE_EFFECTS:
            for removed in entry.removed:
                name, ref = _effect_link(removed, display_names, by_id)
                removes.append(EffectLink(name=name, ref=ref))
        elif entry.kind is ConsumeEffectKind.CLEAR_ALL_EFFECTS:
            clears_all_effects = True
        elif entry.kind is ConsumeEffectKind.TELEPORT_RANDOMLY:
            teleports_randomly = True

    if (
        facts.nutrition is None
        and not effects
        and not removes
        and not clears_all_effects
        and not teleports_randomly
    ):
        return None

    return FoodInfo(
        nutrition=facts.nutrition,
        saturation=facts.saturation,
        can_always_eat=facts.can_always_eat,
        effects=tuple(effects),
        removes=tuple(removes),
        clears_all_effects=clears_all_effects,
        teleports_randomly=teleports_randomly,
    )


def block_drops_from_producers(
    producers: Iterable[Producer],
) -> dict[str, tuple[HarvestDrop, ...]]:
    """Return what each block drops, keyed by the block's registry ID.

    `pipeline.obtain.loot` has already read every block loot table into
    `BLOCK_DROP` producers, so this is a re-key of work that exists rather than
    a second read of the same JSON: a producer answers "what makes this item",
    and `HarvestInfo` needs the transpose, "what does this block make". The one
    input of a `BLOCK_DROP` producer is the block itself, which is the key.

    Drop gates (`silk_touch`, `shears`) are read from `Producer.note` against
    `loot.SILK_TOUCH_NOTE` and `loot.SHEARS_NOTE` rather than re-derived, for
    the reason that constant's own comment gives: the gate is decided once,
    while the loot table is being walked, and any second opinion formed here
    could disagree with the obtain tree drawn from the same producers on the
    same page.

    Duplicates are dropped. One block can reach the same `(item, count,
    gate)` leaf down more than one branch of an `alternatives` tree --
    every leaf-and-sapling table does -- and a drops row that printed the same
    item twice would be reporting the loot table's shape, not the block's
    drops. Order is otherwise the order the tables were walked in, which is the
    order the entries appear in the file.
    """
    drops: dict[str, list[HarvestDrop]] = {}
    for producer in producers:
        if producer.method is not ObtainMethod.BLOCK_DROP or not producer.inputs:
            continue
        block_id = producer.inputs[0].item
        if block_id is None:
            continue
        gate: HarvestGate | None = None
        if producer.note == SILK_TOUCH_NOTE:
            gate = "silk_touch"
        elif producer.note == SHEARS_NOTE:
            gate = "shears"
        drop = HarvestDrop(
            id=producer.output.item,
            count=producer.output.count,
            gate=gate,
        )
        seen = drops.setdefault(block_id, [])
        if drop not in seen:
            seen.append(drop)
    return {block_id: tuple(items) for block_id, items in drops.items()}


def merge_entities(
    *,
    registries: Mapping[str, Sequence[str]],
    advancement_ids: Sequence[str],
    join_table: JoinTable,
    sprite_index: SpriteIndex,
    infobox_report: enrich_infobox.InfoboxReport,
    spawn_index: enrich_spawn_table.SpawnIndex,
    drop_index: enrich_droptable.DropIndex,
    trade_index: enrich_trade.TradeIndex,
    advancement_tree: enrich_advancement.AdvancementTree,
    extract_report: ExtractReport,
    curated: CuratedData,
    entity_classification: EntityClassification,
    breeding_index: enrich_breeding.BreedingIndex | None = None,
    food_index: Mapping[str, FoodFacts] | None = None,
    harvest_index: Mapping[str, BlockHarvest] | None = None,
    block_drops: Mapping[str, Sequence[HarvestDrop]] | None = None,
    effect_index: enrich_effect.EffectIndex | None = None,
    generation_index: Mapping[str, BlockGeneration] | None = None,
    enchant_index: EnchantIndex | None = None,
    profession_index: ProfessionIndex | None = None,
    profession_infoboxes: Mapping[str, ProfessionInfobox] | None = None,
    structure_index: StructureIndex | None = None,
    feature_place_index: FeaturePlaceIndex | None = None,
    biome_index: BiomeIndex | None = None,
    noise_placements: Mapping[str, Sequence[Any]] | None = None,
    curated_chests: Mapping[str, ChestSource] | None = None,
    loot_producers: Sequence[Producer] | None = None,
) -> MergeResult:
    """Return the merged `Entity` set of one build, and the report of how it was built.

    `registries` is the full mcmeta registries payload, matching `pipeline.
    normalize.reconcile.reconcile`'s own parameter of the same name.
    `advancement_ids` is `pipeline.extract.advancement.extract_advancement_ids`'s
    output. `entity_classification` is `pipeline.extract.entity_class.
    classify_entity_types`'s output, built from the same mcmeta payloads as
    `registries` -- the module docstring's classification section names the
    three-way rule it drives. This function takes no `ProducerIndex`: the
    obtain graph is no longer part of what a merge produces, and `pipeline.
    emit.write.emit_build` reads it directly instead -- see `pipeline.emit.
    obtain`'s module docstring for why the graph moved and `pipeline.obtain.
    tree`'s own docstring for what this stage no longer needs to know about
    it. `registries["potion"]` -- present or absent; see the potion
    enumeration section below -- drives the one entity kind this module
    enumerates outside the six-registry union: every potion registers as
    `minecraft:potion/<path>`, per this task's own decision that the `/`
    namespacing is required, not cosmetic, because fifteen potion paths
    collide with a `mob_effect` path of the same name. Every other argument
    is the Tier B index (or Tier C `CuratedData`) the module docstring names
    as that section's source.

    Raises `NormalizeError` for a shape fault: an empty `registries` mapping,
    an empty `join_table`, an empty `sprite_index`, an empty `entity_
    classification`, a registry this module's precedence names that
    `registries` does not publish, or an `entity_type` ID that `entity_
    classification` names nothing for. Never raises for a per-entity gap --
    see the module docstring's closing section.
    """
    if not registries:
        raise NormalizeError(
            "merge_entities was given no mcmeta registries. An empty registries payload is a "
            "failed scrape, not a version of Minecraft with nothing to merge."
        )
    if not join_table.entries:
        raise NormalizeError(
            "merge_entities was given a join table with no entries. An empty resource_location "
            "read is a failed scrape, not a wiki with no pages."
        )
    if not sprite_index.entries:
        raise NormalizeError(
            "merge_entities was given a sprite index with no entries. An empty spritefile read "
            "is a failed scrape, not a wiki with no sprites."
        )
    if not entity_classification.by_path:
        raise NormalizeError(
            "merge_entities was given an entity classification with no paths. An empty "
            "classification is a failed extract, not a version of Minecraft with no entity "
            "types to classify."
        )

    per_id, split_ids = _registries_of_id(registries, join_table, entity_classification)

    multi_registry: list[MultiRegistryId] = []
    undecided_entity_types: list[UndecidedEntityType] = []
    unplaced: list[UnplacedRow] = []
    missing_icons: list[MissingIconEntity] = []
    missing_blurbs: list[MissingBlurb] = []

    blurbs = extract_report.blurbs()
    drafts: dict[str, EntityDraft] = {}
    # The display names the wiki reuses across several ids, computed once before
    # the loop because a collision is only visible across the whole table.
    reused_names = names_the_wiki_reuses(join_table)
    # The display name each ID settled on, collected as the loop resolves it.
    # The food section reads it to name an effect it links to, and it cannot
    # ask the draft: `EntityDraft` deliberately exposes no name accessor, and
    # the value is known here anyway.
    display_names: dict[str, str] = {}
    entity_registries: dict[str, tuple[str, ...]] = {}
    entity_type_kind_counts: dict[EntityKind, int] = {}

    for path, regs in per_id.items():
        entity_id = f"{NAMESPACE}:{path}"
        raw_path = path.removeprefix("entity_type/")
        chosen_registry = regs[0]
        entity_class = (
            entity_classification.by_path.get(raw_path) if "entity_type" in regs else None
        )
        if chosen_registry == "entity_type":
            if entity_class is None:
                # `_registries_of_id` already raised for this shape, so this
                # branch is unreachable in practice; the guard stays because
                # it is what lets mypy narrow `entity_class` to `EntityClass`
                # for `_entity_type_kind` below rather than `EntityClass | None`.
                raise NormalizeError(
                    f"{entity_id!r} chose the entity_type registry with no classification. "
                    f"The classifier and the registries payload have gone out of sync."
                )
            kind = _entity_type_kind(entity_class)
        else:
            kind = _REGISTRY_KIND[chosen_registry]
        override = curated.overrides.get(entity_id)
        if override is not None and override.kind is not None:
            # See the module docstring's section on the curated `kind`
            # override for why this happens before construction rather than
            # through `EntityDraft.set`.
            kind = override.kind
        entity_registries[entity_id] = regs
        if len(regs) > 1:
            multi_registry.append(MultiRegistryId(id=entity_id, registries=regs, kind=kind))
        if entity_class is EntityClass.LOOT_TABLE_ONLY:
            undecided_entity_types.append(UndecidedEntityType(id=entity_id, kind=kind))
        if entity_class is not None and chosen_registry == "entity_type":
            entity_type_kind_counts[kind] = entity_type_kind_counts.get(kind, 0) + 1

        fallback_name = _fallback_name(raw_path)
        draft = EntityDraft(id=entity_id, kind=kind, name=fallback_name, tier=SourceTier.A)

        row = _own_row(entity_id, regs, join_table)
        resolved_name = fallback_name
        if row is not None:
            # The wiki's display name is the in-game stack name, which one family
            # shares on purpose. Where it does, its page title is the real name.
            # See `names_the_wiki_reuses`.
            resolved_name = row.page if row.display_name in reused_names else row.display_name
            draft.set("name", resolved_name, SourceTier.B)
            draft.set("wikiUrl", row.wiki_url, SourceTier.B)
            blurb = blurbs.get(row.page)
            if blurb is not None:
                draft.set("blurb", blurb, SourceTier.B)
            else:
                missing_blurbs.append(MissingBlurb(id=entity_id, page=row.page))

            box = infobox_report.by_page.get(row.page)
            if box is not None and _statblock_has_content(box):
                draft.add_section(_build_stat_block(box), SourceTier.B)

        override = curated.overrides.get(entity_id)
        if override is not None and override.icon is not None:
            draft.set("icon", override.icon, SourceTier.C)
        else:
            icon_key, routes, exempt = _resolve_entity_icon(
                entity_id, regs, join_table, sprite_index
            )
            if icon_key is not None:
                draft.set("icon", icon_key, SourceTier.B)
            elif not exempt:
                missing_icons.append(MissingIconEntity(id=entity_id, routes_tried=routes))

        display_names[entity_id] = resolved_name

        curated_aliases = curated.aliases.get(entity_id, ())
        for alias, strength in generate_aliases(
            entity_id=entity_id, kind=kind, name=resolved_name, curated=curated_aliases
        ):
            alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
            draft.add_aliases([alias], alias_tier)

        drafts[entity_id] = draft

    # --- Advancements, enumerated separately -------------------------------

    for internal_id in advancement_ids:
        entity_id = f"{NAMESPACE}:{internal_id}"
        kind = EntityKind.ADVANCEMENT
        override = curated.overrides.get(entity_id)
        if override is not None and override.kind is not None:
            kind = override.kind

        fallback_name = _fallback_name(internal_id)
        draft = EntityDraft(id=entity_id, kind=kind, name=fallback_name, tier=SourceTier.A)

        wiki_advancement = advancement_tree.by_id.get(internal_id)
        resolved_name = fallback_name
        if wiki_advancement is not None:
            resolved_name = wiki_advancement.title
            draft.set("name", wiki_advancement.title, SourceTier.B)
            draft.set("wikiUrl", wiki_advancement.wiki_url, SourceTier.B)

            parent_ref: EntityRef | None = None
            if wiki_advancement.parent_id is not None:
                parent = advancement_tree.by_id.get(wiki_advancement.parent_id)
                if parent is not None:
                    parent_ref = EntityRef(
                        id=f"{NAMESPACE}:{wiki_advancement.parent_id}", name=parent.title
                    )
            children: list[EntityRef] = []
            for child_id in advancement_tree.children.get(internal_id, ()):
                child = advancement_tree.by_id.get(child_id)
                if child is not None:
                    children.append(EntityRef(id=f"{NAMESPACE}:{child_id}", name=child.title))

            draft.add_section(
                AdvancementInfo(
                    internal_id=wiki_advancement.internal_id,
                    title=wiki_advancement.title,
                    description=wiki_advancement.description,
                    game_description=wiki_advancement.game_description,
                    parent=parent_ref,
                    parent_title=wiki_advancement.parent_title,
                    children=tuple(children),
                    experience=wiki_advancement.experience,
                    reward=wiki_advancement.reward,
                    background=wiki_advancement.background,
                ),
                SourceTier.B,
            )

        if override is not None and override.icon is not None:
            draft.set("icon", override.icon, SourceTier.C)
        elif wiki_advancement is not None and wiki_advancement.icon is not None:
            resolution = resolve_display_name_icon(
                wiki_advancement.icon, join_table, sprite_index
            )
            if resolution.sprite is not None:
                draft.set(
                    "icon",
                    f"{resolution.matched_family}:{resolution.sprite.sprite_id}",
                    SourceTier.B,
                )
            else:
                adv_routes = tuple(
                    ("advancement", family, sprite_id)
                    for family, sprite_id in resolution.routes_tried
                )
                missing_icons.append(MissingIconEntity(id=entity_id, routes_tried=adv_routes))
        else:
            missing_icons.append(
                MissingIconEntity(
                    id=entity_id,
                    routes_tried=(("advancement", "none", "none"),),
                )
            )

        curated_aliases = curated.aliases.get(entity_id, ())
        for alias, strength in generate_aliases(
            entity_id=entity_id, kind=kind, name=resolved_name, curated=curated_aliases
        ):
            alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
            draft.add_aliases([alias], alias_tier)

        drafts[entity_id] = draft

    # --- Potions, enumerated separately -------------------------------------
    #
    # Every potion shares one mcmeta registry ID, `minecraft:potion`, so
    # `_registries_of_id`'s per-path enumeration never sees a "potion"
    # registry to walk -- these 46 IDs are not members of any of the six
    # `_REGISTRY_PRECEDENCE` registries at all, and enumerate here the same
    # way advancements do, from a flat list rather than a registry union.
    # `registries.get("potion", ())` rather than a required key: unlike the
    # six precedence registries, a build with no potion registry loses one
    # entity kind, not the ability to resolve which registry an ID belongs
    # to, so there is nothing here for a missing key to break silently.
    for path in registries.get("potion", ()):
        entity_id = POTION_ID_TEMPLATE.format(path=path)
        kind = EntityKind.ITEM
        override = curated.overrides.get(entity_id)
        if override is not None and override.kind is not None:
            kind = override.kind

        resolved_name = _potion_name(path)
        draft = EntityDraft(id=entity_id, kind=kind, name=resolved_name, tier=SourceTier.A)

        # Only a non-prefixed path may have a page at all -- see the module
        # docstring's note above `_POTION_PAGE_TITLES` for why a `long_`/
        # `strong_` path never does.
        title = _POTION_PAGE_TITLES.get(path)
        if title is not None:
            row = next(
                (
                    entry
                    for entry in join_table.entries
                    if entry.registry_id == f"{NAMESPACE}:potion" and entry.page == title
                ),
                None,
            )
            if row is not None:
                draft.set("wikiUrl", row.wiki_url, SourceTier.B)
                blurb = blurbs.get(row.page)
                if blurb is not None:
                    draft.set("blurb", blurb, SourceTier.B)
                else:
                    missing_blurbs.append(MissingBlurb(id=entity_id, page=row.page))

        curated_aliases = curated.aliases.get(entity_id, ())
        for alias, strength in generate_aliases(
            entity_id=entity_id, kind=kind, name=resolved_name, curated=curated_aliases
        ):
            alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
            draft.add_aliases([alias], alias_tier)

        drafts[entity_id] = draft

    # --- Villager Professions, enumerated separately ------------------------
    #
    # The 13 villager professions known to the trade index enumerate here,
    # mirroring potions and advancements.
    if profession_index is None:
        profession_index = extract_professions(
            registries.get("villager_profession", ()),
            trade_index.by_profession.keys(),
        )

    profession_refs = {
        entry.trade_name: EntityRef(id=entry.id, name=entry.name)
        for entry in profession_index.entries
    }

    # The wandering trader is not a villager profession -- the `villager_
    # profession` registry does not list it, which is why its 97 trades attach
    # to the mob page it already has rather than to a profession entity of its
    # own. It is still one of the seller names the `trade` bucket groups by, so
    # it still heads a group on every item page that sells what it sells. Left
    # out of this map it was the one heading among fourteen that stayed dead
    # text while every sibling became a link, which is exactly the fault the
    # Phase 6c lint bullet exists to catch. `professionRef` names the seller a
    # trade group belongs to, and for this group that seller is a mob.
    if WANDERING_TRADER_ID in drafts:
        profession_refs[WANDERING_TRADER_NAME] = EntityRef(
            id=WANDERING_TRADER_ID, name=drafts[WANDERING_TRADER_ID].name
        )

    for prof_entry in profession_index.entries:
        entity_id = prof_entry.id
        kind = EntityKind.PROFESSION
        override = curated.overrides.get(entity_id)
        if override is not None and override.kind is not None:
            kind = override.kind

        draft = EntityDraft(
            id=entity_id, kind=kind, name=prof_entry.name, tier=SourceTier.A
        )
        draft.set("name", prof_entry.name, SourceTier.B)
        wiki_page = prof_entry.page_title.replace(" ", "_")
        draft.set("wikiUrl", f"https://minecraft.wiki/w/{wiki_page}", SourceTier.B)

        blurb = blurbs.get(prof_entry.page_title)
        if blurb is not None:
            draft.set("blurb", blurb, SourceTier.B)
        else:
            missing_blurbs.append(MissingBlurb(id=entity_id, page=prof_entry.page_title))

        if override is not None and override.icon is not None:
            draft.set("icon", override.icon, SourceTier.C)
        else:
            icon_key, routes, exempt = _resolve_entity_icon(
                entity_id, ("profession",), join_table, sprite_index
            )
            if icon_key is not None:
                draft.set("icon", icon_key, SourceTier.B)
            else:
                missing_icons.append(MissingIconEntity(id=entity_id, routes_tried=routes))

        prof_box = profession_infoboxes.get(prof_entry.page_title) if profession_infoboxes else None
        workstation_ref: EntityRef | None = None
        if prof_box is not None and prof_box.workstation:
            workstation_ref = _maybe_ref(
                prof_box.workstation, "block", join_table, drafts
            ) or _maybe_ref(prof_box.workstation, "item", join_table, drafts)

        prof_trades = trade_index.by_profession.get(prof_entry.trade_name, ())
        draft.add_section(
            ProfessionInfo(workstation=workstation_ref, trade_count=len(prof_trades)),
            SourceTier.B,
        )

        if prof_trades:
            converted_trades = tuple(
                _convert_trade_entry(t, join_table, drafts, profession_refs=profession_refs)
                for t in prof_trades
            )
            draft.add_section(TradeTable(trades=converted_trades), SourceTier.B)

        curated_aliases = curated.aliases.get(entity_id, ())
        ws_name = (
            workstation_ref.name
            if workstation_ref is not None
            else (prof_box.workstation if prof_box else None)
        )
        for alias, strength in generate_aliases(
            entity_id=entity_id,
            kind=kind,
            name=prof_entry.name,
            curated=curated_aliases,
            workstation=ws_name,
        ):
            alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
            draft.add_aliases([alias], alias_tier)

        drafts[entity_id] = draft

    # --- Structures, enumerated separately ----------------------------------
    #
    # The 34 structures from the `worldgen/structure` registry enumerate here,
    # mirroring villager professions, potions, and advancements.
    structures_by_biome: dict[str, list[EntityRef]] = {}
    if structure_index is not None:
        resolved_pages = resolve_structure_pages(structure_index, join_table)
        structure_display_names = {sid: name for sid, (name, _) in resolved_pages.items()}
        structure_wiki_pages = {sid: page for sid, (_, page) in resolved_pages.items()}

        producers_by_table: dict[str, list[Producer]] = {}
        if loot_producers:
            for p in loot_producers:
                producers_by_table.setdefault(p.source_id, []).append(p)

        containers_by_structure = by_structure(curated_chests) if curated_chests else {}

        for sid, struct_entry in structure_index.structures.items():
            entity_id = sid
            kind = EntityKind.STRUCTURE
            override = curated.overrides.get(entity_id)
            if override is not None and override.kind is not None:
                kind = override.kind

            display_name = structure_display_names[sid]
            page = structure_wiki_pages[sid]

            draft = EntityDraft(id=entity_id, kind=kind, name=display_name, tier=SourceTier.A)
            draft.set("name", display_name, SourceTier.B)
            wiki_page = page.replace(" ", "_")
            draft.set(
                "wikiUrl",
                f"https://minecraft.wiki/{wiki_page}"
                if wiki_page.startswith("w/")
                else f"https://minecraft.wiki/w/{wiki_page}",
                SourceTier.B,
            )

            blurb = blurbs.get(page)
            if blurb is not None:
                draft.set("blurb", blurb, SourceTier.B)
            else:
                missing_blurbs.append(MissingBlurb(id=entity_id, page=page))

            # A structure resolves no icon of its own, and `ICON_RULES` still
            # says so with `has_icons=False`: the wiki publishes no structure
            # sprite family, so there is nothing for the id or display-name
            # routes to find and the registry stays an exemption in the icon
            # report. That record is about what the wiki publishes and it is
            # still correct.
            #
            # What a structure can carry is a curated borrowing, and the Tier C
            # override is the mechanism that already exists for it. Each of the
            # 34 names one characteristic block or item whose sprite is in the
            # atlas anyway, so a structure row is recognisable in a mixed
            # suggestion list without a single new sprite being fetched. It
            # states a kind and a place rather than an identity. A structure
            # with no override stays iconless rather than borrowing something
            # arbitrary, which is why this reads the override and never falls
            # back to a guess.
            if override is not None and override.icon is not None:
                draft.set("icon", override.icon, SourceTier.C)

            # Resolve biomes to EntityRefs
            biome_refs: list[EntityRef] = []
            for b_id in struct_entry.biomes:
                b_name = drafts[b_id].name if b_id in drafts else _biome_ref(b_id, join_table).name
                b_ref = EntityRef(id=b_id, name=b_name)
                biome_refs.append(b_ref)
                structures_by_biome.setdefault(b_id, []).append(
                    EntityRef(id=entity_id, name=display_name)
                )

            # Resolve siblings to StructureSibling
            sibling_refs: list[StructureSibling] = []
            for sib in struct_entry.siblings:
                sib_name = structure_display_names.get(
                    sib.structure, _fallback_name(sib.structure.split(":", 1)[-1])
                )
                sibling_refs.append(
                    StructureSibling(
                        structure=EntityRef(id=sib.structure, name=sib_name),
                        weight=sib.weight,
                    )
                )

            # Placement
            placement: StructurePlacement
            if isinstance(struct_entry.placement, ExtractedRandomSpreadPlacement):
                ez = None
                if struct_entry.placement.exclusion_zone is not None:
                    ez = ExclusionZone(
                        other_set=struct_entry.placement.exclusion_zone.other_set,
                        chunk_count=struct_entry.placement.exclusion_zone.chunk_count,
                    )
                placement = RandomSpreadPlacement(
                    type=struct_entry.placement.type,
                    spacing=struct_entry.placement.spacing,
                    separation=struct_entry.placement.separation,
                    spread_type=struct_entry.placement.spread_type,
                    frequency=struct_entry.placement.frequency,
                    frequency_reduction_method=struct_entry.placement.frequency_reduction_method,
                    exclusion_zone=ez,
                    salt=struct_entry.placement.salt,
                )
            else:
                placement = ConcentricRingsPlacement(
                    type=struct_entry.placement.type,
                    count=struct_entry.placement.count,
                    distance=struct_entry.placement.distance,
                    spread=struct_entry.placement.spread,
                    preferred_biomes=struct_entry.placement.preferred_biomes,
                    salt=struct_entry.placement.salt,
                )

            # Spawns
            spawns: list[StructureSpawnEntry] = []
            for sp in struct_entry.spawns:
                mob_name = (
                    drafts[sp.entity_type].name
                    if sp.entity_type in drafts
                    else _fallback_name(sp.entity_type.split(":", 1)[-1])
                )
                spawns.append(
                    StructureSpawnEntry(
                        category=sp.category,
                        mob=EntityRef(id=sp.entity_type, name=mob_name),
                        group_size=IntegerRange(minimum=sp.min_count, maximum=sp.max_count),
                        weight=sp.weight,
                    )
                )

            draft.add_section(
                StructureInfo(
                    dimension=struct_entry.dimension.value,
                    step=struct_entry.step,
                    biomes=tuple(biome_refs),
                    placement=placement,
                    siblings=tuple(sibling_refs),
                    spawns=tuple(spawns),
                    suppressed_spawns=struct_entry.suppressed_spawns,
                ),
                SourceTier.A,
            )

            # Chest loot containers
            chest_section = _build_chest_loot(
                entity_id, containers_by_structure, producers_by_table, drafts
            )
            if chest_section is not None:
                draft.add_section(chest_section, SourceTier.A)

            curated_aliases = curated.aliases.get(entity_id, ())
            for alias, strength in generate_aliases(
                entity_id=entity_id,
                kind=kind,
                name=display_name,
                curated=curated_aliases,
            ):
                alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
                draft.add_aliases([alias], alias_tier)

            drafts[entity_id] = draft

        # --- Curated feature places -----------------------------------------
        #
        # A dungeon is the reason this block exists. Players call it a structure
        # and `chest-sources.json` files its chest under one, but the registry
        # holds it as a configured feature, so `worldgen/structure` never names
        # it and it was the one lootable place in the game with no page.
        #
        # It renders as `GenerationInfo` rather than `StructureInfo`, and that is
        # the honest shape rather than a convenience: a feature has no structure
        # set, no separation, and no generation step, so `StructureInfo` would be
        # mostly empty and its placement field could not be filled at all. What a
        # feature does have -- a dimension, a height band, attempts per chunk and
        # a biome list -- is exactly what `GenerationInfo` was built to state for
        # an ore vein. The kind stays `structure`, because that is the badge and
        # the renderer a player looking for a place expects, not a claim about
        # which registry the id came from.
        for place_id, place in (feature_place_index or {}).items():
            kind = EntityKind.STRUCTURE
            override = curated.overrides.get(place_id)
            if override is not None and override.kind is not None:
                kind = override.kind

            draft = EntityDraft(id=place_id, kind=kind, name=place.name, tier=SourceTier.A)
            draft.set("name", place.name, SourceTier.B)
            draft.set(
                "wikiUrl",
                f"https://minecraft.wiki/w/{place.page.replace(' ', '_')}",
                SourceTier.B,
            )

            blurb = blurbs.get(place.page)
            if blurb is not None:
                draft.set("blurb", blurb, SourceTier.B)
            else:
                missing_blurbs.append(MissingBlurb(id=place_id, page=place.page))

            if override is not None and override.icon is not None:
                draft.set("icon", override.icon, SourceTier.C)

            biome_refs = [
                EntityRef(
                    id=b_id,
                    name=drafts[b_id].name if b_id in drafts else _biome_ref(b_id, join_table).name,
                )
                for b_id in place.biomes
            ]
            for place_biome in biome_refs:
                structures_by_biome.setdefault(place_biome.id, []).append(
                    EntityRef(id=place_id, name=place.name)
                )

            draft.add_section(
                GenerationInfo(
                    scopes=(
                        GenerationScope(
                            dimension=place.dimension.value,
                            min_y=place.min_y,
                            max_y=place.max_y,
                            attempts_per_chunk=place.attempts_per_chunk,
                            biome_count=len(biome_refs),
                            all_biomes_of_dimension=place.all_biomes_of_dimension,
                            biomes=() if place.all_biomes_of_dimension else tuple(biome_refs),
                        ),
                    )
                ),
                SourceTier.A,
            )

            chest_section = _build_chest_loot(
                place_id, containers_by_structure, producers_by_table, drafts
            )
            if chest_section is not None:
                draft.add_section(chest_section, SourceTier.A)

            for alias, strength in generate_aliases(
                entity_id=place_id,
                kind=kind,
                name=place.name,
                curated=curated.aliases.get(place_id, ()),
            ):
                alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
                draft.add_aliases([alias], alias_tier)

            drafts[place_id] = draft

    # --- Biomes: climate, spawns, and generating blocks ---------------------
    if biome_index is not None:
        biome_by_name: dict[str, str] = {}
        for b_id in biome_index:
            name = (
                drafts[b_id].name
                if b_id in drafts
                else _fallback_name(b_id.split(":", 1)[-1])
            )
            biome_by_name[name.lower()] = b_id

        # Overlay wiki notes from spawn_index
        notes_by_mob_biome: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        for entry in spawn_index.entries:
            if entry.note is None:
                continue
            mob_rows = _wiki_rows(entry.mob_page, "entity_type", join_table)
            if not mob_rows:
                mob_rows = _wiki_rows(entry.mob, "entity_type", join_table)
            mob_id = next(iter({r.registry_id for r in mob_rows})) if mob_rows else None
            if mob_id is not None:
                mob_id = _resolve_mob_id(mob_id, drafts)

            resolved_biome_id: str | None = biome_by_name.get(entry.biome.lower())
            if not resolved_biome_id:
                resolved_biome_id = biome_by_name.get(entry.biome_page.lower())

            if mob_id and resolved_biome_id:
                notes_by_mob_biome[(mob_id, resolved_biome_id)] = (entry.note, entry.note_name)
            else:
                unplaced.append(
                    UnplacedRow(
                        table="spawn_table",
                        subject=entry.mob,
                        reason=(
                            f"biome {entry.biome!r} is not an enumerated biome entity"
                            if not resolved_biome_id
                            else f"mob {entry.mob!r} could not be resolved to an entity_type ID"
                        ),
                    )
                )

        # Block generation by biome
        common_blocks: dict[Dimension, set[str]] = {
            Dimension.OVERWORLD: set(),
            Dimension.NETHER: set(),
            Dimension.END: set(),
        }
        specific_blocks_by_biome: dict[str, set[str]] = {}
        if generation_index is not None:
            for block_id, bg in generation_index.items():
                for scope in bg.scopes:
                    if scope.all_biomes_of_dimension:
                        common_blocks[scope.dimension].add(block_id)
                    else:
                        for b_id in scope.biomes:
                            specific_blocks_by_biome.setdefault(b_id, set()).add(block_id)

        # Build BiomeInfo for each biome and collect inverted mob spawns
        mob_spawns: dict[str, list[SpawnEntry]] = {}

        for biome_id, biome_entry in biome_index.items():
            biome_draft = drafts.get(biome_id)
            if biome_draft is None:
                continue

            biome_name = biome_draft.name
            biome_ref = EntityRef(id=biome_id, name=biome_name)

            b_spawns: list[BiomeSpawnEntry] = []
            for category, spawners in biome_entry.spawners.items():
                cat_total = biome_entry.category_totals.get(category, 0)
                for spawner in spawners:
                    mob_id = _resolve_mob_id(spawner.entity_type, drafts)
                    mob_name = (
                        drafts[mob_id].name
                        if mob_id in drafts
                        else _fallback_name(mob_id.split(":", 1)[-1])
                    )
                    note_tuple = notes_by_mob_biome.get((mob_id, biome_id))
                    note = note_tuple[0] if note_tuple else None
                    note_name = note_tuple[1] if note_tuple else None

                    b_spawns.append(
                        BiomeSpawnEntry(
                            category=category,
                            mob=EntityRef(id=mob_id, name=mob_name),
                            group_size=IntegerRange(
                                minimum=spawner.min_count, maximum=spawner.max_count
                            ),
                            weight=spawner.weight,
                            total_weight=cat_total,
                            note=note,
                            note_name=note_name,
                        )
                    )

                    mob_spawns.setdefault(mob_id, []).append(
                        SpawnEntry(
                            biome=biome_name,
                            biome_ref=biome_ref,
                            category=category,
                            weight=float(spawner.weight),
                            total_weight=float(cat_total),
                            group_size=IntegerRange(
                                minimum=spawner.min_count, maximum=spawner.max_count
                            ),
                            note=note,
                            note_name=note_name,
                        )
                    )

            b_spawns.sort(key=lambda s: (s.category, -s.weight, s.mob.name))

            specific_blks = specific_blocks_by_biome.get(biome_id, set())
            b_blocks: list[EntityRef] = []
            for blk_id in sorted(specific_blks):
                blk_name = (
                    drafts[blk_id].name
                    if blk_id in drafts
                    else _fallback_name(blk_id.split(":", 1)[-1])
                )
                b_blocks.append(EntityRef(id=blk_id, name=blk_name))
            b_blocks.sort(key=lambda r: (r.name, r.id))

            # A biome in no dimension tag has no dimension-wide block set to count.
            common_blocks_count = (
                len(common_blocks.get(biome_entry.dimension, set()))
                if biome_entry.dimension is not None
                else 0
            )

            b_noise: list[NoisePlacement] = []
            if noise_placements and biome_id in noise_placements:
                for p in noise_placements[biome_id]:
                    if isinstance(p, NoisePlacement):
                        b_noise.append(p)
                    else:
                        noise_sib: EntityRef | None = None
                        if p.sibling is not None:
                            sib_name = (
                                drafts[p.sibling.id].name
                                if p.sibling.id in drafts
                                else p.sibling.name
                            )
                            noise_sib = EntityRef(id=p.sibling.id, name=sib_name)
                        b_noise.append(
                            NoisePlacement(
                                route=p.route,
                                group=p.group,
                                temperature=p.temperature,
                                humidity=p.humidity,
                                continentalness=p.continentalness,
                                erosion=p.erosion,
                                weirdness=p.weirdness,
                                pv=p.pv,
                                depth=p.depth,
                                additional_requirement=p.additional_requirement,
                                condition=p.condition,
                                sibling=noise_sib,
                                temperature_levels=p.temperature_levels,
                                humidity_levels=p.humidity_levels,
                                erosion_levels=p.erosion_levels,
                                continentalness_bands=p.continentalness_bands,
                                pv_band=p.pv_band,
                            )
                        )

            biome_info = BiomeInfo(
                dimension=(
                    biome_entry.dimension.value if biome_entry.dimension is not None else None
                ),
                temperature=biome_entry.temperature,
                temperature_modifier=biome_entry.temperature_modifier,
                downfall=biome_entry.downfall,
                has_precipitation=biome_entry.has_precipitation,
                precipitation=biome_entry.precipitation,
                creature_spawn_probability=biome_entry.creature_spawn_probability,
                spawn_costs=biome_entry.spawn_costs,
                spawns=tuple(b_spawns),
                blocks=tuple(b_blocks),
                common_blocks_count=common_blocks_count,
                noise_placements=tuple(b_noise),
            )
            biome_draft.add_section(biome_info, SourceTier.A)

        for mob_id, m_entries in mob_spawns.items():
            mob_draft = drafts.get(mob_id)
            if mob_draft is not None:
                sorted_entries = tuple(sorted(m_entries, key=lambda e: (e.biome, e.category)))
                mob_draft.add_section(SpawnInfo(entries=sorted_entries), SourceTier.A)

    # Reverse links on biomes: attach LinkList(title="Structures", links=...)
    for biome_id, struct_refs in structures_by_biome.items():
        if biome_id in drafts:
            sorted_links = tuple(sorted(struct_refs, key=lambda r: (r.name, r.id)))
            drafts[biome_id].add_section(
                LinkList(title="Structures", links=sorted_links),
                SourceTier.A,
            )

    # --- DropTable, TradeTable: forward resolution from Tier B ---

    def attach(target: str, section: Section, *, table: str, subject: str) -> None:
        """Attach one wiki-authored section, or report why it cannot be attached.

        A section is a table the wiki compiled, so decision D1 obliges a link
        back to the page it came from. An entity whose own row never resolved
        has no such link, and `Entity` refuses to build at all in that state.

        The guard makes the invariant structural rather than a crash at the
        end of a twenty-minute build. It is reached when forward resolution
        succeeds through a display name while `_own_row` could not settle on
        one name for the ID -- `minecraft:jigsaw`, which the wiki calls both
        `Jigsaw Block` and `Jigsaw structure Jigsaw`, is the shape that
        survives every tie-break `_own_row` applies. Dropping the section
        loses a table; attaching it would publish wiki-authored content with
        no credit, which is the one failure this project cannot ship.
        """
        draft = drafts[target]
        if draft.wiki_url is None:
            unplaced.append(
                UnplacedRow(
                    table=table,
                    subject=subject,
                    reason=(
                        f"{target} has no resolved wiki page, so a {section.type} section "
                        f"would carry wiki-authored content with no attribution link"
                    ),
                )
            )
            return
        draft.add_section(section, SourceTier.B)

    for mob_name, mob_drops in drop_index.by_mob.items():
        target = _resolve_forward(
            mob_name, "entity_type", join_table, drafts, table="droptable", unplaced=unplaced
        )
        if target is None:
            continue
        drops = tuple(_convert_drop_entry(drop, join_table, drafts) for drop in mob_drops)
        attach(target, DropTable(drops=drops), table="droptable", subject=mob_name)

    # Two display names can resolve to one item, and since `Enchanted <item>`
    # falls back to `<item>` that is now the ordinary case rather than a freak
    # one: a Fletcher sells both a `Bow` and an `Enchanted Bow`, and both are
    # `minecraft:bow`. `EntityDraft.add_section` is keyed by section type, so
    # attaching twice would replace the first table rather than extend it and
    # would lose every trade in it. Group by target first, then attach once.
    trades_by_target: dict[str, list[enrich_trade.WikiTrade]] = {}
    names_by_target: dict[str, list[str]] = {}
    for item_name, item_trades in trade_index.by_given_item.items():
        target = _resolve_forward(
            item_name, "item", join_table, drafts, table="trade", unplaced=unplaced
        )
        if target is None:
            continue
        trades_by_target.setdefault(target, []).extend(item_trades)
        names_by_target.setdefault(target, []).append(item_name)

    for target, target_trades in trades_by_target.items():
        trades = tuple(
            _convert_trade_entry(trade, join_table, drafts, profession_refs=profession_refs)
            for trade in target_trades
        )
        attach(
            target,
            TradeTable(trades=trades),
            table="trade",
            subject=", ".join(names_by_target[target]),
        )

    if WANDERING_TRADER_NAME in trade_index.by_profession:
        wt_trades = trade_index.by_profession[WANDERING_TRADER_NAME]
        if WANDERING_TRADER_ID in drafts:
            converted_wt_trades = tuple(
                _convert_trade_entry(t, join_table, drafts, profession_refs=profession_refs)
                for t in wt_trades
            )
            attach(
                WANDERING_TRADER_ID,
                TradeTable(trades=converted_wt_trades),
                table="trade",
                subject=WANDERING_TRADER_NAME,
            )

    if breeding_index is not None:
        for mob_name, mob_breeding in breeding_index.by_mob.items():
            target = _resolve_forward(
                mob_name, "entity_type", join_table, drafts, table="breeding", unplaced=unplaced
            )
            if target is None:
                continue

            breeding_items = tuple(
                BreedingItem(
                    name=item_name,
                    ref=_maybe_ref(item_name, "item", join_table, drafts),
                )
                for item_name in mob_breeding.items
            )

            taming_names = curated.taming.get(target, ())
            taming_items = tuple(
                BreedingItem(
                    name=t_name,
                    ref=_maybe_ref(t_name, "item", join_table, drafts),
                )
                for t_name in taming_names
            )

            attach(
                target,
                BreedingInfo(
                    items=breeding_items,
                    requires_taming=mob_breeding.requires_taming,
                    taming_items=taming_items,
                    cooldown_seconds=mob_breeding.cooldown_seconds,
                    baby_growth_seconds=mob_breeding.baby_growth_seconds,
                ),
                table="breeding",
                subject=mob_name,
            )

    if food_index is not None:
        for item_id, facts in food_index.items():
            item_draft = drafts.get(item_id)
            if item_draft is None:
                unplaced.append(
                    UnplacedRow(
                        table="food",
                        subject=item_id,
                        reason="the item has a food or consumable component and this build does "
                        "not enumerate it as an entity",
                    )
                )
                continue
            food_section = _build_food_info(facts, display_names, drafts)
            if food_section is None:
                continue
            # `add_section_first`, not `add_section`: TODO.md's Phase 6 line
            # asks for this block "right after the blurb at the top of the
            # page", and this loop runs after the Tier B tables have already
            # attached theirs. Tier A, because both components come from
            # mcmeta and no wiki page was read to build the section -- so it
            # incurs no D1 attribution requirement of its own.
            item_draft.add_section_first(food_section, SourceTier.A)

    if harvest_index is not None:
        for block_id, harvest_facts in harvest_index.items():
            block_draft = drafts.get(block_id)
            if block_draft is None:
                unplaced.append(
                    UnplacedRow(
                        table="harvest",
                        subject=block_id,
                        reason=(
                            "the block has a harvest requirement in the block tags and this "
                            "build does not enumerate it as an entity"
                        ),
                    )
                )
                continue
            drops_without_tool = (
                HarvestTool.PICKAXE not in harvest_facts.tools
                and harvest_facts.tier is HarvestTier.WOODEN
            )
            raw_drops = block_drops.get(block_id, ()) if block_drops is not None else ()
            drops_with_names = tuple(
                HarvestDrop(
                    id=drop.id,
                    name=drafts[drop.id].name if drop.id in drafts else drop.name,
                    count=drop.count,
                    gate=drop.gate,
                )
                for drop in raw_drops
            )
            harvest_section = HarvestInfo(
                tools=harvest_facts.tools,
                tier=harvest_facts.tier,
                drops_without_tool=drops_without_tool,
                drops=drops_with_names,
            )
            block_draft.add_section_first(harvest_section, SourceTier.A)

    if generation_index is not None:
        for block_id, gen_facts in generation_index.items():
            block_draft = drafts.get(block_id)
            if block_draft is None:
                unplaced.append(
                    UnplacedRow(
                        table="generation",
                        subject=block_id,
                        reason=(
                            "the block has worldgen features and this build does not enumerate it "
                            "as an entity"
                        ),
                    )
                )
                continue
            gen_section = GenerationInfo(
                scopes=tuple(
                    GenerationScope(
                        dimension=scope.dimension.value,
                        min_y=scope.min_y,
                        max_y=scope.max_y,
                        densest_y=scope.densest_y,
                        surface_only=scope.surface_only,
                        attempts_per_chunk=scope.attempts_per_chunk,
                        biome_count=scope.biome_count,
                        all_biomes_of_dimension=scope.all_biomes_of_dimension,
                        biomes=tuple(
                            _biome_ref(biome_id, join_table) for biome_id in scope.biomes
                        ),
                        veins=tuple(
                            VeinInfo(
                                feature=vein.feature,
                                min_y=vein.min_y,
                                max_y=vein.max_y,
                                surface=vein.surface,
                                densest_y=vein.densest_y,
                                tries=vein.tries,
                                chunk_chance=vein.chunk_chance,
                                vein_size=vein.vein_size,
                            )
                            for vein in scope.veins
                        ),
                    )
                    for scope in gen_facts.scopes
                )
            )
            block_draft.add_section(gen_section, SourceTier.A)

    if effect_index is not None:
        clear_all_removers: list[EffectLink] = []
        specific_removers: dict[str, list[EffectLink]] = {}
        if food_index is not None:
            for item_id, food_facts in food_index.items():
                item_draft = drafts.get(item_id)
                if item_draft is None:
                    continue
                item_name = item_draft.name
                link = EffectLink(name=item_name, ref=EntityRef(id=item_id, name=item_name))
                for eff in food_facts.effects:
                    if eff.kind is ConsumeEffectKind.CLEAR_ALL_EFFECTS:
                        if link not in clear_all_removers:
                            clear_all_removers.append(link)
                    elif eff.kind is ConsumeEffectKind.REMOVE_EFFECTS:
                        for removed_effect_id in eff.removed:
                            removers_list = specific_removers.setdefault(removed_effect_id, [])
                            if link not in removers_list:
                                removers_list.append(link)

        for effect_facts in effect_index.effects:
            target = _resolve_forward(
                effect_facts.title,
                "mob_effect",
                join_table,
                drafts,
                table="effect",
                unplaced=unplaced,
            )
            if target is None:
                continue

            target_draft = drafts.get(target)
            if target_draft is None:
                continue

            resolved_sources: list[EffectSource] = []
            for s in effect_facts.sources:
                ref = _potion_variant_ref(s.name, s.qualifier, drafts) or _any_registry_ref(
                    s.name, join_table, drafts
                )
                resolved_sources.append(
                    EffectSource(
                        name=s.name,
                        ref=ref,
                        qualifier=s.qualifier,
                        potency=s.potency,
                        length=s.length,
                        note=s.note,
                    )
                )

            target_removers: list[EffectLink] = []
            for link in clear_all_removers:
                if link not in target_removers:
                    target_removers.append(link)
            for link in specific_removers.get(target, ()):
                if link not in target_removers:
                    target_removers.append(link)

            effect_section = EffectSources(
                category=effect_facts.category,
                behaviour=effect_facts.behaviour,
                sources=tuple(resolved_sources),
                removed_by=tuple(target_removers),
            )

            if target_draft.wiki_url is None:
                unplaced.append(
                    UnplacedRow(
                        table="effect",
                        subject=effect_facts.title,
                        reason=(
                            f"{target} has no resolved wiki page, so an EffectSources section "
                            f"would carry wiki-authored content with no attribution link"
                        ),
                    )
                )
                continue

            target_draft.add_section_first(effect_section, SourceTier.B)

    if enchant_index is not None:
        def _resolve_item_refs(
            item_ids: Sequence[str], *, enchant_id: str
        ) -> tuple[EntityRef, ...]:
            refs: list[EntityRef] = []
            for item_id in item_ids:
                item_draft = drafts.get(item_id)
                if item_draft is not None:
                    refs.append(EntityRef(id=item_id, name=item_draft.name))
                else:
                    unplaced.append(
                        UnplacedRow(
                            table="enchantment",
                            subject=item_id,
                            reason=(
                                f"item {item_id} in applicability group of {enchant_id} "
                                "is not an enumerated entity"
                            ),
                        )
                    )
                    refs.append(EntityRef(id=item_id, name=item_id))
            return tuple(sorted(refs, key=lambda r: r.name))

        for enchant_id, enchant_facts in enchant_index.items():
            enchant_draft = drafts.get(enchant_id)
            if enchant_draft is None:
                unplaced.append(
                    UnplacedRow(
                        table="enchantment",
                        subject=enchant_id,
                        reason=(
                            "the enchantment is defined in mcmeta and this build does not "
                            "enumerate it as an entity"
                        ),
                    )
                )
                continue

            supported_refs = _resolve_item_refs(
                enchant_facts.supported_items, enchant_id=enchant_id
            )
            primary_refs = (
                _resolve_item_refs(enchant_facts.primary_items, enchant_id=enchant_id)
                if enchant_facts.primary_items is not None
                else None
            )

            exclusive_refs: list[EntityRef] = []
            for conflict_id in enchant_facts.exclusive_set:
                conflict_draft = drafts.get(conflict_id)
                if conflict_draft is not None:
                    exclusive_refs.append(EntityRef(id=conflict_id, name=conflict_draft.name))
                else:
                    unplaced.append(
                        UnplacedRow(
                            table="enchantment",
                            subject=conflict_id,
                            reason=(
                                f"conflicting enchantment {conflict_id} of {enchant_id} "
                                "is not an enumerated entity"
                            ),
                        )
                    )
                    exclusive_refs.append(EntityRef(id=conflict_id, name=conflict_id))

            enchant_section = EnchantInfo(
                max_level=enchant_facts.max_level,
                weight=enchant_facts.weight,
                rarity=enchant_facts.rarity,
                anvil_cost=enchant_facts.anvil_cost,
                slots=enchant_facts.slots,
                cost_ranges=enchant_facts.cost_ranges,
                supported_items=ApplicableItems(
                    group=enchant_facts.supported_items_group,
                    items=supported_refs,
                ),
                primary_items=(
                    ApplicableItems(
                        group=enchant_facts.primary_items_group,
                        items=primary_refs,
                    )
                    if enchant_facts.primary_items_group is not None and primary_refs is not None
                    else None
                ),
                exclusive_set=tuple(sorted(exclusive_refs, key=lambda r: r.name)),
                treasure=enchant_facts.treasure,
                curse=enchant_facts.curse,
                tradeable=enchant_facts.tradeable,
            )
            enchant_draft.add_section(enchant_section, SourceTier.A)

    # --- Curated overrides: the last field-level write before `.build()` ---

    unknown_overrides: list[str] = []
    for entity_id, override in curated.overrides.items():
        target_draft = drafts.get(entity_id)
        if target_draft is None:
            unknown_overrides.append(entity_id)
            continue
        if override.name is not None:
            target_draft.set("name", override.name, SourceTier.C)
        if override.icon is not None:
            target_draft.set("icon", override.icon, SourceTier.C)
        if override.blurb is not None:
            target_draft.set("blurb", override.blurb, SourceTier.C)
        if override.wiki_url is not None:
            target_draft.set("wikiUrl", override.wiki_url, SourceTier.C)

    entities = tuple(draft.build() for draft in drafts.values())
    by_id = {entity.id: entity for entity in entities}

    counts = {registry: len(registries[registry]) for registry in _REGISTRY_PRECEDENCE}
    counts["advancement"] = len(advancement_ids)
    counts["potion"] = len(registries.get("potion", ()))
    counts["profession"] = len(profession_index)
    counts["structure"] = len(structure_index) if structure_index is not None else 0
    counts["entities"] = len(entities)
    # The per-kind breakdown of the 158 entity_type IDs, once the
    # classification, the demotion, and any curated override have all run.
    # Before an override moves one of the five clause-2 IDs, the module
    # docstring's classification section measures this as 93 `mob` (88
    # `SPAWN_EGG` plus the 5 `LOOT_TABLE_ONLY` defaults), 1 `block`, 41
    # `item`, and 23 `entity` on the live 26.2 data. `data/curated/
    # overrides.json` moves two of those 93 -- `armor_stand` to `item` and
    # `player` to `entity` -- so the counts written here, keyed by the kind
    # each ID actually ended up with, land at 91/42/1/24 once that build's
    # curated overrides are the ones in this repository.
    counts["split_ids"] = len(split_ids)
    for kind, count in entity_type_kind_counts.items():
        counts[f"entity_type_kind.{kind.value}"] = count

    report = MergeReport(
        unplaced=tuple(unplaced),
        multi_registry=tuple(multi_registry),
        undecided_entity_types=tuple(undecided_entity_types),
        missing_icons=tuple(missing_icons),
        missing_blurbs=tuple(missing_blurbs),
        unknown_curated_overrides=tuple(sorted(unknown_overrides)),
        stale_curated_documents=curated.stale,
        split_ids=split_ids,
        advancement_reconciliation=advancement_tree.reconcile(advancement_ids),
        counts=counts,
    )
    return MergeResult(entities=entities, by_id=by_id, report=report)


def write_report(report: MergeReport, path: Path = DEFAULT_REPORT_PATH) -> None:
    """Write `report` to `path` as indented JSON, creating parent directories as needed.

    Copies `pipeline.normalize.reconcile.write_report`'s shape exactly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = report.model_dump(mode="json")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
