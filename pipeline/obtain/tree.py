"""Walk a `ProducerIndex` into one item's obtain tree. The only place the four rules live.

`TODO.md`'s Phase 3 names four structural rules for the unified obtain tree,
and this module is where all four are implemented, once, so that no adapter
(`pipeline.obtain.recipes`, `.loot`, `.brewing`) ever has to know about any
of them -- an adapter only ever emits flat `Producer`s.

1. **Cycle: drop, do not draw.** A path-local visited set carries every
   plain item id between the root and the node currently being expanded.
   When a producer input names an item already on that path, the walker
   emits it as a bare leaf -- no node, no back-reference, no cycle badge --
   and does not recurse into it. The brief is explicit that `iron ingot ->
   iron nugget -> iron ingot` must never reappear in the rendering, and a
   bare leaf is what keeps it from reappearing. If *every* input of one
   producer is a path repeat, the whole producer is dropped, because a
   producer with nothing but repeated ancestors to show teaches a reader
   nothing they were not already looking at.
2. **Memoize on `(item id, remaining depth)`, not on the item id alone.**
   The same item reached with different depth budgets left is not the same
   subtree: a shallow caller's node may be a depth-cap stub while a deeper
   caller's is the real thing, and memoizing on the id alone would hand the
   deep caller the shallow caller's stub. `_first_occurrence` is keyed on
   the pair for exactly this reason -- see `test_obtain_tree.py`'s
   memoization-does-not-leak-a-shallow-answer case.
3. **Depth cap -> expandable stub.** A node whose remaining depth budget has
   reached zero is not expanded at all: it becomes a stub with no producers
   and `expandable=True`, so the web app can continue the walk on its own by
   opening that item's own entity shard, rather than the pipeline building
   an unbounded tree once and shipping it whole.
4. **Repeated-subtree collapse.** The second and later occurrence of an
   `(item id, remaining depth)` pair already computed *elsewhere in the same
   tree* -- not on the current path, which is rule 1's job -- becomes a
   back-reference to the first occurrence's node path, rather than a second
   full copy of the same subtree. This is a diamond, not a loop: legitimate,
   worth showing, and worth showing once. `_first_occurrence` doubles as the
   record of where each key was first rendered, because the same key
   producing the same subtree is exactly what makes the reuse safe -- see
   rule 2's own reasoning for why the key must include the depth.

Producers of one item are walked in `ProducerIndex`'s own order, which is
already the deterministic `(method, output id, source_id)` sort `pipeline.
obtain.producer.ProducerIndex.from_producers` fixes -- this module adds no
sort of its own and relies on that ordering being stable between two runs of
the same build, which is what `pipeline.emit.write`'s byte-for-byte rule
needs.

A tag input, or the untagged-alternatives-list input `pipeline.obtain.
recipes`'s own docstring describes, is never expanded into a subtree of its
own: `TODO.md` Decision 9 collapses it at the producer level already, and
expanding *each* alternative here would silently re-fan it back out one
layer up. Only the alternatives-list shape's representative `item` is even
present to recurse into, and this module leaves it as a leaf too, on
purpose -- the full list survives in `TreeInput.members` for a renderer that
wants to show it, but the tree itself shows one path, not the collapsed
one's cardinality of them.

## Where this module's job ends and Phase 6's begins

This module used to be what the pipeline itself called, once per entity with
at least one producer, from `pipeline.normalize.merge`: the merge stage
walked `build_obtain_tree`'s output into a `RecipeTree` and wrote it into
that entity's own shard. Measured against the real 26.2 data, that cost 73.8
MB raw and 4.1 MB gzipped across the whole build, depth-capped at 4, against
1.05 MB raw and 0.07 MB gzipped for shipping the flat `ProducerIndex` this
module already reads with no depth cap at all -- and the depth cap was
costing real depth, not just bytes: the deepest real producer chain is 15
levels (`minecraft:chiseled_resin_bricks`, height 16), which a cap of 4 never
reaches. `pipeline.emit.obtain`'s module docstring has the full comparison.

So the pipeline no longer calls this module at build time. `pipeline.emit.
obtain.build_obtain_graph` writes the flat graph to `data/dist/obtain.json`,
and the web app -- Phase 6's renderer, written in TypeScript -- reads that
file and walks it into the tree shape a player sees, on demand, the first
time they open an item's Obtaining tab. This module is Python and still runs
only at build time, but no build calls `build_obtain_tree` any more; what it
produces now is the *acceptance spec* the renderer's own walk has to satisfy,
the same role `pipeline.normalize.aliases.rank_candidates` already plays for
Phase 4's matcher -- a small reference implementation of a rule a later
phase, in a different language, has to reimplement against data this phase
already produces. `tests/test_obtain_tree.py` pins this module's own
behaviour, the four rules above, directly. `tests/test_emit_obtain.py` pins
the property that makes shipping the graph instead of the tree safe in the
first place: a `ProducerIndex` serialised through `pipeline.emit.obtain.
build_obtain_graph` exactly as `obtain.json` is written, parsed back with
`pipeline.emit.obtain.producer_index_from_graph`, must build the identical
tree through this module's own `build_obtain_tree` as the original index
does, for every item and at several depths. That test is the one the user's
own condition on shipping the graph instead of the tree asked for outright:
"just confirm that we can make the same obtaining tree in the end." Nothing
about this module's own four rules, or their tests, changes because of any
of this -- the walk this module performs is exactly as correct, and exactly
as tested, as it was before the pipeline stopped calling it itself.
"""

