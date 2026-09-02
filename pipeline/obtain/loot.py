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
2. Silk touch is never `condition: "minecraft:tool/can_silk_touch"`. It is
   `condition: "minecraft:match_tool"` whose `predicate.predicates.
   "minecraft:enchantments"` array names `"minecraft:silk_touch"` with a
   `levels.min` of at least 1 -- verified on `diamond_ore.json` and
   `coal_ore.json`, both of which pair a silk-touch-gated "drop the block
   itself" entry with an unconditioned, fortune-scaled "drop the raw
   resource" entry inside one `minecraft:alternatives` wrapper.

Entries nest through `minecraft:alternatives`, `minecraft:group`, and
`minecraft:sequence`, each carrying a `children` array of more entries,
verified on the block tables above. A flat read of `pools[].entries[]` alone
would miss every drop gated by a condition, which on the live ore tables is
half of them. The walk here recurses through all three container types and
collects every `type: "minecraft:item"` leaf, in the order it meets them, and
records whether a silk-touch condition governs it, from any depth of the
containers above it.

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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from pipeline.enrich.droptable import DropIndex
from pipeline.enrich.resource_location import JoinTable, ResourceLocation
from pipeline.enrich.trade import TradeIndex
from pipeline.obtain import ObtainError
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerInput, ProducerOutput

__all__ = [
    "BLOCK_LOOT_DIRECTORY",
    "CHEST_LOOT_DIRECTORY",
    "SILK_TOUCH_ENCHANTMENT",
    "LootExtractionResult",
    "SkippedLootEntry",
    "UnresolvedTradeOrDrop",
    "extract_block_and_chest_loot",
    "producers_from_drop_index",
    "producers_from_trade_index",
]

BLOCK_LOOT_DIRECTORY = "loot_table/blocks"
CHEST_LOOT_DIRECTORY = "loot_table/chests"
NAMESPACE = "minecraft"

# The container entry types that hold more entries, verified live on
# `diamond_ore.json`. `minecraft:group` and `minecraft:sequence` were not
# observed on the sample read for this task, but they share `children`'s
# shape in the loot table specification and cost nothing to walk the same way.
_CONTAINER_TYPES = frozenset(
    {"minecraft:alternatives", "minecraft:group", "minecraft:sequence"}
)
_ITEM_TYPE = "minecraft:item"

SILK_TOUCH_ENCHANTMENT = "minecraft:silk_touch"

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


class UnresolvedTradeOrDrop(BaseModel, frozen=True):
    """One Tier B row whose display name did not resolve to exactly one registry ID."""

    table: str
    subject: str
    reason: str


class LootExtractionResult(BaseModel, frozen=True):
    """Every producer `extract_block_and_chest_loot` built, and what it skipped."""

    producers: tuple[Producer, ...]
    skipped: tuple[SkippedLootEntry, ...]


def _namespaced(value: str) -> str:
    return value if ":" in value else f"{NAMESPACE}:{value}"


def _entry_count(entry: Mapping[str, Any]) -> int:
    """Return the minimum count a `minecraft:item` leaf entry declares.

    Reads `functions[]` for a `minecraft:set_count` function -- see the
    module docstring's first correction for its real shape. `count` there is
    either a bare integer or a `{"type": "minecraft:uniform", "min", "max"}`
    object; this returns the floor of it, because a `Producer.output.count`
    is one integer and the minimum is the guaranteed amount, never an
    overstatement. No `set_count` function at all means the game's own
    default of one.
    """
    functions = entry.get("functions")
    if not isinstance(functions, list):
        return 1
    for function in functions:
        if not isinstance(function, Mapping) or function.get("function") != "minecraft:set_count":
            continue
        count = function.get("count", 1)
        if isinstance(count, int):
            return max(count, 1)
        if isinstance(count, Mapping):
            minimum = count.get("min", 1)
            if isinstance(minimum, int | float):
                return max(int(minimum), 1)
        return 1
    return 1


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


def _entry_has_silk_touch_condition(entry: Mapping[str, Any]) -> bool:
    conditions = entry.get("conditions")
    if not isinstance(conditions, list):
        return False
    return any(
        isinstance(condition, Mapping) and _condition_is_silk_touch(condition)
        for condition in conditions
    )


