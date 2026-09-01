"""Classify every `entity_type` registry path as a mob, an undecided case, or not a living thing.

`pipeline.normalize.merge`'s module docstring used to carry a "known
simplification, named rather than hidden": `EntityKind` had no member but
`mob` for anything the `entity_type` registry named, so an arrow, an item
frame, and a spawner minecart all rendered as mobs alongside the creeper and
the zombie. That was named rather than fixed because nothing in the pipeline
yet answered the question a fix needs: which `entity_type` paths are actually
mobs? This module answers it, from two Tier A signals the pipeline already
downloads, so the merge stage never has to guess from a registry path's
English spelling.

## The two signals, and why they settle almost every ID outright

**A spawn egg.** Every mob a player can summon from the creative inventory or
a dispenser has an item at `<path>_spawn_egg` in the `item` registry --
`creeper_spawn_egg`, `zombie_spawn_egg`. A spawn egg is Mojang's own
declaration that this `entity_type` path is a mob a player summons, not a
projectile, a display entity, or a piece of level geometry the game happens
to model as an entity.

**An entity loot table.** `loot_table/entities/<path>.json` in the vanilla
data pack, part of `pipeline.fetch.mcmeta.DATA_GROUPS`'s already-fetched
`loot_table` group, is what the game rolls when that entity type dies. A
loot table is a weaker signal than a spawn egg -- `armor_stand` and `player`
both have one and neither is a mob a player *spawns* -- but it still says
"this is a thing the game treats as capable of dying and dropping items,"
which nothing that is purely a projectile or a marker entity does.

Measured against the cached `26.2` mcmeta payloads on 2026-08-31, the
`entity_type` registry holds 158 paths. 88 of them have a spawn egg. 93 have
an entity loot table. The spawn-egg set is a **strict subset** of the
loot-table set -- every ID with a spawn egg also has a loot table, and the two
signals never disagree, they only differ in reach. That subset relationship
is what makes clause 2 below exactly 5 IDs rather than a fuzzy boundary drawn
by hand: it is precisely the 93 with a loot table minus the 88 with a spawn
egg, no more and no fewer.

## Three clauses, in this order

1. **Has a spawn egg -> `SPAWN_EGG`.** A mob, full stop. This is the top of
   `entity_type`'s precedence in `pipeline.normalize.merge`, unchanged from
   before this module existed.
2. **No spawn egg, but has an entity loot table -> `LOOT_TABLE_ONLY`.**
   Genuinely undecided by these two signals alone. `pipeline.normalize.merge`
   defaults this to `EntityKind.MOB` -- the same default the whole registry
   used to get unconditionally -- but names every such ID in the merge report
   so a future Minecraft version's new one cannot slip in silently the way
   the old unconditional mapping let all 158 slip in. Measured on 2026-08-31
   this clause holds exactly 5 IDs: `armor_stand`, `giant`, `illusioner`,
   `mannequin`, `player`. `data/curated/overrides.json` is where a human
   corrects one of the five when "mob" is the wrong default -- see that
   file's own note for which two of the five are corrected and why the other
   three are left at the default on purpose.
3. **Neither -> `NEITHER`.** Not a living thing by either signal. `pipeline.
   normalize.merge` demotes `entity_type` to the bottom of that ID's own
   registry precedence for this class, so a `block` or `item` registry
   membership wins the ID outright, and only an ID with no other registry
   membership at all becomes the new `EntityKind.ENTITY`. Measured on
   2026-08-31 this clause holds 65 IDs: 1 also sits in `block` (`tnt`), 41
   also sit in `item` (every boat and chest boat, every minecart, `arrow`,
   `snowball`, `ender_pearl`, and more), and 23 sit in no other precedence
   registry at all and so become `kind="entity"` --
   `experience_orb`, `lightning_bolt`, and `marker` among them.

## Reading the sheep variants as one entity type, not seventeen

The vanilla data pack does not give every entity type one loot table file.
`sheep` gets seventeen: one per dye colour, nested under a `sheep/`
subdirectory as `loot_table/entities/sheep/black.json`,
`loot_table/entities/sheep/white.json` and fourteen more, plus a top-level
`loot_table/entities/sheep.json` that is not nested and is not a colour.
Every other entity type in the pinned `26.2` archive sits at the top level,
one file per type: `loot_table/entities/creeper.json`. Reading the whole path
as the entity type would count `sheep` as seventeen different things, and
`_loot_table_entity_type` below reads only the *first* path segment after the
`loot_table/entities/` directory instead, stripping `.json` from it when no
`/` follows -- so `sheep/black.json` and `sheep.json` both give `sheep`, and
`creeper.json` gives `creeper`. Measured on 2026-08-31 the vanilla data pack
holds 109 files under `loot_table/entities/`, and collapsing them this way
gives exactly 93 distinct entity types -- the number this module's own
docstring cites above for the loot-table signal, and 109 minus the 16 surplus
sheep files.

## What this module does not decide

`classify_entity_types` answers the three-way question and nothing past it.
It does not choose `EntityKind`, it does not apply a curated override, and it
does not know about `block` or `item` registry membership at all --
`pipeline.normalize.merge._registries_of_id` is where the classification this
module returns actually changes which registry wins an ID, and `EntityKind`
is chosen only there, once every registry an ID belongs to is known. Keeping
the two apart means a change to how `entity_type` is classified never has to
touch how registries are prioritised, and vice versa.

An archive with no entity loot table file at all is a broken read, not a
Minecraft version with no mobs -- every release since loot tables existed has
shipped them, so an empty answer means the fetch stage handed this module the
wrong group, or `fetch_data_files` was called for `loot_table` and returned
nothing. Per the Tier A rule CLAUDE.md states and `pipeline.extract`'s own
package docstring repeats, that raises `ExtractError` rather than quietly
classifying every `entity_type` path as `NEITHER`.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel

from pipeline.extract import ExtractError

__all__ = [
    "ENTITY_TYPE_REGISTRY",
    "ITEM_REGISTRY",
    "LOOT_TABLE_ENTITY_DIRECTORY",
    "LOOT_TABLE_FILE_SUFFIX",
    "SPAWN_EGG_SUFFIX",
    "EntityClass",
    "EntityClassification",
    "classify_entity_types",
]

# The directory of an entity loot table file inside `data/minecraft/`, as
# `fetch_data_files` keys it: `loot_table/entities/creeper.json`, or
# `loot_table/entities/sheep/black.json` for a variant. See the module
# docstring's sheep section for why the variant shape matters.
LOOT_TABLE_ENTITY_DIRECTORY = "loot_table/entities/"

LOOT_TABLE_FILE_SUFFIX = ".json"

# The suffix mcmeta appends to an `entity_type` path to name that entity's
# spawn egg item, when it has one: `creeper` -> `creeper_spawn_egg`.
SPAWN_EGG_SUFFIX = "_spawn_egg"

# The two mcmeta registries this module reads, by the name `pipeline.
# normalize.merge._REGISTRY_PRECEDENCE` already uses for each.
ENTITY_TYPE_REGISTRY = "entity_type"
ITEM_REGISTRY = "item"


class EntityClass(StrEnum):
    """Which of the three clauses classified one `entity_type` path.

    See the module docstring for the full rule. In short: `SPAWN_EGG` is a
    mob outright, `LOOT_TABLE_ONLY` is undecided and defaults to a mob,
    `NEITHER` is not a living thing and is demoted out of `entity_type`'s
    precedence wherever another registry can take the ID instead.
    """

    SPAWN_EGG = "spawn_egg"
    LOOT_TABLE_ONLY = "loot_table_only"
    NEITHER = "neither"


class EntityClassification(BaseModel, frozen=True):
    """The three-way classification of every `entity_type` path of one mcmeta payload.

    `by_path` is keyed by the bare registry path -- `creeper`, `arrow` -- the
    same shape `pipeline.normalize.merge` reads every other registry's IDs
    in, with no `minecraft:` namespace prefix.
    """

    by_path: Mapping[str, EntityClass]


def _registry(registries: Mapping[str, Sequence[str]], name: str) -> Sequence[str]:
    """Return `registries[name]`, or raise `ExtractError` when the payload does not carry it.

    A missing registry here is a broken read of the `registries` summary
    payload, not a real absence of `entity_type` or `item` from the game --
    every Minecraft release since entities and items existed has published
    both.
    """
    ids = registries.get(name)
    if ids is None:
        raise ExtractError(
            f"{name!r} is a registry this classifier reads, and the mcmeta registries payload "
            f"does not publish it. A payload with no {name!r} key is a broken read of the "
            f"registries branch, not a real absence of the registry from the game."
        )
    return ids


def _loot_table_entity_type(path: str) -> str:
    """Return the entity type that one `loot_table/entities/**` path names.

    Takes the first path segment after the directory, so a variant nested
    under its own subdirectory -- `sheep/black.json` -- collapses onto the
    same entity type as every sibling variant, and a plain top-level file --
    `creeper.json` -- has its `.json` extension stripped the same way. See
    the module docstring's sheep section for the measured count this
    collapsing produces.
    """
    remainder = path[len(LOOT_TABLE_ENTITY_DIRECTORY) :]
    first_segment = remainder.split("/", 1)[0]
    if first_segment.endswith(LOOT_TABLE_FILE_SUFFIX):
        first_segment = first_segment[: -len(LOOT_TABLE_FILE_SUFFIX)]
    return first_segment


def classify_entity_types(
    files: Mapping[str, bytes], registries: Mapping[str, Sequence[str]]
) -> EntityClassification:
    """Return the three-way classification of every `entity_type` path.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files` for the
    `loot_table` group (or a superset of groups that includes it): a mapping
    of path under `data/minecraft/` to the file's bytes. Only the path is
    read here -- a loot table's own contents describe what an entity drops
    and at what weight, which is `pipeline.enrich.droptable`'s concern, not
    this module's, so a caller may pass a mapping whose values are empty and
    still get a correct answer, exactly as `pipeline.extract.advancement.
    extract_advancement_ids` reads only paths of the `advancement` group.

    `registries` is the full mcmeta registries payload -- every registry name
    mapped to its IDs, the same shape `pipeline.normalize.reconcile.reconcile`
    and `pipeline.normalize.merge.merge_entities` both take. This module
    reads two of its keys: `entity_type`, to know which paths need an answer
    at all, and `item`, to check each one for a spawn egg. Raises
    `ExtractError` when either key is missing from the payload -- see
    `_registry`'s own docstring for the reason that is a broken read rather
    than a real absence.

    Raises `ExtractError` when `files` holds no file under
    `loot_table/entities/` at all. See the module docstring's closing
    paragraph for why that is a broken fetch rather than a version of the
    game with nothing that can die.
    """
    entity_type_paths = _registry(registries, ENTITY_TYPE_REGISTRY)
    item_paths = frozenset(_registry(registries, ITEM_REGISTRY))

    loot_table_entity_types: set[str] = set()
    for path in files:
        if not path.startswith(LOOT_TABLE_ENTITY_DIRECTORY):
            continue
        loot_table_entity_types.add(_loot_table_entity_type(path))

    if not loot_table_entity_types:
        raise ExtractError(
            "the archive holds no file under 'loot_table/entities/'. An empty read is a broken "
            "fetch, not a version of Minecraft with no entity types that can die and drop loot."
        )

    by_path: dict[str, EntityClass] = {}
    for path in entity_type_paths:
        if f"{path}{SPAWN_EGG_SUFFIX}" in item_paths:
            by_path[path] = EntityClass.SPAWN_EGG
        elif path in loot_table_entity_types:
            by_path[path] = EntityClass.LOOT_TABLE_ONLY
        else:
            by_path[path] = EntityClass.NEITHER
    return EntityClassification(by_path=by_path)