from pydantic import BaseModel

from pipeline.obtain.producer import ObtainMethod, ProducerIndex, ProducerInput

__all__ = [
    "DEFAULT_MAX_DEPTH",
    "ROOT_PATH",
    "ObtainNode",
    "ObtainTree",
    "TreeInput",
    "TreeProducer",
    "build_obtain_tree",
]

# Decided in review, per this task's own brief.
DEFAULT_MAX_DEPTH = 4

ROOT_PATH = "root"


class TreeInput(BaseModel, frozen=True):
    """One ingredient slot of a `TreeProducer`, expanded (or not) into its own node.

    `node` is the recursive expansion of `item`, present exactly when this
    input is a plain item that was neither a path repeat (rule 1) nor a tag
    or alternatives-list leaf. It is `None` for a tag input, for the
    untagged-alternatives-list shape (see the module docstring), and for a
    cycle-dropped repeat -- three different reasons that all read the same
    way to a renderer: nothing more to expand here.
    """

    label: str
    item: str | None = None
    tag: str | None = None
    count: int = 1
    members: tuple[str, ...] = ()
    node: "ObtainNode | None" = None


class TreeProducer(BaseModel, frozen=True):
    """One way to get a node's item, mirroring `pipeline.obtain.producer.Producer`."""

    method: ObtainMethod
    station: str | None = None
    note: str | None = None
    source_id: str
    inputs: tuple[TreeInput, ...] = ()


class ObtainNode(BaseModel, frozen=True):
    """One item of the obtain tree: what makes it, or why the walk stopped here.

    `expandable` marks a depth-cap stub (rule 3): `producers` is empty and
    the web app is expected to continue the walk itself, by opening
    `item`'s own entity shard. `back_reference` marks a repeated-subtree
    collapse (rule 4): `producers` is empty and the value is the
    `ObtainNode` path where this same `(item, remaining depth)` pair was
    first rendered in this tree. A node with neither set and empty
    `producers` is an ordinary leaf: this item genuinely has no known
    producer.
    """

    item: str
    producers: tuple[TreeProducer, ...] = ()
    expandable: bool = False
    back_reference: str | None = None


TreeInput.model_rebuild()


class ObtainTree(BaseModel, frozen=True):
    """The whole obtain tree of one item, rooted at `root`."""

    root: ObtainNode


def _tree_input(
    input_spec: ProducerInput,
    *,
    index: ProducerIndex,
    max_depth: int,
    remaining_depth: int,
    path: frozenset[str],
    first_occurrence: dict[tuple[str, int], str],
    node_path: str,
) -> tuple[TreeInput, bool]:
    """Return one `TreeInput` and whether it was a path repeat (rule 1)."""
    if input_spec.tag is not None:
        label = input_spec.tag
        return (
            TreeInput(
                label=label,
                tag=input_spec.tag,
                count=input_spec.count,
                members=input_spec.members,
            ),
            False,
        )

    item_id = input_spec.item
    assert item_id is not None  # ProducerInput guarantees exactly one of item/tag.

    if item_id in path:
        return TreeInput(label=item_id, item=item_id, count=input_spec.count), True

    child = _build_node(
        item_id,
        index=index,
        max_depth=max_depth,
        remaining_depth=remaining_depth - 1,
        path=path | {item_id},
        first_occurrence=first_occurrence,
        node_path=node_path,
    )
    return (
        TreeInput(
            label=item_id,
            item=item_id,
            count=input_spec.count,
            members=input_spec.members,
            node=child,
        ),
        False,
    )


