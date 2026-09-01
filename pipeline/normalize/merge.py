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
vocabulary for the registry in question -- `_WIKI_KIND` records the mapping,
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
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, model_validator

from pipeline.enrich import advancement as enrich_advancement
from pipeline.enrich import droptable as enrich_droptable
from pipeline.enrich import infobox as enrich_infobox
from pipeline.enrich import spawn_table as enrich_spawn_table
from pipeline.enrich import trade as enrich_trade
from pipeline.enrich.resource_location import NAMESPACE, JoinTable, ResourceLocation
from pipeline.enrich.sprite import SpriteIndex
from pipeline.extract.entity_class import EntityClass, EntityClassification
from pipeline.fetch.extracts import ExtractReport
from pipeline.normalize import NormalizeError
from pipeline.normalize.aliases import AliasStrength, generate_aliases
from pipeline.normalize.curated import CuratedData, StaleDocument
from pipeline.normalize.entity import (
    AdvancementInfo,
    DamageValue,
    DistributionEntry,
    DropEntry,
    DropNote,
    DropTable,
    Entity,
    EntityDraft,
    EntityKind,
    EntityRef,
    IntegerRange,
    ItemAmount,
    JavaProbability,
    LabelledText,
    LabelledValue,
    LootingDrop,
    Measure,
    Ratio,
    Section,
    SizeValue,
    SourceTier,
    SpawnEntry,
    SpawnInfo,
    StatBlock,
    TradeEntry,
    TradeTable,
)
from pipeline.normalize.reconcile import ICON_RULES, resolve_icon

