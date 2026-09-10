"""Tests for pipeline.collections.facts."""

from pipeline.collections.facts import extract_fact
from pipeline.normalize.entity import (
    ApplicableItems,
    EnchantInfo,
    Entity,
    EntityKind,
    EntityRef,
    FoodInfo,
    IntegerRange,
    SourceTier,
)


def _minimal_entity(**overrides: object) -> Entity:
    fields: dict[str, object] = {
        "id": "minecraft:apple",
        "kind": EntityKind.ITEM,
        "name": "Apple",
        "aliases": (),
        "sourceTiers": {"name": SourceTier.A},
        "sections": (),
    }
    fields.update(overrides)
    return Entity.model_validate(fields)


def test_extract_food_nutrition_and_saturation() -> None:
    apple = _minimal_entity(
        sections=(
            FoodInfo(
                nutrition=4,
                saturation=2.4,
            ),
        )
    )
    assert extract_fact(apple, "food.nutrition") == "4"
    assert extract_fact(apple, "food.saturation") == "2.4"


def test_extract_fact_missing_section_returns_empty_string() -> None:
    apple = _minimal_entity(sections=())
    assert extract_fact(apple, "food.nutrition") == ""
    assert extract_fact(apple, "food.saturation") == ""
    assert extract_fact(apple, "enchant.maxLevel") == ""


def test_extract_fact_none_value_returns_empty_string() -> None:
    food_with_none = _minimal_entity(
        sections=(
            FoodInfo(
                nutrition=None,
                saturation=None,
            ),
        )
    )
    assert extract_fact(food_with_none, "food.nutrition") == ""
    assert extract_fact(food_with_none, "food.saturation") == ""


def test_extract_fact_unknown_key_returns_empty_string() -> None:
    apple = _minimal_entity(sections=(FoodInfo(nutrition=4, saturation=2.4),))
    assert extract_fact(apple, "unknown.fact") == ""


def test_extract_enchant_max_level() -> None:
    sharpness = _minimal_entity(
        id="minecraft:sharpness",
        kind=EntityKind.ENCHANTMENT,
        name="Sharpness",
        sections=(
            EnchantInfo(
                max_level=5,
                weight=10,
                rarity="common",
                anvil_cost=1,
                cost_ranges=(IntegerRange(minimum=1, maximum=21),),
                supported_items=ApplicableItems(
                    group="weapons",
                    items=(EntityRef(id="minecraft:diamond_sword", name="Diamond Sword"),),
                ),
            ),
        ),
    )
    assert extract_fact(sharpness, "enchant.maxLevel") == "5"
