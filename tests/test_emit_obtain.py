"""`build_obtain_graph`: the flat `obtain.json` payload built from a `ProducerIndex`.

Two kinds of test live here. The first handful, mirroring `tests/
test_emit_search_index.py`'s own style, pin the wire shape of one producer and
one input: the short keys, which fields are omitted when absent, and that the
graph carries no `min_length` the way `SearchIndex.entities` does.

The second, `test_the_round_trip_survives_every_shape_and_rebuilds_the_same_
trees`, is the test this whole restructuring stands or falls on. The user's
one condition on shipping the flat graph instead of a materialised tree was
"just confirm that we can make the same obtaining tree in the end," and this
is that confirmation, made mechanical: build a `ProducerIndex` that exercises
crafting, brewing, a tag input, a cycle, and a diamond that forces a
back-reference; serialise it through `build_obtain_graph` and a real
`json.dumps`/`json.loads` round trip, exactly the bytes `pipeline.emit.write`
would produce; rebuild a `ProducerIndex` from the parsed result with
`producer_index_from_graph`; and assert that `pipeline.obtain.tree.
build_obtain_tree` gives byte-identical trees from the original index and the
round-tripped one, for every item this fixture names, at several depths. If a
future change to either conversion direction ever drops a field the tree walk
needs, this test is the one that has to fail.
"""

import json

from pipeline.emit.obtain import (
    ChestSource,
    ObtainGraph,
    ObtainProducer,
    ObtainProducerInput,
    build_obtain_graph,
    producer_index_from_graph,
)
from pipeline.obtain.producer import (
    ObtainMethod,
    Producer,
    ProducerIndex,
    ProducerInput,
    ProducerOutput,
)
from pipeline.obtain.tree import build_obtain_tree


def make(
    output: str,
    *inputs: tuple[str, int],
    source_id: str,
    method: ObtainMethod = ObtainMethod.CRAFTING,
    count: int = 1,
    station: str | None = None,
    note: str | None = None,
) -> Producer:
    """Build one `Producer` from plain-item inputs. Mirrors `tests/test_obtain_tree.py`'s
    own helper."""
    return Producer(
        method=method,
        output=ProducerOutput(item=output, count=count),
        inputs=tuple(ProducerInput(item=item, count=item_count) for item, item_count in inputs),
        source_id=source_id,
        station=station,
        note=note,
    )


# --- Wire shape: the short keys, and what is omitted -------------------------


def test_a_producer_carries_every_field_under_its_short_key() -> None:
    index = ProducerIndex.from_producers(
        [
            make(
                "minecraft:gunpowder",
                ("minecraft:emerald", 3),
                source_id="fake_gunpowder_recipe",
                count=4,
                station="crafting_table",
                note="requires silk touch",
            )
        ]
    )
    graph = build_obtain_graph(index)
    (producer,) = graph.producers["minecraft:gunpowder"]

    assert producer.method is ObtainMethod.CRAFTING
    assert producer.count == 4
    assert producer.source_id == "fake_gunpowder_recipe"
    assert producer.station == "crafting_table"
    assert producer.note == "requires silk touch"
    (one_input,) = producer.inputs
    assert one_input.item == "minecraft:emerald"
    assert one_input.count == 3

    dumped = graph.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["producers"]["minecraft:gunpowder"] == [
        {
            "m": "crafting",
            "c": 4,
            "src": "fake_gunpowder_recipe",
            "st": "crafting_table",
            "nt": "requires silk touch",
            "in": [{"i": "minecraft:emerald", "c": 3, "mb": []}],
        }
    ]


def test_station_and_note_are_omitted_from_the_wire_shape_when_absent() -> None:
    index = ProducerIndex.from_producers(
        [make("minecraft:stick", ("minecraft:oak_planks", 2), source_id="stick_from_planks")]
    )
    graph = build_obtain_graph(index)
    dumped = graph.model_dump(mode="json", by_alias=True, exclude_none=True)
    (producer,) = dumped["producers"]["minecraft:stick"]
    assert "st" not in producer
    assert "nt" not in producer


def test_grid_fields_are_emitted_when_present_and_omitted_when_absent() -> None:
    producer_with_grid = Producer(
        method=ObtainMethod.CRAFTING,
        output=ProducerOutput(item="minecraft:iron_pickaxe"),
        inputs=(
            ProducerInput(item="minecraft:stick", count=2),
            ProducerInput(item="minecraft:iron_ingot", count=3),
        ),
        source_id="iron_pickaxe",
        grid=(1, 1, 1, None, 0, None, None, 0, None),
        grid_width=3,
        grid_height=3,
    )
    producer_without_grid = make("minecraft:stick", ("minecraft:oak_planks", 2), source_id="stick")
    index = ProducerIndex.from_producers([producer_with_grid, producer_without_grid])
    graph = build_obtain_graph(index)
    dumped = graph.model_dump(mode="json", by_alias=True, exclude_none=True)

    pickaxe = dumped["producers"]["minecraft:iron_pickaxe"][0]
    assert pickaxe["g"] == [1, 1, 1, None, 0, None, None, 0, None]
    assert pickaxe["gw"] == 3
    assert pickaxe["gh"] == 3

    stick = dumped["producers"]["minecraft:stick"][0]
    assert "g" not in stick
    assert "gw" not in stick
    assert "gh" not in stick


