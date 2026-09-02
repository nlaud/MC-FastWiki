"""`pipeline.obtain.tree`: the walker, and the only place the four structural rules live.

Every rule `TODO.md`'s Phase 3 names gets its own regression test here,
against a small, hand-built `ProducerIndex` -- no adapter, no socket.
"""

from pipeline.obtain.producer import (
    ObtainMethod,
    Producer,
    ProducerIndex,
    ProducerInput,
    ProducerOutput,
)
from pipeline.obtain.tree import DEFAULT_MAX_DEPTH, ObtainNode, build_obtain_tree


def make(
    output: str,
    *inputs: tuple[str, int],
    source_id: str,
    method: ObtainMethod = ObtainMethod.CRAFTING,
) -> Producer:
    return Producer(
        method=method,
        output=ProducerOutput(item=output),
        inputs=tuple(ProducerInput(item=item, count=count) for item, count in inputs),
        source_id=source_id,
    )


def node_for(node: ObtainNode, item: str) -> ObtainNode:
    """Return the single child node whose item is `item`, from `node`'s first producer's inputs."""
    for producer in node.producers:
        for one_input in producer.inputs:
            if one_input.item == item and one_input.node is not None:
                return one_input.node
    raise AssertionError(f"no expanded child node for {item!r} under {node.item!r}")


# --- Rule 1: cycle, drop, do not draw ------------------------------------------


def test_the_iron_ingot_nugget_cycle_does_not_reappear() -> None:
    """The brief's own example: iron ingot -> iron nugget -> iron ingot must not render."""
    index = ProducerIndex.from_producers(
        [
            make(
                "minecraft:iron_ingot",
                ("minecraft:iron_nugget", 9),
                source_id="ingot_from_nuggets",
            ),
            make(
                "minecraft:iron_nugget",
                ("minecraft:iron_ingot", 1),
                source_id="nugget_from_ingot",
            ),
        ]
    )
    tree = build_obtain_tree("minecraft:iron_ingot", index)

    nugget_node = node_for(tree.root, "minecraft:iron_nugget")
    # The nugget's own producer's only input is iron_ingot, already on the
    # path -- a path repeat. Its whole (only) producer is dropped, so the
    # nugget node has no producers and, crucially, no node for iron_ingot
    # anywhere under it.
    assert nugget_node.producers == ()


def test_a_producer_with_some_but_not_all_repeated_inputs_keeps_the_others() -> None:
    """Partial repeats stay: only a producer whose *every* input repeats is dropped."""
    index = ProducerIndex.from_producers(
        [
            make("minecraft:a", ("minecraft:b", 1), source_id="a_from_b"),
            make("minecraft:b", ("minecraft:a", 1), ("minecraft:c", 1), source_id="b_from_a_and_c"),
        ]
    )
    tree = build_obtain_tree("minecraft:a", index)
    b_node = node_for(tree.root, "minecraft:b")
    assert len(b_node.producers) == 1
    inputs = {i.item for i in b_node.producers[0].inputs}
    # `a` stays a bare leaf (cycle); `c` expands normally, since it is not a
    # repeat and is not itself producing anything.
    assert inputs == {"minecraft:a", "minecraft:c"}
    c_input = next(i for i in b_node.producers[0].inputs if i.item == "minecraft:c")
    assert c_input.node is not None
    a_input = next(i for i in b_node.producers[0].inputs if i.item == "minecraft:a")
    assert a_input.node is None


# --- Rule 4: repeated-subtree collapse -> back-reference -----------------------


def test_a_diamond_produces_a_back_reference_on_its_second_occurrence() -> None:
    """Two producers of the root, both needing `x` at the same remaining depth: a diamond."""
    index = ProducerIndex.from_producers(
        [
            make("minecraft:root", ("minecraft:x", 1), source_id="p1"),
            make("minecraft:root", ("minecraft:x", 2), source_id="p2"),
            make("minecraft:x", ("minecraft:raw", 1), source_id="x_from_raw"),
        ]
    )
    tree = build_obtain_tree("minecraft:root", index)
    assert len(tree.root.producers) == 2

    first_x = tree.root.producers[0].inputs[0]
    second_x = tree.root.producers[1].inputs[0]
    assert first_x.node is not None
    assert first_x.node.back_reference is None
    assert first_x.node.producers  # the real, fully expanded subtree

    assert second_x.node is not None
    assert second_x.node.back_reference == "root.producers.0.inputs.0"
    assert second_x.node.producers == ()


