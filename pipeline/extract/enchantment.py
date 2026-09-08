"""Extract enchantment data and tag relationships from the vanilla data pack.

Tier A enchantment data comes from `data/minecraft/enchantment/<id>.json` (43 files)
and `data/minecraft/tags/enchantment/` in the pinned mcmeta `data` archive.

This module extracts:
1. Max level (int 1-5).
2. Anvil cost multiplier (int 1, 2, 4, 8).
3. Weight (int 10, 5, 2, 1) and derived rarity (common, uncommon, rare, very_rare).
4. Equipment slots where the enchantment is active.
5. Modified enchantment level cost ranges for each level:
   `base + per_level_above_first * (L - 1)` for both min_cost and max_cost.
6. Applicable items:
   - `supported_items`: item tag or list of items accepted by an anvil.
   - `primary_items`: item tag or list of items offered in the enchanting table,
     kept only when it differs from `supported_items`.
7. Exclusive set:
   Enchantments that cannot be combined on the same item, resolved through tags or
   item lists, with the enchantment itself removed from its own conflict list.
8. Classification tags:
   `treasure`, `curse`, and `tradeable` read from `tags/enchantment/`.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from pipeline.extract import ExtractError
from pipeline.extract.tags import TagIndex
from pipeline.fetch import FetchError, decode_json
from pipeline.normalize.entity import IntegerRange

__all__ = [
    "ENCHANTMENT_DIRECTORY",
    "WEIGHT_TO_RARITY",
    "EnchantIndex",
    "EnchantSlot",
    "EnchantmentFacts",
    "extract_enchantments",
]

ENCHANTMENT_DIRECTORY = "enchantment"

EnchantSlot = Literal[
    "any",
    "armor",
    "feet",
    "hand",
    "head",
    "legs",
    "mainhand",
    "offhand",
]

EnchantRarity = Literal["common", "uncommon", "rare", "very_rare"]

WEIGHT_TO_RARITY: Mapping[int, EnchantRarity] = {
    10: "common",
    5: "uncommon",
    2: "rare",
    1: "very_rare",
}


def _group_name_from_tag(tag: str) -> str:
    """Return the display group name from a tag identifier."""
    raw = tag[1:] if tag.startswith("#") else tag
    return raw.split(":", 1)[-1]


def _resolve_item_set(
    value: str | Sequence[str] | None,
    item_tags: TagIndex,
    *,
    source: str,
) -> tuple[str, frozenset[str]]:
    """Resolve an item tag, single item ID, or list of item IDs into (group_name, item_ids)."""
    if value is None:
        return ("", frozenset())

    if isinstance(value, str):
        if value.startswith("#"):
            tag_ref = value[1:]
            group = _group_name_from_tag(value)
            return (group, item_tags.resolve(tag_ref))
        single_id = value if ":" in value else f"minecraft:{value}"
        group = single_id.split(":", 1)[-1]
        return (group, frozenset({single_id}))

    if isinstance(value, Sequence):
        ids: set[str] = set()
        for entry in value:
            if not isinstance(entry, str):
                raise ExtractError(f"{source} holds a non-string item entry {entry!r}")
            if entry.startswith("#"):
                ids.update(item_tags.resolve(entry[1:]))
            else:
                single_id = entry if ":" in entry else f"minecraft:{entry}"
                ids.add(single_id)
        return ("custom", frozenset(ids))

    raise ExtractError(f"{source} has invalid item set format: {type(value).__name__}")


def _resolve_enchantment_set(
    value: str | Sequence[str] | None,
    enchant_tags: TagIndex,
    *,
    source: str,
) -> frozenset[str]:
    """Resolve an enchantment tag, single enchantment ID, or list of enchantment IDs."""
    if value is None:
        return frozenset()

    if isinstance(value, str):
        if value.startswith("#"):
            return enchant_tags.resolve(value[1:])
        single_id = value if ":" in value else f"minecraft:{value}"
        return frozenset({single_id})

    if isinstance(value, Sequence):
        ids: set[str] = set()
        for entry in value:
            if not isinstance(entry, str):
                raise ExtractError(f"{source} holds a non-string enchantment entry {entry!r}")
            if entry.startswith("#"):
                ids.update(enchant_tags.resolve(entry[1:]))
            else:
                single_id = entry if ":" in entry else f"minecraft:{entry}"
                ids.add(single_id)
        return frozenset(ids)

    raise ExtractError(f"{source} has invalid exclusive set format: {type(value).__name__}")


class EnchantmentFacts(BaseModel, frozen=True):
    """The complete extracted facts of one enchantment from Tier A data."""

    id: str
    max_level: int
    anvil_cost: int
    weight: int
    rarity: EnchantRarity
    slots: tuple[EnchantSlot, ...]
    cost_ranges: tuple[IntegerRange, ...]
    supported_items_group: str
    supported_items: tuple[str, ...]
    primary_items_group: str | None = None
    primary_items: tuple[str, ...] | None = None
    exclusive_set: tuple[str, ...] = ()
    treasure: bool = False
    curse: bool = False
    tradeable: bool = True


@dataclass(frozen=True)
class EnchantIndex:
    """All enchantments extracted from Tier A data, indexed by namespaced ID."""

    by_id: dict[str, EnchantmentFacts] = field(default_factory=dict)

    def __getitem__(self, key: str) -> EnchantmentFacts:
        return self.by_id[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.by_id)

    def __len__(self) -> int:
        return len(self.by_id)

    def __contains__(self, key: object) -> bool:
        return key in self.by_id

    def get(self, key: str, default: Any = None) -> Any:
        return self.by_id.get(key, default)

    def items(self) -> Any:
        return self.by_id.items()

    def values(self) -> Any:
        return self.by_id.values()


def extract_enchantments(
    files: Mapping[str, bytes],
    *,
    item_tags: TagIndex | None = None,
    enchant_tags: TagIndex | None = None,
) -> EnchantIndex:
    """Extract every enchantment from `files`, resolving item and enchantment tags.

    `files` is the mapping returned by `fetch_data_files`.
    `item_tags` and `enchant_tags` may be supplied by tests; otherwise they are
    constructed from `files`.
    """
    prefix = f"{ENCHANTMENT_DIRECTORY}/"
    enchant_files = {path: data for path, data in files.items() if path.startswith(prefix)}
    if not enchant_files:
        raise ExtractError(
            f"the archive holds no enchantment files under {prefix!r}. "
            "An empty read is a broken scrape, not a game with no enchantments."
        )

    resolved_item_tags = item_tags if item_tags is not None else TagIndex(files, registry="item")
    resolved_enchant_tags = (
        enchant_tags if enchant_tags is not None else TagIndex(files, registry="enchantment")
    )

    treasure_set = (
        resolved_enchant_tags.resolve("minecraft:treasure")
        if resolved_enchant_tags.holds("minecraft:treasure")
        else frozenset()
    )
    curse_set = (
        resolved_enchant_tags.resolve("minecraft:curse")
        if resolved_enchant_tags.holds("minecraft:curse")
        else frozenset()
    )
    tradeable_set = (
        resolved_enchant_tags.resolve("minecraft:tradeable")
        if resolved_enchant_tags.holds("minecraft:tradeable")
        else frozenset()
    )

    by_id: dict[str, EnchantmentFacts] = {}

    for path, payload in sorted(enchant_files.items()):
        enchant_name = path.removeprefix(prefix).removesuffix(".json")
        enchant_id = f"minecraft:{enchant_name}"

        try:
            doc: Any = decode_json(payload, source=path)
        except FetchError as error:
            raise ExtractError(str(error)) from error

        if not isinstance(doc, dict):
            raise ExtractError(f"{path} does not hold a JSON object at top level")

        try:
            max_level = int(doc["max_level"])
            anvil_cost = int(doc["anvil_cost"])
            weight = int(doc["weight"])
        except (KeyError, ValueError, TypeError) as err:
            raise ExtractError(f"{path} is missing required integer fields: {err}") from err

        rarity = WEIGHT_TO_RARITY.get(weight)
        if rarity is None:
            raise ExtractError(f"{path} has unknown enchantment weight {weight}")

        slots_raw = doc.get("slots", [])
        if not isinstance(slots_raw, list):
            raise ExtractError(f"{path} slots field is not a list")
        slots = tuple(str(s) for s in slots_raw)

        min_cost = doc.get("min_cost")
        max_cost = doc.get("max_cost")
        if not isinstance(min_cost, dict) or not isinstance(max_cost, dict):
            raise ExtractError(f"{path} is missing min_cost or max_cost object")

        try:
            min_base = int(min_cost["base"])
            min_step = int(min_cost.get("per_level_above_first", 0))
            max_base = int(max_cost["base"])
            max_step = int(max_cost.get("per_level_above_first", 0))
        except (KeyError, ValueError, TypeError) as err:
            raise ExtractError(f"{path} has malformed cost definition: {err}") from err

        cost_ranges = tuple(
            IntegerRange(
                minimum=min_base + min_step * level_offset,
                maximum=max_base + max_step * level_offset,
            )
            for level_offset in range(max_level)
        )

        sup_group, sup_items = _resolve_item_set(
            doc.get("supported_items"), resolved_item_tags, source=path
        )
        if not sup_items:
            raise ExtractError(f"{path} resolved to an empty supported_items set")

        pri_group: str | None = None
        pri_items_tuple: tuple[str, ...] | None = None
        if "primary_items" in doc and doc["primary_items"] is not None:
            candidate_group, candidate_items = _resolve_item_set(
                doc["primary_items"], resolved_item_tags, source=path
            )
            # Only keep primary_items if it differs from supported_items
            if candidate_items != sup_items:
                pri_group = candidate_group
                pri_items_tuple = tuple(sorted(candidate_items))

        # Exclusive set conflicts, filtering out the enchantment itself
        raw_conflicts = _resolve_enchantment_set(
            doc.get("exclusive_set"), resolved_enchant_tags, source=path
        )
        filtered_conflicts = tuple(sorted(raw_conflicts - {enchant_id}))

        by_id[enchant_id] = EnchantmentFacts(
            id=enchant_id,
            max_level=max_level,
            anvil_cost=anvil_cost,
            weight=weight,
            rarity=rarity,
            slots=slots,  # type: ignore[arg-type]
            cost_ranges=cost_ranges,
            supported_items_group=sup_group,
            supported_items=tuple(sorted(sup_items)),
            primary_items_group=pri_group,
            primary_items=pri_items_tuple,
            exclusive_set=filtered_conflicts,
            treasure=enchant_id in treasure_set,
            curse=enchant_id in curse_set,
            tradeable=enchant_id in tradeable_set,
        )

    return EnchantIndex(by_id=by_id)
