"""`pipeline.extract.rarity`: item display rarity tiers, read from `minecraft:rarity`.

The stage is a pure function from the decoded `item_components/data.json` payload
to a mapping of namespaced item IDs to their `ItemRarity` tier.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pipeline.extract import ExtractError

__all__ = [
    "RARITY_COMPONENT",
    "ItemRarity",
    "extract_rarity",
]

RARITY_COMPONENT = "minecraft:rarity"
VANILLA_NAMESPACE = "minecraft"


class ItemRarity(StrEnum):
    """The four Minecraft Java Edition item rarity tiers."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"


def _require_mapping(value: Any, *, subject: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtractError(f"{subject} must be a JSON object, got {type(value).__name__}.")
    return value


def extract_rarity(payload: Mapping[str, Any]) -> dict[str, ItemRarity]:
    """Return the display rarity tier for every item that declares `minecraft:rarity`.

    `payload` is the decoded `item_components/data.json` of the pinned mcmeta
    `summary` branch. Its keys are unprefixed item paths, and the answer this
    function returns is keyed by the namespaced item ID, in ID order.

    An item is in the answer when it has a `minecraft:rarity` component whose
    value names a known `ItemRarity` tier (`common`, `uncommon`, `rare`, `epic`).

    Every fault raises `ExtractError`: a payload that is not an object, a
    component map that is not an object, a rarity tier that is not a string or
    names an unknown tier, and an answer that holds no rarity at all.
    """
    items = _require_mapping(payload, subject="the item_components payload")

    facts: dict[str, ItemRarity] = {}
    for path in sorted(items):
        components = _require_mapping(items[path], subject=f"the components of {path!r}")
        item = f"{VANILLA_NAMESPACE}:{path}"

        if RARITY_COMPONENT not in components:
            continue

        raw_rarity = components[RARITY_COMPONENT]
        if not isinstance(raw_rarity, str):
            got = type(raw_rarity).__name__
            raise ExtractError(
                f"the rarity component of {path!r} must be a string, got {got}."
            )

        try:
            rarity = ItemRarity(raw_rarity)
        except ValueError:
            valid = ", ".join(repr(member.value) for member in ItemRarity)
            raise ExtractError(
                f"the rarity component of {path!r} is {raw_rarity!r}, which is not one of {valid}."
            ) from None

        facts[item] = rarity

    if not facts:
        raise ExtractError(
            "item_components declares no item rarity at all. An empty read is a "
            "broken fetch, not a version of Minecraft where items have no rarity."
        )
    return facts