# --- Rule 3: depth cap -> expandable stub ---------------------------------------


def test_a_node_at_the_depth_cap_becomes_an_expandable_stub_with_no_producers() -> None:
    index = ProducerIndex.from_producers(
        [
            make("minecraft:a", ("minecraft:b", 1), source_id="a_from_b"),
            make("minecraft:b", ("minecraft:c", 1), source_id="b_from_c"),
            make("minecraft:c", ("minecraft:d", 1), source_id="c_from_d"),
        ]
    )
    tree = build_obtain_tree("minecraft:a", index, max_depth=1)
    b_node = node_for(tree.root, "minecraft:b")
    assert b_node.expandable is True
    assert b_node.producers == ()
    assert b_node.back_reference is None


def test_the_root_itself_is_never_capped_regardless_of_max_depth() -> None:
    index = ProducerIndex.from_producers(
        [make("minecraft:a", ("minecraft:b", 1), source_id="a_from_b")]
    )
    tree = build_obtain_tree("minecraft:a", index, max_depth=0)
    assert tree.root.expandable is False
    assert len(tree.root.producers) == 1


def test_the_default_max_depth_is_four() -> None:
    assert DEFAULT_MAX_DEPTH == 4


# --- Rule 2: memoize on (item, remaining depth), not on item alone -----------


def test_memoization_does_not_leak_a_shallow_stub_to_a_deeper_caller() -> None:
    """The case rule 2 exists for: the same item, reached at two different depths.

    `minecraft:a` is reached two ways from root, at two different remaining
    depths: once through `minecraft:via_b` (one extra hop, so `a` is deeper
    and gets capped into a stub), and once directly (one hop closer, so `a`
    is not capped and expands for real). Source ids are chosen so the
    shallower, capped occurrence is walked first -- `ProducerIndex` sorts by
    `(method, output id, source_id)`, and `"p1_via_b"` sorts before
    `"p2_direct"` -- which is exactly the order that would leak a cached
    stub to the deeper caller if memoization keyed on the item id alone.
    """
    index = ProducerIndex.from_producers(
        [
            make("minecraft:root", ("minecraft:via_b", 1), source_id="p1_via_b"),
            make("minecraft:via_b", ("minecraft:a", 1), source_id="via_b_from_a"),
            make("minecraft:root", ("minecraft:a", 1), source_id="p2_direct"),
            make("minecraft:a", ("minecraft:c", 1), source_id="a_from_c"),
        ]
    )
    tree = build_obtain_tree("minecraft:root", index, max_depth=2)

    via_b_node = node_for(tree.root, "minecraft:via_b")
    capped_a = node_for(via_b_node, "minecraft:a")
    assert capped_a.expandable is True
    assert capped_a.producers == ()

    direct_a = node_for(tree.root, "minecraft:a")
    assert direct_a.expandable is False
    assert len(direct_a.producers) == 1
    assert direct_a.back_reference is None


# --- Tag inputs stay collapsed, never expanded --------------------------------


def test_a_tag_input_is_never_expanded_into_a_subtree() -> None:
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
            ),
            make("minecraft:oak_planks", ("minecraft:oak_log", 1), source_id="planks_from_log"),
        ]
    )
    tree = build_obtain_tree("minecraft:oak_stairs", index)
    tag_input = tree.root.producers[0].inputs[0]
    assert tag_input.tag == "minecraft:planks"
    assert tag_input.node is None
    assert tag_input.members == ("minecraft:oak_planks", "minecraft:spruce_planks")


# --- Producer order comes from the index, unchanged -----------------------------


