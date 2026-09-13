"""Tests for pipeline.collections.facts."""

from pipeline.collections.facts import extract_fact
from pipeline.normalize.entity import (
    ApplicableItems,
    ChestLoot,
    ChestLootContainer,
    ChestLootItem,
    EnchantInfo,
    Entity,
    EntityKind,
    EntityRef,
    FoodInfo,
    IntegerRange,
    ProfessionInfo,
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


def test_extract_chest_containers_and_distinct_items() -> None:
    city = _minimal_entity(
        id="minecraft:ancient_city",
        name="Ancient City",
        kind=EntityKind.STRUCTURE,
        sections=(
            ChestLoot(
                containers=(
                    ChestLootContainer(
                        label="Chest",
                        items=(
                            ChestLootItem(
                                item=EntityRef(id="minecraft:echo_shard", name="Echo Shard"),
                                chance=0.298,
                                stack_range=IntegerRange(minimum=1, maximum=3),
                            ),
                            ChestLootItem(
                                item=EntityRef(
                                    id="minecraft:disc_fragment_5", name="Disc Fragment"
                                ),
                                chance=0.298,
                                stack_range=IntegerRange(minimum=1, maximum=3),
                            ),
                        ),
                    ),
                    ChestLootContainer(
                        label="Ice Box",
                        items=(
                            ChestLootItem(
                                item=EntityRef(id="minecraft:echo_shard", name="Echo Shard"),
                                chance=0.1,
                                stack_range=IntegerRange(minimum=1, maximum=1),
                            ),
                            ChestLootItem(
                                item=EntityRef(id="minecraft:packed_ice", name="Packed Ice"),
                                chance=0.5,
                                stack_range=IntegerRange(minimum=1, maximum=4),
                            ),
                        ),
                    ),
                )
            ),
        ),
    )
    # 2 containers, 3 distinct items (echo_shard, disc_fragment_5, packed_ice)
    assert extract_fact(city, "chest.containers") == "2"
    assert extract_fact(city, "chest.items") == "3"


def test_extract_profession_workstation_and_trade_count() -> None:
    armorer = _minimal_entity(
        id="minecraft:armorer",
        name="Armorer",
        kind=EntityKind.PROFESSION,
        sections=(
            ProfessionInfo(
                workstation=EntityRef(id="minecraft:blast_furnace", name="Blast Furnace"),
                trade_count=18,
            ),
        ),
    )
    assert extract_fact(armorer, "profession.workstation") == "Blast Furnace"
    assert extract_fact(armorer, "profession.tradeCount") == "18"


def test_extract_bartering_odds_single_and_merged() -> None:
    from pipeline.obtain.producer import ObtainMethod, Producer, ProducerIndex, ProducerOutput

    blackstone = _minimal_entity(id="minecraft:blackstone", name="Blackstone")
    potion = _minimal_entity(id="minecraft:potion", name="Potion")

    prod_bs = Producer(
        method=ObtainMethod.BARTERING,
        output=ProducerOutput(item="minecraft:blackstone", count=8),
        inputs=(),
        source_id="gameplay/piglin_bartering.json",
        chance=40 / 469,
        count_max=16,
        per_attempt=480 / 469,
    )
    prod_pot1 = Producer(
        method=ObtainMethod.BARTERING,
        output=ProducerOutput(item="minecraft:potion", count=1),
        inputs=(),
        source_id="gameplay/piglin_bartering.json",
        chance=10 / 469,
        count_max=1,
        per_attempt=10 / 469,
    )
    prod_pot2 = Producer(
        method=ObtainMethod.BARTERING,
        output=ProducerOutput(item="minecraft:potion", count=1),
        inputs=(),
        source_id="gameplay/piglin_bartering.json",
        chance=8 / 469,
        count_max=1,
        per_attempt=8 / 469,
    )
    index = ProducerIndex.from_producers([prod_bs, prod_pot1, prod_pot2])

    assert extract_fact(blackstone, "obtain.chance", producer_index=index) == "8.529%"
    assert extract_fact(blackstone, "obtain.stackRange", producer_index=index) == "8-16"
    assert extract_fact(blackstone, "obtain.perAttempt", producer_index=index) == "1.023"

    assert extract_fact(potion, "obtain.chance", producer_index=index) == "3.838%"
    assert extract_fact(potion, "obtain.stackRange", producer_index=index) == "1"
    assert extract_fact(potion, "obtain.perAttempt", producer_index=index) == "0.038"