__all__ = [
    "DEFAULT_REPORT_PATH",
    "MergeReport",
    "MergeResult",
    "MissingBlurb",
    "MissingIconEntity",
    "MultiRegistryId",
    "UndecidedEntityType",
    "UnplacedRow",
    "merge_entities",
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
_WIKI_KIND: Mapping[str, tuple[str | None, ...]] = {
    "item": ICON_RULES["item"].join_kinds,
    "block": ICON_RULES["block"].join_kinds,
    "entity_type": ("entity",),
    "mob_effect": ("effect",),
    "worldgen/biome": ("biome",),
    "enchantment": (None,),
}


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


def _wiki_rows(name: str, registry: str, join_table: JoinTable) -> tuple[ResourceLocation, ...]:
    """Return the rows of `join_table.by_display_name[name]` whose kind fits `registry`.

    `_WIKI_KIND` is not optional here, for the reason `IconRule.join_kinds`'s
    own docstring gives in full: a raw chicken item and the chicken mob share
    one registry ID and, on some pages, one display name, and reading both
    kinds as candidates is how one gets silently resolved through the
    other's row.
    """
    wanted = _WIKI_KIND.get(registry, ())
    return tuple(row for row in join_table.by_display_name.get(name, ()) if row.kind in wanted)


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
    all_rows = join_table.by_registry_id.get(entity_id, ())
    for registry in registries:
        wanted = _WIKI_KIND.get(registry, ())
        rows = tuple(row for row in all_rows if row.kind in wanted)
        names = {row.display_name for row in rows}
        if len(names) == 1:
            return rows[0]

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
    path = entity_id.split(":", 1)[-1]
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
    if len(ids) != 1:
        return None
    target = next(iter(ids))
    if target not in by_id:
        return None
    return EntityRef(id=target, name=name)


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
        unplaced.append(
            UnplacedRow(
                table=table,
                subject=name,
                reason=f"ambiguous display name, candidates: {', '.join(sorted(ids))}",
            )
        )
        return None
    target = next(iter(ids))
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
    tried_any_iconed_registry = False
    all_routes: list[tuple[str, str, str]] = []
    for registry in registries_of_id:
        rule = ICON_RULES.get(registry)
        if rule is None or not rule.has_icons:
            continue
        tried_any_iconed_registry = True
        resolution = resolve_icon(entity_id, rule, join_table, sprite_index)
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


def _convert_spawn_entry(
    entry: enrich_spawn_table.SpawnEntry, join_table: JoinTable, by_id: Mapping[str, object]
) -> SpawnEntry:
    return SpawnEntry(
        biome=entry.biome,
        biome_ref=_maybe_ref(entry.biome, "worldgen/biome", join_table, by_id),
        category=entry.category,
        weight=float(entry.weight),
        total_weight=float(entry.total_weight),
        group_size=IntegerRange(minimum=entry.group_size.minimum, maximum=entry.group_size.maximum),
        note=entry.note,
        note_name=entry.note_name,
    )


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
    trade: enrich_trade.WikiTrade, join_table: JoinTable, by_id: Mapping[str, object]
) -> TradeEntry:
    max_trades = trade.max_trades
    return TradeEntry(
        profession=trade.profession,
        # Villager profession entities arrive in Phase 6c; nothing exists yet
        # for this to resolve a profession name to, per the schema's own
        # `professionRef` note.
        profession_ref=None,
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


def _registries_of_id(
    registries: Mapping[str, Sequence[str]],
    join_table: JoinTable,
    classification: EntityClassification,
) -> dict[str, tuple[str, ...]]:
    """Return every path of the six precedence registries, mapped to the registries it sits in.

    Each value lists the registries in the order the merge should try them, so
    `value[0]` is the entity's chosen registry: it decides the `kind` and it
    is the first registry `_own_row` looks for a wiki row under.

    The starting order is `_REGISTRY_PRECEDENCE`, and two adjustments run on
    top of it, in this order, for an ID that sits in more than one registry:

    **First, the registry whose wiki row calls the ID by its own name wins.**
    Precedence alone is a guess about which of two meanings a player wants,
    and the wiki has already answered the question by choosing what to call
    each row.

    `minecraft:ender_pearl` is the case that forced this. It is an
    `entity_type` and an `item`, and the wiki writes two rows: `Ender Pearl`
    for the item and `Thrown Ender Pearl` for the projectile. Straight
    precedence put `entity_type` first, so the merge named the entity
    `Thrown Ender Pearl` -- a player typing "ender pearl" would get an exact
    match on nothing and the page they wanted would rank below whatever did
    match. Comparing each row's display name against the registry path fixes
    it without a hand-written list: `ender_pearl` matches `Ender Pearl`, so
    `item` wins.

    The same rule leaves `minecraft:chicken` alone, which is the check that
    matters. Its rows are `Chicken` for the mob and `Raw Chicken` for the
    food; `chicken` matches the mob's row, `entity_type` keeps its
    precedence, and the mob still owns the page. Measured against the live
    26.2 registries on 2026-08-31 this adjustment fires for 14 IDs and every
    one is a fix: the nine boats and the bamboo raft become items rather than
    mobs, `egg` stops being `Thrown Egg`, `tnt` stops being `Primed TNT`, and
    `wheat` stops being `Wheat Crops`. The boats and the raft are also fixed
    by the second adjustment below on their own merits -- neither has a spawn
    egg or an entity loot table -- so for those ten this one is no longer the
    only thing holding the answer up, but it still fires first and still
    gives the same answer.

    **Second, an `entity_type` ID that classifies as `EntityClass.NEITHER`
    is demoted to the bottom of its own list.** This runs after the name
    adjustment and unconditionally overrides whatever it decided, which is
    what makes the demotion a real settlement rather than one more input to a
    tie-break: `pipeline.extract.entity_class.classify_entity_types` already
    proved this ID has no spawn egg and no entity loot table, so nothing the
    wiki calls it changes what it is. `minecraft:arrow` and `minecraft:
    snowball` are the case that used to fall through every other rule: both
    registries' wiki rows carry the identical name, so the name adjustment
    above cannot distinguish them and precedence alone used to decide --
    silently picking `mob` for an arrow, correct in the sense that the name
    was right either way, but wrong about what was choosing it, since nothing
    about "arrow" is a mob. The demotion is what actually settles it now:
    `arrow` and `snowball` are both `NEITHER`-classified, so `entity_type`
    drops to the bottom of their lists regardless of the name tie, and
    `item` wins on its own registry membership rather than on a coin flip
    dressed up as precedence. See `EntityClassification` and the module
    docstring's classification section for the full rule and its measured
    counts, and `EntityKind`'s own docstring for what `EntityKind.ENTITY`
    holds when the demotion leaves an ID with nowhere else to land.

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
    for path, regs in per_id.items():
        if len(regs) > 1:
            rows = join_table.by_registry_id.get(f"{NAMESPACE}:{path}", ())
            named = _registry_the_wiki_names_the_id_under(path, regs, rows)
            if named is not None:
                regs = [named] + [registry for registry in regs if registry != named]

        if "entity_type" in regs:
            entity_class = classification.by_path.get(path)
            if entity_class is None:
                raise NormalizeError(
                    f"{path!r} sits in the entity_type registry, and the entity classification "
                    f"this merge was given names nothing for it. The classifier and the "
                    f"registries payload have gone out of sync."
                )
            if entity_class is EntityClass.NEITHER and len(regs) > 1:
                regs = [registry for registry in regs if registry != "entity_type"] + [
                    "entity_type"
                ]

        ordered[path] = tuple(regs)
    return ordered


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
        wanted = _WIKI_KIND.get(registry, ())
        for row in rows:
            if row.kind in wanted and row.display_name.casefold().replace(" ", "_") == path:
                return registry
    return None


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
) -> MergeResult:
    """Return the merged `Entity` set of one build, and the report of how it was built.

    `registries` is the full mcmeta registries payload, matching `pipeline.
    normalize.reconcile.reconcile`'s own parameter of the same name.
    `advancement_ids` is `pipeline.extract.advancement.extract_advancement_ids`'s
    output. `entity_classification` is `pipeline.extract.entity_class.
    classify_entity_types`'s output, built from the same mcmeta payloads as
    `registries` -- the module docstring's classification section names the
    three-way rule it drives. Every other argument is the Tier B index (or
    Tier C `CuratedData`) the module docstring names as that section's
    source.

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

    per_id = _registries_of_id(registries, join_table, entity_classification)

    multi_registry: list[MultiRegistryId] = []
    undecided_entity_types: list[UndecidedEntityType] = []
    unplaced: list[UnplacedRow] = []
    missing_icons: list[MissingIconEntity] = []
    missing_blurbs: list[MissingBlurb] = []

    blurbs = extract_report.blurbs()
    drafts: dict[str, EntityDraft] = {}
    entity_registries: dict[str, tuple[str, ...]] = {}
    entity_type_kind_counts: dict[EntityKind, int] = {}

    for path, regs in per_id.items():
        entity_id = f"{NAMESPACE}:{path}"
        chosen_registry = regs[0]
        entity_class = entity_classification.by_path.get(path) if "entity_type" in regs else None
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
        if entity_class is not None:
            entity_type_kind_counts[kind] = entity_type_kind_counts.get(kind, 0) + 1

        fallback_name = _fallback_name(path)
        draft = EntityDraft(id=entity_id, kind=kind, name=fallback_name, tier=SourceTier.A)

        row = _own_row(entity_id, regs, join_table)
        resolved_name = fallback_name
        if row is not None:
            resolved_name = row.display_name
            draft.set("name", row.display_name, SourceTier.B)
            draft.set("wikiUrl", row.wiki_url, SourceTier.B)
            blurb = blurbs.get(row.page)
            if blurb is not None:
                draft.set("blurb", blurb, SourceTier.B)
            else:
                missing_blurbs.append(MissingBlurb(id=entity_id, page=row.page))

            box = infobox_report.by_page.get(row.page)
            if box is not None and _statblock_has_content(box):
                draft.add_section(_build_stat_block(box), SourceTier.B)

        icon_key, routes, exempt = _resolve_entity_icon(entity_id, regs, join_table, sprite_index)
        if icon_key is not None:
            draft.set("icon", icon_key, SourceTier.B)
        elif not exempt:
            missing_icons.append(MissingIconEntity(id=entity_id, routes_tried=routes))

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

        curated_aliases = curated.aliases.get(entity_id, ())
        for alias, strength in generate_aliases(
            entity_id=entity_id, kind=kind, name=resolved_name, curated=curated_aliases
        ):
            alias_tier = SourceTier.C if strength is AliasStrength.CURATED else SourceTier.A
            draft.add_aliases([alias], alias_tier)

        drafts[entity_id] = draft

    # --- SpawnInfo, DropTable, TradeTable: forward resolution from Tier B ---

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

    for mob_name, spawn_entries in spawn_index.by_mob.items():
        target = _resolve_forward(
            mob_name, "entity_type", join_table, drafts, table="spawn_table", unplaced=unplaced
        )
        if target is None:
            continue
        entries = tuple(_convert_spawn_entry(entry, join_table, drafts) for entry in spawn_entries)
        attach(target, SpawnInfo(entries=entries), table="spawn_table", subject=mob_name)

    for mob_name, mob_drops in drop_index.by_mob.items():
        target = _resolve_forward(
            mob_name, "entity_type", join_table, drafts, table="droptable", unplaced=unplaced
        )
        if target is None:
            continue
        drops = tuple(_convert_drop_entry(drop, join_table, drafts) for drop in mob_drops)
        attach(target, DropTable(drops=drops), table="droptable", subject=mob_name)

    for item_name, item_trades in trade_index.by_given_item.items():
        target = _resolve_forward(
            item_name, "item", join_table, drafts, table="trade", unplaced=unplaced
        )
        if target is None:
            continue
        trades = tuple(_convert_trade_entry(trade, join_table, drafts) for trade in item_trades)
        attach(target, TradeTable(trades=trades), table="trade", subject=item_name)

    # --- Curated overrides: applied last, so Tier C wins ---------------------

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