def test_producer_order_within_a_node_matches_the_index_order() -> None:
    index = ProducerIndex.from_producers(
        [
            make(
                "minecraft:a",
                ("minecraft:z", 1),
                source_id="z_source",
                method=ObtainMethod.SMELTING,
            ),
            make("minecraft:a", ("minecraft:y", 1), source_id="y_source"),
        ]
    )
    tree = build_obtain_tree("minecraft:a", index)
    assert [p.source_id for p in tree.root.producers] == ["y_source", "z_source"]


# --- A leaf with no producer at all is a plain, unremarkable node -------------


def test_an_item_with_no_producer_is_an_ordinary_leaf() -> None:
    index = ProducerIndex.from_producers([])
    tree = build_obtain_tree("minecraft:bedrock", index)
    assert tree.root.item == "minecraft:bedrock"
    assert tree.root.producers == ()
    assert tree.root.expandable is False
    assert tree.root.back_reference is None


# --- Rule 4's node paths have to actually resolve ------------------------------


def resolve_node_path(tree_root: ObtainNode, dotted: str) -> ObtainNode:
    """Return the node a rule-4 back-reference addresses, or raise if it does not exist.

    A back-reference is only worth emitting if a reader can follow it, so
    this walks the emitted tree by the same `producers.<i>.inputs.<j>` path
    the walker wrote, indexing the tuples exactly as the web app would.
    """
    parts = dotted.split(".")
    assert parts[0] == "root", f"a node path starts at the root: {dotted!r}"
    node = tree_root
    index = 1
    while index < len(parts):
        assert parts[index] == "producers", dotted
        producer = node.producers[int(parts[index + 1])]
        assert parts[index + 2] == "inputs", dotted
        child = producer.inputs[int(parts[index + 3])].node
        assert child is not None, f"{dotted} passes through an unexpanded input"
        node = child
        index += 4
    return node


def every_back_reference(node: ObtainNode, path: str = "root") -> list[tuple[str, str]]:
    """Return every `(where it sits, what it points at)` back-reference pair below `node`."""
    found: list[tuple[str, str]] = []
    if node.back_reference is not None:
        found.append((path, node.back_reference))
    for producer_index, producer in enumerate(node.producers):
        for input_index, one_input in enumerate(producer.inputs):
            if one_input.node is not None:
                child_path = f"{path}.producers.{producer_index}.inputs.{input_index}"
                found.extend(every_back_reference(one_input.node, child_path))
    return found


def test_a_back_reference_resolves_even_when_rule_1_dropped_an_earlier_producer() -> None:
    """Dropping a producer must not shift the addresses of the ones after it.

    The walker used to number a producer by its position in the index rather
    than by the position it ends up occupying, so any producer sitting after
    one that rule 1 dropped was addressed one slot too high, and every
    back-reference into its subtree pointed at a producer the emitted tree
    does not have. `root` here has a pure-cycle producer first, which rule 1
    drops, and a real one second whose two inputs share a subtree -- so the
    second input is a back-reference into the first, and it has to land.
    """
    index = ProducerIndex.from_producers(
        [
            # Rule 1 drops this one: its only input is the root itself.
            make("minecraft:root", ("minecraft:root", 1), source_id="dropped_by_rule_1"),
            make("minecraft:root", ("minecraft:a", 1), ("minecraft:b", 1), source_id="kept"),
            make("minecraft:a", ("minecraft:shared", 1), source_id="a_source"),
            make("minecraft:b", ("minecraft:shared", 1), source_id="b_source"),
            make("minecraft:shared", ("minecraft:leaf", 1), source_id="shared_source"),
        ]
    )
    tree = build_obtain_tree("minecraft:root", index, max_depth=6)

    assert [p.source_id for p in tree.root.producers] == ["kept"]

    references = every_back_reference(tree.root)
    assert references, "this index is built to produce at least one back-reference"
    for where, target in references:
        resolved = resolve_node_path(tree.root, target)
        assert resolved.back_reference is None, (
            f"the back-reference at {where} points at another back-reference"
        )
        assert resolved.item == resolve_node_path(tree.root, where).item