def test_sources_map_is_emitted_and_sorted() -> None:
    sources = {
        "loot_table/chests/simple_dungeon.json": ChestSource(
            structure="Dungeon", container="Chest"
        ),
        "loot_table/chests/abandoned_mineshaft.json": ChestSource(
            structure="Mineshaft", container="Chest"
        ),
    }
    graph = build_obtain_graph(ProducerIndex.from_producers([]), sources=sources)
    dumped = graph.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert list(dumped["sources"].keys()) == [
        "loot_table/chests/abandoned_mineshaft.json",
        "loot_table/chests/simple_dungeon.json",
    ]
    assert dumped["sources"]["loot_table/chests/abandoned_mineshaft.json"] == {
        "structure": "Mineshaft",
        "container": "Chest",
    }


def test_a_tag_input_carries_no_item_and_carries_its_members() -> None:
    index = ProducerIndex.from_producers(
        [
            Producer(
                method=ObtainMethod.CRAFTING,
                output=ProducerOutput(item="minecraft:oak_stairs"),
                inputs=(
                    ProducerInput(
                        tag="minecraft:planks",
                        members=("minecraft:oak_planks", "minecraft:spruce_planks"),
                    ),
                ),
                source_id="oak_stairs",
            )
        ]
    )
    graph = build_obtain_graph(index)
    (producer,) = graph.producers["minecraft:oak_stairs"]
    (tag_input,) = producer.inputs
    assert tag_input.item is None
    assert tag_input.tag == "minecraft:planks"
    assert tag_input.members == ("minecraft:oak_planks", "minecraft:spruce_planks")

    dumped_input = (
        graph.model_dump(mode="json", by_alias=True, exclude_none=True)["producers"][
            "minecraft:oak_stairs"
        ][0]["in"][0]
    )
    assert "i" not in dumped_input
    assert dumped_input["t"] == "minecraft:planks"


def test_a_producer_has_no_field_naming_what_it_produces() -> None:
    """The output item is the dict key it sits under in `ObtainGraph.producers`, never repeated."""
    assert set(ObtainProducer.model_fields) == {
        "method",
        "count",
        "source_id",
        "station",
        "note",
        "chance",
        "count_max",
        "per_attempt",
        "inputs",
        "grid",
        "grid_width",
        "grid_height",
    }


def test_the_graph_carries_schema_version_one_by_default() -> None:
    graph = build_obtain_graph(ProducerIndex.from_producers([]))
    assert graph.schema_version == 1
    assert graph.model_dump(mode="json", by_alias=True)["schemaVersion"] == 1


def test_an_empty_producer_index_is_not_refused() -> None:
    """Unlike `SearchIndex.entities`, `ObtainGraph.producers` carries no `min_length`.

    See `ObtainGraph`'s own docstring: a build over fixtures with no recipe,
    loot, or brewing data wired up genuinely has no producers to report, and
    `pipeline.emit.write.emit_build`'s own default `producer_index` relies on
    that being a valid, empty graph rather than a build fault.
    """
    graph = build_obtain_graph(ProducerIndex.from_producers([]))
    assert graph.producers == {}


def test_a_producer_can_be_constructed_by_its_python_names_or_by_its_wire_aliases() -> None:
    by_name = ObtainProducer(method=ObtainMethod.CRAFTING, source_id="src")
    by_alias = ObtainProducer.model_validate({"m": "crafting", "src": "src"})
    assert by_name == by_alias

    by_name_input = ObtainProducerInput(item="minecraft:emerald", count=3)
    by_alias_input = ObtainProducerInput.model_validate({"i": "minecraft:emerald", "c": 3})
    assert by_name_input == by_alias_input


def test_producers_are_sorted_by_item_id_regardless_of_index_insertion_order() -> None:
    index = ProducerIndex.from_producers(
        [
            make("minecraft:zombie_head", ("minecraft:zombie", 1), source_id="src_z"),
            make("minecraft:apple", ("minecraft:apple_tree", 1), source_id="src_a"),
        ]
    )
    graph = build_obtain_graph(index)
    assert list(graph.producers) == ["minecraft:apple", "minecraft:zombie_head"]


# --- The round trip: the property that makes shipping the graph safe ---------


