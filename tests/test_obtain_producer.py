"""The `Producer` node vocabulary, and the determinism `ProducerIndex` guarantees.

`pipeline.emit.write` holds a build to byte-for-byte reproduction between two
runs, and `ProducerIndex.from_producers`/`.merge` are the one place that
ordering is fixed for every adapter downstream of them -- see this module's
own docstring. These tests pin that guarantee directly, along with the
`ProducerInput` shape rule (`TODO.md` Decision 9) that keeps a tagged
ingredient collapsed rather than fanned out.
"""

import pytest

from pipeline.obtain import ObtainError
from pipeline.obtain.producer import (
    ObtainMethod,
    Producer,
    ProducerIndex,
    ProducerInput,
    ProducerOutput,
)


def producer(
    *,
    method: ObtainMethod = ObtainMethod.CRAFTING,
    output: str = "minecraft:oak_stairs",
    source_id: str = "oak_stairs",
) -> Producer:
    return Producer(
        method=method,
        output=ProducerOutput(item=output),
        inputs=(ProducerInput(item="minecraft:oak_planks", count=6),),
        source_id=source_id,
    )


# --- ProducerInput: exactly one of item/tag ---------------------------------


def test_an_input_with_only_an_item_is_valid() -> None:
    assert ProducerInput(item="minecraft:oak_planks").tag is None


def test_an_input_with_only_a_tag_is_valid() -> None:
    value = ProducerInput(tag="minecraft:planks", members=("minecraft:oak_planks",))
    assert value.item is None


def test_an_input_naming_neither_item_nor_tag_raises() -> None:
    with pytest.raises(ObtainError, match="exactly one of item or tag"):
        ProducerInput()


def test_an_input_naming_both_item_and_tag_raises() -> None:
    with pytest.raises(ObtainError, match="exactly one of item or tag"):
        ProducerInput(item="minecraft:oak_planks", tag="minecraft:planks")


def test_a_tag_input_carries_its_resolved_members() -> None:
    """`TODO.md` Decision 9: a tag stays one input, labelled by the tag, not fanned out."""
    value = ProducerInput(
        tag="minecraft:planks",
        members=("minecraft:acacia_planks", "minecraft:oak_planks"),
    )
    assert value.item is None
    assert value.members == ("minecraft:acacia_planks", "minecraft:oak_planks")


# --- ProducerIndex: grouping and lookup --------------------------------------


def test_producers_of_returns_every_producer_of_one_output_item() -> None:
    index = ProducerIndex.from_producers(
        [producer(source_id="a"), producer(source_id="b"), producer(output="minecraft:other")]
    )
    assert {p.source_id for p in index.producers_of("minecraft:oak_stairs")} == {"a", "b"}


def test_producers_of_an_item_with_no_producer_is_empty() -> None:
    index = ProducerIndex.from_producers([])
    assert index.producers_of("minecraft:bedrock") == ()


# --- Determinism: the (method, output id, source_id) sort -------------------


def test_from_producers_sorts_each_output_groups_producers_by_method_then_source_id() -> None:
    """Every output item's own producer list is sorted, independent of insertion order.

    `ProducerIndex.by_output` groups by output item id, so the promised
    `(method, output id, source_id)` order is a property of each group, not
    of concatenating every group's producers in dict-iteration order --
    `producers_of` is the one interface this class actually exposes that
    order through.
    """
    unsorted = [
        producer(method=ObtainMethod.SMELTING, output="minecraft:a", source_id="z"),
        producer(method=ObtainMethod.CRAFTING, output="minecraft:b", source_id="a"),
        producer(method=ObtainMethod.CRAFTING, output="minecraft:a", source_id="b"),
        producer(method=ObtainMethod.CRAFTING, output="minecraft:a", source_id="a"),
    ]
    index = ProducerIndex.from_producers(unsorted)
    assert [(p.method, p.source_id) for p in index.producers_of("minecraft:a")] == [
        (ObtainMethod.CRAFTING, "a"),
        (ObtainMethod.CRAFTING, "b"),
        (ObtainMethod.SMELTING, "z"),
    ]
    assert [(p.method, p.source_id) for p in index.producers_of("minecraft:b")] == [
        (ObtainMethod.CRAFTING, "a"),
    ]


def test_from_producers_sorts_base_recipes_before_dye_recipes() -> None:
    """Base crafting recipes sort before dyeing recipes for the same item."""
    unsorted = [
        producer(
            method=ObtainMethod.CRAFTING,
            output="minecraft:red_bed",
            source_id="minecraft:dye_red_bed",
        ),
        producer(
            method=ObtainMethod.CRAFTING,
            output="minecraft:red_bed",
            source_id="minecraft:red_bed",
        ),
    ]
    index = ProducerIndex.from_producers(unsorted)
    assert [p.source_id for p in index.producers_of("minecraft:red_bed")] == [
        "minecraft:red_bed",
        "minecraft:dye_red_bed",
    ]


