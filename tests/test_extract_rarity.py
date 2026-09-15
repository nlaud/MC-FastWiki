"""`pipeline.extract.rarity`: item display rarity tiers, read from `minecraft:rarity`.

Every payload here is built in memory, one rule per test, matching
`tests/test_extract_food.py`.
"""

import pytest

from pipeline.extract import ExtractError
from pipeline.extract.rarity import (
    ItemRarity,
    extract_rarity,
)


def _payload(**items: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return an `item_components` payload holding exactly `items`."""
    return dict(items)


def test_reads_item_rarity_tiers() -> None:
    facts = extract_rarity(
        _payload(
            apple={"minecraft:rarity": "common"},
            conduit={"minecraft:rarity": "uncommon"},
            beacon={"minecraft:rarity": "rare"},
            command_block={"minecraft:rarity": "epic"},
        )
    )

    assert facts["minecraft:apple"] is ItemRarity.COMMON
    assert facts["minecraft:conduit"] is ItemRarity.UNCOMMON
    assert facts["minecraft:beacon"] is ItemRarity.RARE
    assert facts["minecraft:command_block"] is ItemRarity.EPIC


def test_the_answer_is_keyed_by_the_namespaced_id_not_the_unprefixed_path() -> None:
    facts = extract_rarity(_payload(beacon={"minecraft:rarity": "rare"}))

    assert "minecraft:beacon" in facts
    assert "beacon" not in facts


def test_items_without_rarity_component_are_omitted() -> None:
    facts = extract_rarity(
        _payload(
            stone={},
            beacon={"minecraft:rarity": "rare"},
        )
    )

    assert "minecraft:beacon" in facts
    assert "minecraft:stone" not in facts


def test_payload_must_be_a_mapping() -> None:
    with pytest.raises(ExtractError, match="the item_components payload must be a JSON object"):
        extract_rarity(["apple"])  # type: ignore[arg-type]


def test_components_entry_must_be_a_mapping() -> None:
    with pytest.raises(ExtractError, match="the components of 'beacon' must be a JSON object"):
        extract_rarity(_payload(beacon="rare"))  # type: ignore[arg-type]


def test_rarity_value_must_be_a_string() -> None:
    with pytest.raises(ExtractError, match="the rarity component of 'beacon' must be a string"):
        extract_rarity(_payload(beacon={"minecraft:rarity": 123}))


def test_unknown_rarity_tier_raises_extract_error() -> None:
    with pytest.raises(ExtractError, match="the rarity component of 'beacon' is 'mythic'"):
        extract_rarity(_payload(beacon={"minecraft:rarity": "mythic"}))


def test_empty_payload_raises_extract_error() -> None:
    with pytest.raises(ExtractError, match="item_components declares no item rarity at all"):
        extract_rarity({})