def _build_node(
    item_id: str,
    *,
    index: ProducerIndex,
    max_depth: int,
    remaining_depth: int,
    path: frozenset[str],
    first_occurrence: dict[tuple[str, int], str],
    node_path: str,
    is_root: bool = False,
) -> ObtainNode:
    """Return the `ObtainNode` of `item_id`, applying all four rules in order.

    `is_root` exempts the very first call `build_obtain_tree` makes from
    rule 3: the depth cap bounds how far the walk recurses *from* the root,
    never the root's own existence, so a caller that asks for `max_depth=0`
    still sees the root's own producers -- it only stops one hop sooner than
    it otherwise would, exactly where `max_depth=1` would already have
    stopped it. Every recursive call below leaves this at its default.
    """
    if remaining_depth <= 0 and not is_root:
        return ObtainNode(item=item_id, expandable=True)

    key = (item_id, remaining_depth)
    earlier_path = first_occurrence.get(key)
    if earlier_path is not None:
        return ObtainNode(item=item_id, back_reference=earlier_path)
    first_occurrence[key] = node_path

    tree_producers: list[TreeProducer] = []
    for producer in index.producers_of(item_id):
        # Rule 1's "drop the whole producer" test runs *before* any recursion,
        # for two reasons that both surfaced as one bug.
        #
        # Whether an input is a path repeat is knowable without walking it --
        # it is a set membership test against `path` -- so deciding first
        # costs nothing. Deciding afterwards cost two things. The node path
        # woven into a back-reference (rule 4) was built from the producer's
        # index in `producers_of`, which counts producers this loop then
        # dropped, so every producer after a dropped one was addressed one
        # slot too high and its back-references pointed at a producer that
        # does not exist in the emitted tree. And a producer that was walked
        # and then dropped still left its subtree's keys in
        # `first_occurrence`, so a later back-reference could name a path
        # inside a subtree that was never emitted at all.
        #
        # `len(tree_producers)` below is the index this producer will actually
        # occupy, which is the number the web app can index by. The two are
        # the same number only because nothing is dropped after this point.
        repeats = [
            input_spec.item is not None and input_spec.item in path
            for input_spec in producer.inputs
        ]
        if producer.inputs and all(repeats):
            continue

        producer_index = len(tree_producers)
        inputs: list[TreeInput] = []
        for input_index, input_spec in enumerate(producer.inputs):
            tree_input, _ = _tree_input(
                input_spec,
                index=index,
                max_depth=max_depth,
                remaining_depth=remaining_depth,
                path=path,
                first_occurrence=first_occurrence,
                node_path=f"{node_path}.producers.{producer_index}.inputs.{input_index}",
            )
            inputs.append(tree_input)

        tree_producers.append(
            TreeProducer(
                method=producer.method,
                station=producer.station,
                note=producer.note,
                source_id=producer.source_id,
                inputs=tuple(inputs),
            )
        )

    return ObtainNode(item=item_id, producers=tuple(tree_producers))


def build_obtain_tree(
    item_id: str, index: ProducerIndex, *, max_depth: int = DEFAULT_MAX_DEPTH
) -> ObtainTree:
    """Return the obtain tree of `item_id`, walking `index` under the four rules above.

    `max_depth` bounds how many levels of producer-input expansion the tree
    holds before a node becomes an expandable stub (rule 3); the root itself
    is depth 0 and always shows its own producers regardless of `max_depth`,
    since the cap bounds recursion *from* the root, not the root's own
    existence.
    """
    return ObtainTree(
        root=_build_node(
            item_id,
            index=index,
            max_depth=max_depth,
            remaining_depth=max_depth,
            path=frozenset({item_id}),
            first_occurrence={},
            node_path=ROOT_PATH,
            is_root=True,
        )
    )