def test_from_producers_is_deterministic_regardless_of_input_order() -> None:
    """The same producers, handed in two different orders, sort identically.

    This is the property the byte-for-byte determinism rule of `pipeline.
    emit.write` actually needs: not that sorting works, but that it erases
    whatever order an adapter happened to produce its output in.
    """
    a = producer(source_id="a")
    b = producer(source_id="b")
    c = producer(output="minecraft:other", source_id="c")

    first = ProducerIndex.from_producers([a, b, c])
    second = ProducerIndex.from_producers([c, b, a])
    assert first == second


def test_merge_combines_several_indexes_and_re_sorts() -> None:
    """`pipeline.cli.build` merges one index per adapter; the merge must not just concatenate."""
    left = ProducerIndex.from_producers([producer(source_id="z")])
    right = ProducerIndex.from_producers([producer(source_id="a")])
    merged = ProducerIndex.merge([left, right])
    assert [p.source_id for p in merged.producers_of("minecraft:oak_stairs")] == ["a", "z"]


def test_merge_of_no_indexes_is_empty() -> None:
    assert ProducerIndex.merge([]).by_output == {}


# --- ObtainMethod ------------------------------------------------------------


def test_obtain_method_has_the_sixteen_named_members() -> None:
    """Sixteen methods: crafting, smelting, brewing, filling, mob_loot, chest_loot,
    trade, block_drop, brushing, fishing, bartering, gift, shearing, harvesting,
    using, world_generation.
    """
    assert {member.value for member in ObtainMethod} == {
        "crafting",
        "smelting",
        "brewing",
        "filling",
        "mob_loot",
        "chest_loot",
        "trade",
        "block_drop",
        "brushing",
        "fishing",
        "bartering",
        "gift",
        "shearing",
        "harvesting",
        "using",
        "world_generation",
    }


# --- Producer grid validation ------------------------------------------------


def test_producer_with_valid_grid_is_valid() -> None:
    p = Producer(
        method=ObtainMethod.CRAFTING,
        output=ProducerOutput(item="minecraft:iron_pickaxe"),
        inputs=(
            ProducerInput(item="minecraft:stick"),
            ProducerInput(item="minecraft:iron_ingot"),
        ),
        source_id="iron_pickaxe",
        grid=(1, 1, 1, None, 0, None, None, 0, None),
        grid_width=3,
        grid_height=3,
    )
    assert p.grid_width == 3
    assert p.grid_height == 3
    assert p.grid == (1, 1, 1, None, 0, None, None, 0, None)


def test_producer_with_mismatched_grid_length_raises() -> None:
    with pytest.raises(ObtainError, match="does not match"):
        Producer(
            method=ObtainMethod.CRAFTING,
            output=ProducerOutput(item="minecraft:iron_pickaxe"),
            inputs=(ProducerInput(item="minecraft:stick"),),
            source_id="iron_pickaxe",
            grid=(0, 0),
            grid_width=3,
            grid_height=3,
        )


def test_producer_with_out_of_range_grid_index_raises() -> None:
    with pytest.raises(ObtainError, match="out of range"):
        Producer(
            method=ObtainMethod.CRAFTING,
            output=ProducerOutput(item="minecraft:iron_pickaxe"),
            inputs=(ProducerInput(item="minecraft:stick"),),
            source_id="iron_pickaxe",
            grid=(5,),
            grid_width=1,
            grid_height=1,
        )


def test_producer_with_grid_but_no_width_or_height_raises() -> None:
    with pytest.raises(ObtainError, match="must declare grid_width and grid_height"):
        Producer(
            method=ObtainMethod.CRAFTING,
            output=ProducerOutput(item="minecraft:iron_pickaxe"),
            inputs=(ProducerInput(item="minecraft:stick"),),
            source_id="iron_pickaxe",
            grid=(0,),
        )


def test_producer_without_grid_but_with_width_or_height_raises() -> None:
    with pytest.raises(
        ObtainError, match="without a grid cannot declare grid_width or grid_height"
    ):
        Producer(
            method=ObtainMethod.CRAFTING,
            output=ProducerOutput(item="minecraft:iron_pickaxe"),
            inputs=(ProducerInput(item="minecraft:stick"),),
            source_id="iron_pickaxe",
            grid_width=3,
            grid_height=3,
        )