def _walk_entries(
    entries: Sequence[Any],
    *,
    silk_touch: bool,
    source: str,
    skipped: list[SkippedLootEntry],
) -> list[tuple[str, int, bool]]:
    """Return every `(item id, count, silk_touch)` leaf reachable from `entries`.

    `silk_touch` carries whether an ancestor container already gated this
    branch on silk touch, so a leaf under `minecraft:alternatives` inherits
    its parent's gate rather than each recursion re-deriving it.
    """
    found: list[tuple[str, int, bool]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ObtainError(f"{source} holds a loot entry of {entry!r}, not an object.")
        entry_type = entry.get("type")
        if not isinstance(entry_type, str):
            raise ObtainError(f"{source} holds a loot entry with no 'type'.")
        gated = silk_touch or _entry_has_silk_touch_condition(entry)
        if entry_type in _CONTAINER_TYPES:
            children = entry.get("children")
            if not isinstance(children, list):
                raise ObtainError(f"{source} holds a {entry_type} entry with no 'children' list.")
            found.extend(_walk_entries(children, silk_touch=gated, source=source, skipped=skipped))
        elif entry_type == _ITEM_TYPE:
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ObtainError(f"{source} holds an item entry with no 'name'.")
            found.append((_namespaced(name), _entry_count(entry), gated))
        else:
            skipped.append(
                SkippedLootEntry(
                    table=source,
                    entry_type=entry_type,
                    reason="this entry type names no single concrete item",
                )
            )
    return found


def _table_entries(document: Mapping[str, Any], *, source: str) -> list[Any]:
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
    entries: list[Any] = []
    for pool in pools:
        if not isinstance(pool, Mapping):
            raise ObtainError(f"{source} holds a pool of {pool!r}, not an object.")
        pool_entries = pool.get("entries")
        if not isinstance(pool_entries, list):
            raise ObtainError(f"{source} holds a pool with no 'entries' list.")
        entries.extend(pool_entries)
    return entries


def extract_block_and_chest_loot(files: Mapping[str, bytes]) -> LootExtractionResult:
    """Return every `BLOCK_DROP` and `CHEST_LOOT` producer of `files`.

    `files` is the answer of `pipeline.fetch.mcmeta.fetch_data_files`. A
    `BLOCK_DROP` producer's one input is the block itself, named from the
    file path -- breaking `diamond_ore.json` needs the block `minecraft:
    diamond_ore`, and the tree walker expands that block's own producers (or
    reports it a leaf) exactly as it would any other item. A `CHEST_LOOT`
    producer carries no inputs: nothing is spent to open a naturally
    generated chest, so it is a leaf of the tree by construction, matching
    `pipeline.obtain.tree`'s own reading of a zero-input producer.

    Raises `ObtainError` on a malformed table of either directory, and when
    neither directory holds a file at all.
    """
    block_entries = {k: v for k, v in files.items() if k.startswith(f"{BLOCK_LOOT_DIRECTORY}/")}
    chest_entries = {k: v for k, v in files.items() if k.startswith(f"{CHEST_LOOT_DIRECTORY}/")}
    if not block_entries and not chest_entries:
        raise ObtainError(
            f"no file under {BLOCK_LOOT_DIRECTORY!r} or {CHEST_LOOT_DIRECTORY!r} was found. "
            f"An empty read is a broken scrape, not a version of Minecraft with no loot."
        )

    producers: list[Producer] = []
    skipped: list[SkippedLootEntry] = []

    for key in sorted(block_entries):
        block_path = key[len(BLOCK_LOOT_DIRECTORY) + 1 : -len(".json")]
        block_id = _namespaced(block_path)
        document = _decoded(block_entries[key], source=key)
        for item_id, count, silk_touch in _walk_entries(
            _table_entries(document, source=key), silk_touch=False, source=key, skipped=skipped
        ):
            producers.append(
                Producer(
                    method=ObtainMethod.BLOCK_DROP,
                    output=ProducerOutput(item=item_id, count=count),
                    inputs=(ProducerInput(item=block_id),),
                    source_id=key,
                    note="requires silk touch" if silk_touch else None,
                )
            )

    for key in sorted(chest_entries):
        document = _decoded(chest_entries[key], source=key)
        for item_id, count, _silk_touch in _walk_entries(
            _table_entries(document, source=key), silk_touch=False, source=key, skipped=skipped
        ):
            producers.append(
                Producer(
                    method=ObtainMethod.CHEST_LOOT,
                    output=ProducerOutput(item=item_id, count=count),
                    inputs=(),
                    source_id=key,
                )
            )

    return LootExtractionResult(producers=tuple(producers), skipped=tuple(skipped))


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

    A name that reaches none of the three is reported rather than guessed at.
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
    return _one_id(by_page)


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
        if item_id is None:
            unresolved.append(
                UnresolvedTradeOrDrop(
                    table="droptable", subject=drop.item, reason="the item name did not resolve"
                )
            )
            continue
        producers.append(
            Producer(
                method=ObtainMethod.MOB_LOOT,
                output=ProducerOutput(item=item_id),
                inputs=(),
                source_id=f"droptable/{drop.page}",
                note=f"dropped by {drop.mob}",
            )
        )
    return tuple(producers), tuple(unresolved)


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