def _fixture_index() -> ProducerIndex:
    """Build a `ProducerIndex` exercising crafting, brewing, a tag input, a cycle, and a diamond."""
    return ProducerIndex.from_producers(
        [
            # A diamond: two crafting producers of `root`, both needing `x` at
            # the same remaining depth, so the second occurrence collapses to
            # a back-reference -- the shape `tests/test_obtain_tree.py`'s own
            # diamond test exercises.
            make("minecraft:root", ("minecraft:x", 1), source_id="root_from_x_v1"),
            make("minecraft:root", ("minecraft:x", 2), source_id="root_from_x_v2"),
            # `x` is reachable two ways: a plain expansion, and through a
            # crafting producer with a tag input.
            make("minecraft:x", ("minecraft:raw", 1), source_id="x_from_raw"),
            make("minecraft:x", ("minecraft:handle", 1), source_id="x_from_handle"),
            Producer(
                method=ObtainMethod.CRAFTING,
                output=ProducerOutput(item="minecraft:handle"),
                inputs=(
                    ProducerInput(
                        tag="minecraft:planks",
                        members=("minecraft:oak_planks", "minecraft:spruce_planks"),
                    ),
                ),
                source_id="handle_from_planks",
            ),
            # Brewing, standalone from the crafting tree above.
            Producer(
                method=ObtainMethod.BREWING,
                output=ProducerOutput(item="minecraft:potion/weakness"),
                inputs=(
                    ProducerInput(item="minecraft:potion/awkward"),
                    ProducerInput(item="minecraft:fermented_spider_eye"),
                ),
                source_id="brew_weakness",
                station="brewing_stand",
            ),
            # A cycle, standalone: rule 1 of `pipeline.obtain.tree` must drop
            # it the same way whichever `ProducerIndex` builds the tree.
            make(
                "minecraft:iron_ingot", ("minecraft:iron_nugget", 9), source_id="ingot_from_nuggets"
            ),
            make(
                "minecraft:iron_nugget", ("minecraft:iron_ingot", 1), source_id="nugget_from_ingot"
            ),
        ]
    )


def test_the_round_trip_survives_every_shape_and_rebuilds_the_same_trees() -> None:
    """Serialise, parse, rebuild, and compare -- the user's own condition on this restructuring.

    The intermediate `json.dumps`/`json.loads` step is load-bearing, not
    decoration: it is what proves the property holds for `obtain.json` as it
    is actually written and read, not merely for two Python objects that
    happen to compare equal in memory.
    """
    original_index = _fixture_index()
    graph = build_obtain_graph(original_index)

    wire_text = json.dumps(
        graph.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        ensure_ascii=False,
    )
    parsed_graph = ObtainGraph.model_validate(json.loads(wire_text))
    restored_index = producer_index_from_graph(parsed_graph)

    items = (
        "minecraft:root",
        "minecraft:x",
        "minecraft:handle",
        "minecraft:potion/weakness",
        "minecraft:iron_ingot",
        "minecraft:iron_nugget",
        # An item the fixture names nowhere as a producer output: both
        # indexes must agree it is an ordinary, producer-less leaf too.
        "minecraft:bedrock",
    )
    for item in items:
        for max_depth in (2, 4, 15):
            original_tree = build_obtain_tree(item, original_index, max_depth=max_depth)
            restored_tree = build_obtain_tree(item, restored_index, max_depth=max_depth)
            assert original_tree == restored_tree, (
                f"{item!r} at max_depth={max_depth} diverged after a round trip through obtain.json"
            )


def test_the_round_trip_is_not_vacuously_true() -> None:
    """Guard the guard: the fixture must actually reach every shape it claims to.

    A round-trip test that silently exercised only plain leaves would pass
    for the wrong reason. This pins that the fixture's `ProducerIndex`
    genuinely produces a back-reference (the diamond), an expandable stub
    (the depth cap), and a dropped cycle producer, so the equality assertions
    above are actually comparing trees with structure in them.
    """
    index = _fixture_index()
    tree = build_obtain_tree("minecraft:root", index, max_depth=2)

    first_x = tree.root.producers[0].inputs[0]
    second_x = tree.root.producers[1].inputs[0]
    assert first_x.node is not None
    assert first_x.node.back_reference is None
    assert second_x.node is not None
    assert second_x.node.back_reference is not None  # the diamond collapsed

    shallow_tree = build_obtain_tree("minecraft:root", index, max_depth=1)
    shallow_x = shallow_tree.root.producers[0].inputs[0]
    assert shallow_x.node is not None
    assert shallow_x.node.expandable is True  # the depth cap fired

    ingot_tree = build_obtain_tree("minecraft:iron_ingot", index, max_depth=4)
    nugget_node = ingot_tree.root.producers[0].inputs[0].node
    assert nugget_node is not None
    assert nugget_node.producers == ()  # the cycle's only producer was dropped


def test_build_obtain_graph_includes_curated_sources() -> None:
    """build_obtain_graph merges world_generation sources from data/curated/producers.json."""
    graph = build_obtain_graph(ProducerIndex.from_producers(()))
    assert "world_generation/end_ship/elytra" in graph.sources
    elytra_src = graph.sources["world_generation/end_ship/elytra"]
    assert elytra_src.structure == "End Ship"
    assert elytra_src.container == "Item Frame"
