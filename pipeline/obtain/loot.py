"""Turn loot into `Producer`s: mcmeta's block and chest tables, plus two Tier B indexes.

Three sources feed this module, and they are not read the same way.

## Block and chest loot: Tier A, read raw

`loot_table/blocks/*.json` and `loot_table/chests/*.json` are exact,
versioned data, so this module walks them the way `pipeline.extract.harvest`
walks a block tag: raise on a shape it does not recognize, never guess.
**The shapes verified live against the pinned `26.2-data` archive on
2026-09-01 disagree with an earlier draft of this task's implementation
notes, and the live shapes are what this module reads.** Two corrections,
both load-bearing for a project whose stated worst failure is a wrong
recipe:

1. A count is never a bare `modifier` field on the entry. It is
   `entry.functions[]`, an array of function objects, and the one this
   module reads is `{"function": "minecraft:set_count", "count": {"type":
   "minecraft:uniform", "min": N, "max": M}}` (or a bare integer `count`
   for a fixed drop). A `functions` entry can also be `minecraft:
   apply_bonus` (fortune) or `minecraft:explosion_decay`, both left
   unread here -- they scale a *drop chance*, not the existence of a
   producer, and `TODO.md` Phase 6's looting-tier display is `pipeline.
   enrich.droptable`'s job for mobs, with no chest/block equivalent
   requested yet.
2. Silk touch is never `condition: "minecraft:tool/can_silk_touch"`, which
   appears only on newer snapshots. It is `condition: "minecraft:match_tool"`
   whose `predicate.predicates."minecraft:enchantments"` array names
   `"minecraft:silk_touch"` with a `levels.min` of at least 1.
   Tool gates appear both at the entry level inside `minecraft:alternatives`
   (verified on `diamond_ore.json` and `coal_ore.json`) and at the pool level
   (on 82 block tables across the pinned archive: 76 silk-touch and 6 shears).

Pool-level conditions such as `survives_explosion` (on roughly 825 tables)
and pool-level tool gates (silk touch and shears) do not forfeit odds: a
silk-touch gate is deterministic for a player holding the tool, so the note
states the tool requirement while the odds describe the draw given it. Entry-level
conditions continue to forfeit odds, because the probability of an entry condition
holding is not stated by the table.

Entries nest through `minecraft:alternatives`, `minecraft:group`, and
`minecraft:sequence`, each carrying a `children` array of more entries,
verified on the block tables above. A flat read of `pools[].entries[]` alone
would miss every drop gated by a condition, which on the live ore tables is
half of them. The walk here recurses through all three container types and
collects every `type: "minecraft:item"` leaf, in the order it meets them, and
records whether a tool gate condition governs it, from any depth of the
containers or pool above it.

An entry `type` this module does not recognize (`minecraft:loot_table`, a
reference to another table; `minecraft:tag`, a whole tag as one weighted
entry; `minecraft:dynamic`, computed content such as a shulker box's own
inventory) is skipped and counted rather than raised on, because none of
them name one concrete item the way `minecraft:item` does, and inventing one
would be exactly the guess this project refuses to make.

## Mob loot and trades: Tier B, already parsed

`pipeline.enrich.droptable.DropIndex` and `pipeline.enrich.trade.TradeIndex`
are built once per run by earlier stages, keyed by wiki display name. This
module inverts each into `Producer`s rather than reading a fresh loot-table
JSON for it, per this task's own instruction: the wiki tables already carry
what mcmeta's raw entity loot tables would need a second, separate reader to
recover (looting-level breakdowns with exact fractions for drops, and Java
probabilities for trades), so re-deriving them from `loot_table/entities/`
would be strictly less precise for no benefit. Each display name --
`MobDrop.mob`, `MobDrop.item`, `TradeItem.item` -- is resolved to a registry
ID through the wiki's join table, the same `JoinTable.by_display_name` route
`pipeline.normalize.merge._wiki_rows` reads, narrowed by wiki `Type` the same
way that function is narrowed: an unnarrowed lookup would resolve a raw
chicken item through the chicken mob's row, exactly the collision `pipeline.
normalize.reconcile.IconRule.join_kinds`'s docstring already measures the
cost of. A name that does not resolve to exactly one registry ID is skipped
and reported rather than guessed at.

This module intentionally does **not** import `pipeline.normalize.merge`'s
own `WIKI_KIND` for that narrowing, even though the two constants describe
the same rule: `pipeline.normalize.merge` is the module that will call into
`pipeline.obtain.tree` to attach a `RecipeTree` section, and importing the
other direction here would point the package dependency backward for a
three-line constant. `_ITEM_KINDS` and `_ENTITY_KINDS` below are that
constant's item/block and entity_type rows, restated with a comment pointing
at the original, and `tests/test_obtain_loot.py` is what keeps the copies
from drifting apart unnoticed.

A `MobDrop`/`WikiTrade` this module cannot resolve is reported and skipped,
never raised on: these are Tier B rows, and a wiki page mid-edit is an
expected, ordinary event, not a shape fault.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pipeline.enrich.droptable import DropIndex, LootingDrop
from pipeline.enrich.resource_location import (
    JoinTable,
    ResourceLocation,
    alternative_names,
    alternative_registry_id,
)
from pipeline.enrich.trade import TradeIndex
from pipeline.obtain import ObtainError
from pipeline.obtain.chests import ChestSource, _coerce_structure_ref
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerInput, ProducerOutput

__all__ = [
    "BLOCK_LOOT_DIRECTORY",
    "CHEST_LOOT_DIRECTORY",
    "DEFAULT_LOOT_SOURCES_PATH",
    "LOOT_SOURCES_FILENAME",
    "READ_FAMILIES",
    "SHEARS_NOTE",
    "SILK_TOUCH_ENCHANTMENT",
    "SILK_TOUCH_NOTE",
    "SKIPPED_FAMILIES",
    "TYPE_TO_METHOD",
    "LootExtractionResult",
    "LootLeaf",
    "SkippedLootEntry",
    "UnresolvedTradeOrDrop",
    "extract_block_and_chest_loot",
    "extract_loot",
    "load_loot_sources",
    "producers_from_drop_index",
    "producers_from_trade_index",
    "verify_loot_sources",
]

BLOCK_LOOT_DIRECTORY = "loot_table/blocks"
CHEST_LOOT_DIRECTORY = "loot_table/chests"
LOOT_SOURCES_FILENAME = "loot-sources.json"
DEFAULT_LOOT_SOURCES_PATH = Path("data/curated") / LOOT_SOURCES_FILENAME
NAMESPACE = "minecraft"

READ_FAMILIES = frozenset(
    {
        "archaeology",
        "blocks",
        "brush",
        "carve",
        "chests",
        "dispensers",
        "gameplay",
        "harvest",
        "pots",
        "shearing",
        "spawners",
    }
)

SKIPPED_FAMILIES = frozenset(
    {
        "charged_creeper",
        "entities",
        "equipment",
    }
)

TYPE_TO_METHOD: Mapping[str, ObtainMethod] = {
    "minecraft:block": ObtainMethod.BLOCK_DROP,
    "minecraft:chest": ObtainMethod.CHEST_LOOT,
    "minecraft:archaeology": ObtainMethod.BRUSHING,
    "minecraft:entity_interact": ObtainMethod.BRUSHING,
    "minecraft:block_interact": ObtainMethod.HARVESTING,
    "minecraft:shearing": ObtainMethod.SHEARING,
    "minecraft:fishing": ObtainMethod.FISHING,
    "minecraft:barter": ObtainMethod.BARTERING,
    "minecraft:gift": ObtainMethod.GIFT,
}

_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# The container entry types that hold more entries, verified live on
# `diamond_ore.json`. `minecraft:group` and `minecraft:sequence` were not
# observed on the sample read for this task, but they share `children`'s
# shape in the loot table specification and cost nothing to walk the same way.
_CONTAINER_TYPES = frozenset(
    {"minecraft:alternatives", "minecraft:group", "minecraft:sequence"}
)
_ITEM_TYPE = "minecraft:item"

SILK_TOUCH_ENCHANTMENT = "minecraft:silk_touch"

# The qualifier a silk-touch-gated producer carries, in the vocabulary
# `Producer.note` defines. It is a named constant rather than a literal at the
# one place it is written because two readers now match on it -- the obtain
# tree renderer, through the emitted payload, and `pipeline.normalize.merge`'s
# block drops, which asks whether a producer is gated before it turns one into
# a `HarvestDrop`. A reworded literal would silently unset every silk-touch
# flag on that second reader rather than fail.
SILK_TOUCH_NOTE = "requires silk touch"
SHEARS_NOTE = "requires shears"

# Mirrors `pipeline.normalize.merge.WIKI_KIND`'s `item` and `entity_type`
# rows. See the module docstring for why this is a restatement rather than an
# import.
_ITEM_KINDS = ("item", "block")
_ENTITY_KINDS = ("entity",)


class SkippedLootEntry(BaseModel, frozen=True):
    """One loot table entry this module did not turn into a producer, and why."""

    table: str
    entry_type: str
    reason: str


class LootLeaf(BaseModel, frozen=True):
    """One `minecraft:item` entry the walk reached, with its odds where they exist.

    `chance` and `rolls` are set together, and only for a leaf whose odds the
    weighted-pool model actually describes -- see `_walk_entries` for the two
    shapes that forfeit them. `count_min` and `count_max` are always both set,
    and are equal for a fixed drop.
    """

    item: str
    count_min: int
    count_max: int
    gate: str | None = None
    chance: float | None = None
    rolls: float | None = None

    @property
    def per_attempt(self) -> float | None:
        """Return the expected number of items one attempt yields, or `None`.

        The loot-table half of the argument in `Producer`'s docstring: a pool
        rolled `rolls` times, each roll won with probability `chance`, each win
        paying the mean of the stack range.
        """
        if self.chance is None or self.rolls is None:
            return None
        return self.chance * self.rolls * (self.count_min + self.count_max) / 2.0


class UnresolvedTradeOrDrop(BaseModel, frozen=True):
    """One Tier B row whose display name did not resolve to exactly one registry ID."""

    table: str
    subject: str
    reason: str


class LootExtractionResult(BaseModel, frozen=True):
    """Every producer `extract_loot` built, and what it skipped."""

    producers: tuple[Producer, ...]
    skipped: tuple[SkippedLootEntry, ...]
    tables_by_family: Mapping[str, int] = Field(default_factory=dict)


def load_loot_sources(path: Path = DEFAULT_LOOT_SOURCES_PATH) -> dict[str, ChestSource]:
    """Read and validate `loot-sources.json`, returning table paths to ChestSource."""
    if not path.is_file():
        raise ObtainError(f"curated loot sources file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ObtainError(f"could not parse curated loot sources at {path}: {error}") from error

    if not isinstance(data, dict):
        raise ObtainError(f"{path} does not hold a JSON object.")

    sources_dict = data.get("sources")
    if not isinstance(sources_dict, dict):
        raise ObtainError(f"{path} does not declare a 'sources' mapping.")

    result: dict[str, ChestSource] = {}
    for table_id, entry in sources_dict.items():
        if not isinstance(entry, dict) or "structure" not in entry or "container" not in entry:
            raise ObtainError(
                f"{path} entry for {table_id!r} must be an object declaring 'structure' "
                f"and 'container'."
            )
        result[table_id] = ChestSource(
            structure=entry["structure"],
            container=entry["container"],
            ref=entry.get("ref"),
            structure_ref=_coerce_structure_ref(entry.get("structureRef")),
        )
    return result


def verify_loot_sources(
    found_tables: Iterable[str],
    curated: Mapping[str, ChestSource],
    *,
    extracted_structures: Iterable[str] | None = None,
) -> None:
    """Raise ObtainError if any found loot table is missing from curated sources,
    or if any structureRef names an unknown structure.
    """
    missing = [table for table in sorted(found_tables) if table not in curated]
    if missing:
        raise ObtainError(
            f"found {len(missing)} loot tables with no curated entry in "
            f"{LOOT_SOURCES_FILENAME}: {', '.join(missing)}"
        )

    if extracted_structures is not None:
        known = set(extracted_structures)
        unknown: set[str] = set()
        for table in found_tables:
            source = curated.get(table)
            if source is not None:
                for s_ref in source.structure_ref:
                    if s_ref not in known:
                        unknown.add(s_ref)
        if unknown:
            raise ObtainError(
                f"structureRef in {LOOT_SOURCES_FILENAME} names unknown structure(s): "
                f"{', '.join(sorted(unknown))}"
            )


def _namespaced(value: str) -> str:
    return value if ":" in value else f"{NAMESPACE}:{value}"


def _entry_count(entry: Mapping[str, Any]) -> tuple[int, int]:
    """Return the `(minimum, maximum)` count a `minecraft:item` leaf entry declares.

    Reads `functions[]` for a `minecraft:set_count` function -- see the
    module docstring's first correction for its real shape. `count` there is
    either a bare integer or a `{"type": "minecraft:uniform", "min", "max"}`
    object. A bare integer is a fixed drop, so both ends of the range are it.
    No `set_count` function at all means the game's own default of one.

    This used to return the floor alone, because `ProducerOutput.count` is one
    integer and the minimum is the guaranteed amount. The ceiling is now read
    as well, and travels beside it in `Producer.count_max`, because "10 to 36
    iron nuggets" is a materially different answer from "10" for a player
    deciding whether a barter is worth the gold -- and the ceiling was sitting
    unread in the same object the floor was taken from.
    """
    functions = entry.get("functions")
    if not isinstance(functions, list):
        return 1, 1
    for function in functions:
        if not isinstance(function, Mapping) or function.get("function") != "minecraft:set_count":
            continue
        count = function.get("count", 1)
        if isinstance(count, int | float):
            fixed = max(int(count), 1)
            return fixed, fixed
        if isinstance(count, Mapping):
            minimum = count.get("min", 1)
            maximum = count.get("max", minimum)
            low = max(int(minimum), 1) if isinstance(minimum, int | float) else 1
            high = max(int(maximum), low) if isinstance(maximum, int | float) else low
            return low, high
        return 1, 1
    return 1, 1


def _entry_weight(entry: Mapping[str, Any]) -> int:
    """Return the draw weight of one direct pool entry.

    Absent means one, which is the game's own default and the reason every
    entry of `loot_table/gameplay/fishing/treasure.json` is equally likely
    despite that table naming no weight at all.
    """
    weight = entry.get("weight", 1)
    if isinstance(weight, int | float) and weight > 0:
        return int(weight)
    return 1


def _numeric_average(value: Any) -> float | None:
    """Return the mean of a loot number provider that states a plain range.

    `rolls` is either a bare number or a `{"type": "minecraft:uniform", "min",
    "max"}` object, the same two shapes `set_count` uses. Any other provider
    -- binomial, or a score-driven one -- returns `None`, so the caller drops
    the odds rather than averaging a distribution this function does not model.
    """
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, Mapping):
        if value.get("type") not in (None, "minecraft:uniform"):
            return None
        minimum = value.get("min")
        maximum = value.get("max")
        if isinstance(minimum, int | float) and isinstance(maximum, int | float):
            return (float(minimum) + float(maximum)) / 2.0
    return None


def _condition_is_silk_touch(condition: Mapping[str, Any]) -> bool:
    """Return whether one `conditions[]` entry is the silk-touch gate.

    The real shape, verified live -- see the module docstring's second
    correction: `condition: "minecraft:match_tool"`, whose `predicate.
    predicates."minecraft:enchantments"` array names `minecraft:silk_touch`
    with `levels.min >= 1`.
    """
    if condition.get("condition") != "minecraft:match_tool":
        return False
    predicate = condition.get("predicate")
    if not isinstance(predicate, Mapping):
        return False
    predicates = predicate.get("predicates")
    if not isinstance(predicates, Mapping):
        return False
    enchantments = predicates.get("minecraft:enchantments")
    if not isinstance(enchantments, list):
        return False
    for enchantment in enchantments:
        if not isinstance(enchantment, Mapping):
            continue
        if enchantment.get("enchantments") != SILK_TOUCH_ENCHANTMENT:
            continue
        levels = enchantment.get("levels")
        minimum = levels.get("min") if isinstance(levels, Mapping) else None
        if isinstance(minimum, int | float) and minimum >= 1:
            return True
    return False


def _condition_is_shears(condition: Mapping[str, Any]) -> bool:
    """Return whether one `conditions[]` entry is the shears gate.

    The real shape in 26.2: `condition: "minecraft:match_tool"` whose
    `predicate.items` is `"minecraft:shears"` (or `["minecraft:shears"]`).
    """
    if condition.get("condition") != "minecraft:match_tool":
        return False
    predicate = condition.get("predicate")
    if not isinstance(predicate, Mapping):
        return False
    items = predicate.get("items")
    return items == "minecraft:shears" or items == ["minecraft:shears"]


def _conditions_gate(conditions: Any) -> str | None:
    """Return the first matching gate note from `conditions`, or `None`."""
    if not isinstance(conditions, list):
        return None
    for condition in conditions:
        if not isinstance(condition, Mapping):
            continue
        if _condition_is_silk_touch(condition):
            return SILK_TOUCH_NOTE
        if _condition_is_shears(condition):
            return SHEARS_NOTE
    return None


def _walk_entries(
    entries: Sequence[Any],
    *,
    gate: str | None,
    source: str,
    skipped: list[SkippedLootEntry],
    pool_weight: int | None = None,
    rolls: float | None = None,
) -> list[LootLeaf]:
    """Return every item leaf reachable from `entries`.

    `gate` carries whether an ancestor container or pool already gated this
    branch on a tool requirement (e.g. silk touch or shears), so a leaf under
    `minecraft:alternatives` inherits its parent's gate rather than each recursion
    re-deriving it.

    `pool_weight` and `rolls` describe the pool these entries are the *direct*
    children of, and both are `None` on every recursive call. That is what
    makes a leaf's odds available exactly where they are meaningful: a direct
    child of a plain weighted pool competes by weight, so its chance is its
    own weight over the pool's total, while a leaf found underneath a
    container is chosen by condition rather than by weight and gets no odds at
    all. `Producer`'s own docstring argues that refusal at more length.
    """
    found: list[LootLeaf] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ObtainError(f"{source} holds a loot entry of {entry!r}, not an object.")
        entry_type = entry.get("type")
        if not isinstance(entry_type, str):
            raise ObtainError(f"{source} holds a loot entry with no 'type'.")
        conditioned = isinstance(entry.get("conditions"), list) and bool(entry["conditions"])
        entry_gate = gate or _conditions_gate(entry.get("conditions"))
        if entry_type in _CONTAINER_TYPES:
            children = entry.get("children")
            if not isinstance(children, list):
                raise ObtainError(f"{source} holds a {entry_type} entry with no 'children' list.")
            found.extend(_walk_entries(children, gate=entry_gate, source=source, skipped=skipped))
        elif entry_type == _ITEM_TYPE:
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ObtainError(f"{source} holds an item entry with no 'name'.")
            count_min, count_max = _entry_count(entry)
            # Odds only where the weighted-pool model actually describes the
            # outcome: a direct child of a pool, carrying no condition of its
            # own whose probability no loot table states.
            chance: float | None = None
            if pool_weight is not None and rolls is not None and not conditioned:
                chance = _entry_weight(entry) / pool_weight
            found.append(
                LootLeaf(
                    item=_namespaced(name),
                    count_min=count_min,
                    count_max=count_max,
                    gate=entry_gate,
                    chance=chance,
                    rolls=rolls if chance is not None else None,
                )
            )
        else:
            skipped.append(
                SkippedLootEntry(
                    table=source,
                    entry_type=entry_type,
                    reason="this entry type names no single concrete item",
                )
            )
    return found


def _table_leaves(
    document: Mapping[str, Any], *, source: str, skipped: list[SkippedLootEntry]
) -> list[LootLeaf]:
    # A loot table with no `pools` key at all is a table that drops nothing,
    # not a broken file. `loot_table/blocks/budding_amethyst.json` is the
    # canonical case: it carries a `type` and a `random_sequence` and stops
    # there, because breaking budding amethyst by hand yields no item at all.
    # Several block tables share that shape. Reading a missing key as a fault
    # was what stopped the first real build of this stage, and treating it as
    # an empty answer is right for the same reason `pipeline.extract.harvest`
    # gives a block that no `needs` tag names the `wooden` tier: the absence
    # is the game's answer, not a gap in the read.
    #
    # A `pools` that is *present* and is not a list stays a fault. That is a
    # shape this project has never seen from mcmeta, so it means the archive
    # changed under us, and CLAUDE.md's rule against letting a broken read
    # travel down the pipeline as real data applies to it exactly.
    if "pools" not in document:
        return []
    pools = document["pools"]
    if not isinstance(pools, list):
        raise ObtainError(f"{source} carries a 'pools' of {pools!r}, not a list.")
    leaves: list[LootLeaf] = []
    for pool in pools:
        if not isinstance(pool, Mapping):
            raise ObtainError(f"{source} holds a pool of {pool!r}, not an object.")
        pool_entries = pool.get("entries")
        if not isinstance(pool_entries, list):
            raise ObtainError(f"{source} holds a pool with no 'entries' list.")

        # The denominator counts *every* direct entry, not only the item ones.
        # A `minecraft:loot_table` or `minecraft:tag` sibling still competes for
        # the same draw, so leaving it out would inflate every percentage in
        # the pool. `loot_table/gameplay/fishing.json` is the table that proves
        # it: junk 10, treasure 5 and fish 85 sum to 100, and dropping the two
        # this walk cannot name would turn the third into a certainty.
        total_weight = sum(
            _entry_weight(entry) for entry in pool_entries if isinstance(entry, Mapping)
        )
        # `bonus_rolls` is deliberately unread. It is scaled by the opener's
        # luck attribute, which is zero for an ordinary player and which no
        # table states, so the base roll count is what an unluck-ed attempt
        # actually gets -- and that is the number this tool's reader wants.
        rolls = _numeric_average(pool.get("rolls", 1))
        gate = _conditions_gate(pool.get("conditions"))
        leaves.extend(
            _walk_entries(
                pool_entries,
                gate=gate,
                source=source,
                skipped=skipped,
                pool_weight=total_weight if total_weight > 0 else None,
                rolls=rolls,
            )
        )
    return leaves


def extract_loot(files: Mapping[str, bytes]) -> LootExtractionResult:
    """Return every loot-table producer across the supported mcmeta families.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files`.
    Walks all tables under `loot_table/` matching `READ_FAMILIES`. Reads each table's
    declared `type` field to determine the `ObtainMethod`. Raises `ObtainError` if
    an unknown family or unknown `type` is encountered. Deliberately skips
    `SKIPPED_FAMILIES` (`entities`, `charged_creeper`, `equipment`), which are sourced
    from wiki drop tables or trial chamber mob spawn equipment.

    Raises `ObtainError` on malformed tables and when no loot tables are found.
    """
    loot_entries = {k: v for k, v in files.items() if k.startswith("loot_table/")}
    if not loot_entries:
        raise ObtainError(
            f"no file under {BLOCK_LOOT_DIRECTORY!r} or {CHEST_LOOT_DIRECTORY!r} was found. "
            f"An empty read is a broken scrape, not a version of Minecraft with no loot."
        )

    producers: list[Producer] = []
    skipped: list[SkippedLootEntry] = []
    tables_by_family: dict[str, int] = {}

    for key in sorted(loot_entries):
        parts = key.split("/")
        if len(parts) < 2:
            continue
        family = parts[1]
        if family in SKIPPED_FAMILIES:
            continue
        if family not in READ_FAMILIES:
            raise ObtainError(f"unknown loot table family {family!r} in {key}")

        document = _decoded(loot_entries[key], source=key)
        declared_type = document.get("type")
        if not isinstance(declared_type, str) or declared_type not in TYPE_TO_METHOD:
            raise ObtainError(
                f"{key} declares unknown or missing loot table type {declared_type!r}"
            )

        method = TYPE_TO_METHOD[declared_type]
        tables_by_family[family] = tables_by_family.get(family, 0) + 1

        leaves = _table_leaves(document, source=key, skipped=skipped)

        # One shape for every family. A block drop is the only method whose
        # producer names an input -- the block you break -- and every other
        # family is a zero-input leaf. The odds ride along identically on all
        # of them, because `_walk_entries` already decided per leaf whether the
        # weighted-pool model describes it, and that decision does not depend
        # on which family the table came from.
        for leaf in leaves:
            inputs: tuple[ProducerInput, ...] = ()
            if method is ObtainMethod.BLOCK_DROP:
                block_path = key[len(BLOCK_LOOT_DIRECTORY) + 1 : -len(".json")]
                inputs = (ProducerInput(item=_namespaced(block_path)),)
            producers.append(
                Producer(
                    method=method,
                    output=ProducerOutput(item=leaf.item, count=leaf.count_min),
                    inputs=inputs,
                    source_id=key,
                    note=leaf.gate,
                    chance=leaf.chance,
                    count_max=leaf.count_max if leaf.chance is not None else None,
                    per_attempt=leaf.per_attempt,
                )
            )

    return LootExtractionResult(
        producers=tuple(producers),
        skipped=tuple(skipped),
        tables_by_family=tables_by_family,
    )


extract_block_and_chest_loot = extract_loot


def _decoded(payload: bytes, *, source: str) -> Mapping[str, Any]:
    try:
        document: Any = json.loads(payload)
    except (ValueError, TypeError) as error:
        raise ObtainError(f"{source} is not JSON: {error}") from error
    if not isinstance(document, Mapping):
        raise ObtainError(f"{source} is not a JSON object.")
    return document


def _one_id(rows: Iterable[ResourceLocation]) -> str | None:
    """Return the single registry ID `rows` agree on, or `None` if they do not agree."""
    ids = {row.registry_id for row in rows}
    return next(iter(ids)) if len(ids) == 1 else None


def _resolve(name: str, *, join_table: JoinTable, kinds: tuple[str, ...]) -> str | None:
    """Return the one registry ID `name` resolves to under `kinds`, or `None`.

    Three routes, tried in order, each one narrower than a plain display-name
    lookup because a plain lookup measurably loses real drops and trades.

    1. **The display name, when it is unambiguous.** The common case.

    2. **The display name, tie-broken by the wiki page it sits on.** Two
       different items can carry the same display name. The live 26.2 join
       table maps "Potato" onto three rows: the crop block `potatoes`, the
       item `potato`, and `snektato`, an April Fools item whose own page is
       "Venomous Potato" but whose *display* name is also "Potato". Narrowing
       by `kinds` removes the block and still leaves two items, so route 1
       gives up and four real potato drops and trades were lost. The row
       whose page title is the name being looked up is the one the wiki
       itself treats as canonical for that name, so preferring it resolves
       the tie without inventing a preference between two registry IDs.

    3. **The page title, when the display name matched nothing.** The wiki
       disambiguates an item that shares a name with a mob by suffixing the
       page, so the `trade` bucket asks for "Tropical Fish (item)" and
       "Pufferfish (item)" -- titles that are nobody's display name, since
       the display name of both is the bare word. Matching the page title
       recovers them.

    4. **A name the wiki writes as a nickname, through `pipeline.enrich.
       resource_location`.** `<Pattern> Armor Trim`, `Arrow of <Effect>` and
       `Music Disc <Song>` are all names a loot or trade row states that no
       row's display name carries; that module owns the three rules and
       argues each one, because `pipeline.normalize.merge` reads the
       identical set against the same join table and a second copy here would
       be free to drift. Route 4 runs last, so a name that is already a real
       row never reaches it.

    A name that reaches none of the four is reported rather than guessed at.
    That is the right answer for most of what is left: "Enchanted Diamond
    Sword", "Any color Wool", and "Explorer Map" are a component, a variant
    group, and map data respectively, and none of the three is one registry
    ID that this function could honestly return.
    """
    named = tuple(row for row in join_table.by_display_name.get(name, ()) if row.kind in kinds)
    resolved = _one_id(named)
    if resolved is not None:
        return resolved

    if named:
        on_its_own_page = tuple(row for row in named if row.page == name)
        resolved = _one_id(on_its_own_page)
        if resolved is not None:
            return resolved

    by_page = tuple(row for row in join_table.entries if row.page == name and row.kind in kinds)
    resolved = _one_id(by_page)
    if resolved is not None:
        return resolved

    for alternative in alternative_names(name):
        resolved = _resolve(alternative, join_table=join_table, kinds=kinds)
        if resolved is not None:
            return resolved

    direct_id = alternative_registry_id(name)
    if direct_id is not None:
        return _one_id(
            tuple(row for row in join_table.by_registry_id.get(direct_id, ()) if row.kind in kinds)
        )

    return None


def producers_from_drop_index(
    drop_index: DropIndex, *, join_table: JoinTable
) -> tuple[tuple[Producer, ...], tuple[UnresolvedTradeOrDrop, ...]]:
    """Return every `MOB_LOOT` producer `drop_index` describes, and what did not resolve.

    Carries no inputs: the mob is named in `Producer.note` and `source_id`
    for traceability, but this module does not model "you must first obtain
    a mob" as an ingredient -- a mob is found and killed, not crafted, and
    `pipeline.obtain.tree` has nothing useful to expand a mob's own entity ID
    into.
    """
    producers: list[Producer] = []
    unresolved: list[UnresolvedTradeOrDrop] = []
    for drop in drop_index.drops:
        mob_id = _resolve(drop.mob, join_table=join_table, kinds=_ENTITY_KINDS)
        if mob_id is None:
            unresolved.append(
                UnresolvedTradeOrDrop(
                    table="droptable", subject=drop.mob, reason="the mob name did not resolve"
                )
            )
            continue
        item_id = _resolve(drop.item, join_table=join_table, kinds=_ITEM_KINDS)
        if item_id is not None:
            target_ids = [item_id]
        else:
            target_ids = []
            for note in drop.notes:
                links = [m.group(1).strip() for m in _WIKI_LINK.finditer(note.content)]
                if not links:
                    continue
                resolved_links = [
                    _resolve(link, join_table=join_table, kinds=_ITEM_KINDS) for link in links
                ]
                if all(r is not None for r in resolved_links):
                    target_ids = [r for r in resolved_links if r is not None]
                    break
                if any(r is not None for r in resolved_links):
                    target_ids = []
                    break

        if not target_ids:
            unresolved.append(
                UnresolvedTradeOrDrop(
                    table="droptable", subject=drop.item, reason="the item name did not resolve"
                )
            )
            continue
        # Looting 0 is the unenchanted kill, which is the honest default for a
        # panel that shows one number. The wiki records every level, and
        # `MobDrop.at_looting` is how a later looting-tier display reads them.
        count, odds = _drop_odds(drop.at_looting(0))
        for target_id in target_ids:
            producers.append(
                Producer(
                    method=ObtainMethod.MOB_LOOT,
                    output=ProducerOutput(item=target_id, count=count),
                    inputs=(),
                    source_id=f"droptable/{drop.page}",
                    note=f"dropped by {drop.mob}",
                    chance=odds[0],
                    count_max=odds[1],
                    per_attempt=odds[2],
                )
            )
    return tuple(producers), tuple(unresolved)


def _drop_odds(
    base: LootingDrop | None,
) -> tuple[int, tuple[float, int, float] | tuple[None, None, None]]:
    """Return `(count, (chance, count_max, per_attempt))` for one looting-0 wiki row.

    The three odds travel as one tuple because `Producer` refuses a partial
    set, so every reason to distrust one of them has to drop all three. A wiki
    row mid-edit is an ordinary event here, not a fault, and the reasons to
    decline are: no looting-0 row at all, a probability outside `(0, 1]`, an
    average of zero, or a range whose ends are crossed.

    `per_attempt` is the wiki's own measured average and never `chance x
    count`. See `Producer`'s docstring: a `0-2` drop already folds its own
    failure into that range, so multiplying would count the failure twice.
    """
    none: tuple[None, None, None] = (None, None, None)
    if base is None:
        return 1, none
    count = max(base.minimum, 1)
    chance = base.drop_chance.value
    average = base.average.value
    if not 0.0 < chance <= 1.0 or average <= 0.0 or base.maximum < count:
        return count, none
    return count, (chance, base.maximum, average)


def producers_from_trade_index(
    trade_index: TradeIndex, *, join_table: JoinTable
) -> tuple[tuple[Producer, ...], tuple[UnresolvedTradeOrDrop, ...]]:
    """Return every `TRADE` producer `trade_index` describes, and what did not resolve.

    Unlike a mob's loot, a trade's inputs are real ingredients: what the
    player hands over (`WikiTrade.wanted`) is itself obtainable, and the tree
    walker expands it exactly like a crafting ingredient. A wanted item that
    does not resolve drops that one input rather than the whole trade -- an
    unresolved emerald price still leaves the rest of the trade informative
    -- but a trade whose *given* item does not resolve is dropped outright
    and reported, because a producer with no output names nothing.
    """
    producers: list[Producer] = []
    unresolved: list[UnresolvedTradeOrDrop] = []
    for trade in trade_index.trades:
        given_id = _resolve(trade.given.item, join_table=join_table, kinds=_ITEM_KINDS)
        if given_id is None:
            unresolved.append(
                UnresolvedTradeOrDrop(
                    table="trade", subject=trade.given.item, reason="the given item did not resolve"
                )
            )
            continue
        inputs: list[ProducerInput] = []
        for item in trade.wanted:
            wanted_id = _resolve(item.item, join_table=join_table, kinds=_ITEM_KINDS)
            if wanted_id is None:
                unresolved.append(
                    UnresolvedTradeOrDrop(
                        table="trade", subject=item.item, reason="a wanted item did not resolve"
                    )
                )
                continue
            inputs.append(
                ProducerInput(item=wanted_id, count=max(item.quantity.minimum, 1))
            )
        producers.append(
            Producer(
                method=ObtainMethod.TRADE,
                output=ProducerOutput(item=given_id, count=max(trade.given.quantity.minimum, 1)),
                inputs=tuple(inputs),
                source_id=f"trade/{trade.page}/{trade.level}",
                station="villager",
                note=f"{trade.profession}, {trade.level}",
            )
        )
    return tuple(producers), tuple(unresolved)
