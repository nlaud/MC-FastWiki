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


def test_extract_obtain_found_in_structure() -> None:
    from pipeline.obtain.chests import ChestSource
    from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput

    bolt = _minimal_entity(
        id="minecraft:bolt_armor_trim_smithing_template", name="Bolt Armor Trim"
    )
    producer = Producer(
        method=ObtainMethod.CHEST_LOOT,
        output=ProducerOutput(item="minecraft:bolt_armor_trim_smithing_template", count=1),
        inputs=(),
        source_id="chests/trial_chambers/reward_unique.json",
    )
    index = ProducerIndex.from_producers([producer])
    sources = {
        "chests/trial_chambers/reward_unique.json": ChestSource(
            structure="Trial Chambers", container="Chest"
        )
    }

    assert (
        extract_fact(bolt, "obtain.foundIn", producer_index=index, sources=sources)
        == "Trial Chambers"
    )


def test_extract_obtain_found_in_drops_crafting() -> None:
    from pipeline.obtain.chests import ChestSource
    from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput

    bolt = _minimal_entity(
        id="minecraft:bolt_armor_trim_smithing_template", name="Bolt Armor Trim"
    )
    crafting = Producer(
        method=ObtainMethod.CRAFTING,
        output=ProducerOutput(item="minecraft:bolt_armor_trim_smithing_template", count=2),
        inputs=(),
        source_id="crafting/bolt_armor_trim.json",
    )
    loot = Producer(
        method=ObtainMethod.CHEST_LOOT,
        output=ProducerOutput(item="minecraft:bolt_armor_trim_smithing_template", count=1),
        inputs=(),
        source_id="chests/trial_chambers.json",
    )
    index = ProducerIndex.from_producers([crafting, loot])
    sources = {
        "chests/trial_chambers.json": ChestSource(structure="Trial Chambers", container="Chest")
    }

    assert (
        extract_fact(bolt, "obtain.foundIn", producer_index=index, sources=sources)
        == "Trial Chambers"
    )


def test_extract_obtain_found_in_note_fallback() -> None:
    from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput

    tide = _minimal_entity(
        id="minecraft:tide_armor_trim_smithing_template", name="Tide Armor Trim"
    )
    crafting = Producer(
        method=ObtainMethod.CRAFTING,
        output=ProducerOutput(item="minecraft:tide_armor_trim_smithing_template", count=2),
        inputs=(),
        source_id="crafting/tide_armor_trim.json",
    )
    mob_drop = Producer(
        method=ObtainMethod.MOB_LOOT,
        output=ProducerOutput(item="minecraft:tide_armor_trim_smithing_template", count=1),
        inputs=(),
        source_id="droptable/Elder Guardian",
        note="dropped by Elder Guardian",
    )
    index = ProducerIndex.from_producers([crafting, mob_drop])

    assert (
        extract_fact(tide, "obtain.foundIn", producer_index=index, sources={})
        == "dropped by Elder Guardian"
    )


def test_extract_obtain_found_in_multiple_structures() -> None:
    from pipeline.obtain.chests import ChestSource
    from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput

    item = _minimal_entity(id="minecraft:test_item", name="Test Item")
    prod1 = Producer(
        method=ObtainMethod.CHEST_LOOT,
        output=ProducerOutput(item="minecraft:test_item", count=1),
        inputs=(),
        source_id="chest_a",
    )
    prod2 = Producer(
        method=ObtainMethod.CHEST_LOOT,
        output=ProducerOutput(item="minecraft:test_item", count=1),
        inputs=(),
        source_id="chest_b",
    )
    prod3 = Producer(
        method=ObtainMethod.CHEST_LOOT,
        output=ProducerOutput(item="minecraft:test_item", count=1),
        inputs=(),
        source_id="chest_c",
    )
    index = ProducerIndex.from_producers([prod1, prod2, prod3])
    sources = {
        "chest_a": ChestSource(structure="Woodland Mansion", container="Chest"),
        "chest_b": ChestSource(structure="Ancient City", container="Chest"),
        "chest_c": ChestSource(structure="Ancient City", container="Chest"),  # duplicate
    }

    assert (
        extract_fact(item, "obtain.foundIn", producer_index=index, sources=sources)
        == "Ancient City, Woodland Mansion"
    )


def test_extract_obtain_found_in_empty_when_no_producers() -> None:
    item = _minimal_entity(id="minecraft:test_item", name="Test Item")
    assert extract_fact(item, "obtain.foundIn") == ""

