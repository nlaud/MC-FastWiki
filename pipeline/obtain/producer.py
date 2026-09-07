"""The one node vocabulary every obtain source reduces to.

`pipeline.obtain.recipes`, `pipeline.obtain.loot`, and `pipeline.obtain.brewing`
each read a different upstream shape and each emit `Producer`s -- one way to
get one item, from crafting, smelting, brewing, a mob kill, a chest, a trade,
or breaking a block. `pipeline.obtain.tree` never reads a recipe JSON file or
a wiki table; it only ever reads `Producer`s through a `ProducerIndex`, which
is what lets one walker (`pipeline.obtain.tree.build_obtain_tree`) implement
cycle handling, memoization, the depth cap, and repeated-subtree collapse
exactly once, instead of once per source.

## Why a tag input stays collapsed

`TODO.md` Decision 9 renders crafting collapsed -- "Wooden Stairs -- any plank
type" rather than thirteen near-identical rows -- and the same reasoning
applies one layer down, to the *ingredient* side of a recipe. A recipe whose
key resolves through `#minecraft:planks` accepts all thirteen wood planks, and
fanning that out into thirteen `ProducerInput`s (or, worse, thirteen
`Producer`s, one per wood type) would multiply every recipe that touches a
tagged ingredient by the size of the tag, for no reader who wants "how do I
get oak stairs" and not "here are thirteen ways, spelled out." So a tag input
stays *one* `ProducerInput`, labelled by the tag itself, and `members` records
what it resolved to -- the collapsed list a renderer can still expand if it
wants to, without the tree walker ever treating it as thirteen separate
inputs.

## Determinism

`pipeline.emit.write` holds the whole build to byte-for-byte reproduction
between two runs, and nothing here reads in a stable order by accident: mcmeta
files come off a `dict[str, bytes]` whose iteration order is insertion order
of a gzip archive walk, which is stable within one archive but says nothing
about ordering *across* producers of the same item gathered from several
sources. `ProducerIndex.from_producers` is the one place that sorts, once, by
`(method, output item id, source_id)` -- the tuple `TODO.md`'s own read of
Phase 3 names -- so every caller downstream of it, including `build_obtain_
tree`, sees the same order on every run regardless of which adapter happened
to run first.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, model_validator

from pipeline.obtain import ObtainError

__all__ = [
    "ObtainMethod",
    "Producer",
    "ProducerIndex",
    "ProducerInput",
    "ProducerOutput",
]


class ObtainMethod(StrEnum):
    """How one `Producer` turns its inputs into its output.

    Sixteen methods. There is no separate member for stonecutting or smithing:
    both are crafting-like -- a player stands at a station and trades items
    for one result, with no randomness -- and `Producer.station` already
    carries which station (`"stonecutter"`, `"smithing_table"`) without the
    enum needing a member for every station a recipe type happens to use.

    `FILLING` describes a world interaction where a player right-clicks a
    source block, cauldron, or mob with a container and gets a filled one
    back. It covers filling bottles (water) and buckets (water, lava, powder
    snow, milk, mob buckets).

    `USING` describes a player action at no station that consumes an item and
    returns a different one (e.g. signing a writable book into a written book).
    Stretching `FILLING` to cover it would contradict that method's focus on
    filling a container from an in-world source.

    `WORLD_GENERATION` covers items found placed in generated structures without
    inputs or loot tables (e.g. an elytra in an End Ship item frame, or naturally
    generated decorated pots in Trial Chambers yielding pottery sherds). On web,
    these render alongside chest loot in the Natural Generation source group.

    The six loot-table world interaction methods (`BRUSHING`, `FISHING`,
    `BARTERING`, `GIFT`, `SHEARING`, `HARVESTING`) earn their own enum members
    because each represents a fundamentally distinct player action and verb
    rather than a station variant. Having distinct members allows the renderer
    to name the verb directly without parsing unstructured note prose.
    `BRUSHING` covers both suspicious blocks (`minecraft:archaeology`) and
    entities (`minecraft:entity_interact`), mirroring how stonecutting and
    smithing share `CRAFTING`.
    """

    CRAFTING = "crafting"
    SMELTING = "smelting"
    BREWING = "brewing"
    FILLING = "filling"
    MOB_LOOT = "mob_loot"
    CHEST_LOOT = "chest_loot"
    TRADE = "trade"
    BLOCK_DROP = "block_drop"
    BRUSHING = "brushing"
    FISHING = "fishing"
    BARTERING = "bartering"
    GIFT = "gift"
    SHEARING = "shearing"
    HARVESTING = "harvesting"
    USING = "using"
    WORLD_GENERATION = "world_generation"



class ProducerOutput(BaseModel, frozen=True):
    """What one `Producer` makes, and how many."""

    item: str
    count: int = 1


class ProducerInput(BaseModel, frozen=True):
    """One ingredient slot of a `Producer`, an item, a tag, or an untagged alternatives list.

    Exactly one of `item` or `tag` is set for the two shapes `TODO.md` Decision
    9 names outright: a plain item (`item` set, `tag` `None`, `members` empty),
    or a `#`-prefixed tag (`tag` set to the tag id, `item` `None`, `members`
    holding what `pipeline.extract.tags.TagIndex.resolve` returned for it, so a
    caller never has to re-resolve the tag to see what it covers).

    A third, narrower shape exists for a recipe ingredient mcmeta writes as a
    bare JSON list of items with no tag id at all -- `pipeline.obtain.recipes`'s
    own docstring names where this appears. There is no tag id to label such an
    input by, so `item` is set to the alphabetically-first alternative and
    `members` still carries the full sorted list, which keeps the model's
    two-field shape (`item` xor `tag`) intact while losing none of the
    alternatives a renderer might want to show.
    """

    item: str | None = None
    tag: str | None = None
    count: int = 1
    members: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _exactly_one_of_item_or_tag(self) -> "ProducerInput":
        """Refuse an input that names both an item and a tag, or neither."""
        if (self.item is None) == (self.tag is None):
            raise ObtainError(
                f"a producer input must name exactly one of item or tag, and this one names "
                f"item={self.item!r} tag={self.tag!r}."
            )
        return self


class Producer(BaseModel, frozen=True):
    """One way to get `output`, from `inputs`, by `method`.

    `source_id` names where this producer came from -- a recipe path such as
    `oak_stairs`, a loot table path, a brewing rule's own description -- so a
    report can point at the exact upstream row a bad producer traces back to.
    `station` names the block or entity the player uses, where one applies:
    `"furnace"`, `"blast_furnace"`, `"smoker"`, `"campfire"`, `"stonecutter"`,
    `"smithing_table"`, `"brewing_stand"`. `note` carries a qualifier a
    renderer should show but that changes no field's shape: `"requires silk
    touch"`, `"requires looting"`.

    ## The three odds fields, and when they are absent

    `chance`, `count_max` and `per_attempt` describe a producer whose outcome
    is a draw rather than a certainty: opening a chest, reeling in a catch,
    trading a gold ingot to a piglin, killing a mob. `chance` is the
    probability the drop happens at all on one attempt, `count_max` is the top
    of the stack size (`output.count` already carries the bottom), and
    `per_attempt` is the expected number of items one attempt yields. What an
    "attempt" *is* differs by method -- one chest, one catch, one barter, one
    kill -- and the renderer names it from `method` rather than this model
    carrying a noun.

    `per_attempt` is stored rather than derived because the two adapters that
    fill it know different things and `chance x average count` is only right
    for one of them. `pipeline.obtain.loot` multiplies a pool weight by the
    pool's roll count and the mean stack size, because that is exactly what a
    loot table states. `pipeline.obtain.loot.producers_from_drop_index` instead
    copies the wiki's own measured average, because a mob drop's quantity range
    starts at zero when the drop can fail, and multiplying a chance by the mean
    of a range that already includes the failure would count the failure twice.
    Deriving in the renderer would force one formula onto both and quietly
    misstate every `0-N` mob drop.

    All three are `None` together, and that absence is meaningful rather than
    missing. A weight only describes an outcome when the entry competes in a
    plain weighted pool, so `pipeline.obtain.loot` declines to compute odds
    for an entry that sits under `minecraft:alternatives`, `minecraft:group`
    or `minecraft:sequence` -- where the game picks by condition rather than
    by weight -- and for an entry carrying `conditions` of its own, whose real
    probability is the weight times the odds of the condition holding, a
    number no loot table states. Refusing there is the same rule this package
    already applies to an unrecognized entry type: a number this data does not
    support is not a number to invent.
    """

    method: ObtainMethod
    output: ProducerOutput
    inputs: tuple[ProducerInput, ...]
    source_id: str
    station: str | None = None
    note: str | None = None
    chance: float | None = None
    count_max: int | None = None
    per_attempt: float | None = None
    grid: tuple[int | None, ...] | None = None
    grid_width: int | None = None
    grid_height: int | None = None

    @model_validator(mode="after")
    def _validate_odds(self) -> "Producer":
        """Refuse a partial or out-of-range set of the three odds fields.

        They are one fact in three parts, so a producer carrying some of them
        describes a draw it cannot state the odds of, which is worse than one
        carrying none: a renderer reading `chance` alone would print a
        percentage with no quantity beside it.
        """
        present = (
            self.chance is not None,
            self.count_max is not None,
            self.per_attempt is not None,
        )
        if any(present) and not all(present):
            raise ObtainError(
                f"chance, count_max and per_attempt are one fact in three parts and must be "
                f"set together, and {self.source_id!r} sets chance={self.chance!r} "
                f"count_max={self.count_max!r} per_attempt={self.per_attempt!r}."
            )
        if self.chance is not None and not (0.0 < self.chance <= 1.0):
            raise ObtainError(
                f"a producer chance is a probability in (0, 1], and {self.source_id!r} "
                f"declares {self.chance!r}."
            )
        if self.per_attempt is not None and self.per_attempt <= 0.0:
            raise ObtainError(
                f"a producer that yields nothing on an average attempt is not a producer, "
                f"and {self.source_id!r} declares per_attempt={self.per_attempt!r}."
            )
        if self.count_max is not None and self.count_max < self.output.count:
            raise ObtainError(
                f"a producer count_max is the top of the range whose bottom is output.count, "
                f"and {self.source_id!r} declares count_max={self.count_max} against "
                f"output.count={self.output.count}."
            )
        return self

    @model_validator(mode="after")
    def _validate_grid(self) -> "Producer":
        if self.grid is not None:
            if self.grid_width is None or self.grid_height is None:
                raise ObtainError("a producer with a grid must declare grid_width and grid_height.")
            if len(self.grid) != self.grid_width * self.grid_height:
                raise ObtainError(
                    f"a producer grid of length {len(self.grid)} does not match "
                    f"grid_width={self.grid_width} * grid_height={self.grid_height}."
                )
            num_inputs = len(self.inputs)
            for idx in self.grid:
                if idx is not None and not (0 <= idx < num_inputs):
                    raise ObtainError(
                        f"grid cell index {idx} is out of range for {num_inputs} inputs."
                    )
        else:
            if self.grid_width is not None or self.grid_height is not None:
                raise ObtainError(
                    "a producer without a grid cannot declare grid_width or grid_height."
                )
        return self


def _sort_key(producer: Producer) -> tuple[str, str, int, str]:
    """Return the deterministic sort key for one producer.

    Base crafting recipes sort before dyeing/recoloring recipes
    (source_id starting with 'minecraft:dye_' or 'dye_'), so canonical
    construction (e.g. wool + planks for beds) leads ahead of recoloring.
    """
    is_dye = (
        1
        if (
            producer.source_id.startswith("minecraft:dye_")
            or producer.source_id.startswith("dye_")
        )
        else 0
    )
    return (producer.method.value, producer.output.item, is_dye, producer.source_id)


class ProducerIndex(BaseModel, frozen=True):
    """Every `Producer` this build found, indexed by the item id it produces.

    Wraps a `Mapping[str, tuple[Producer, ...]]` rather than exposing the
    mapping directly, so `producers_of` can return an empty tuple for an item
    with no known producer instead of a caller writing `.get(item_id, ())`
    everywhere `pipeline.obtain.tree` reads this index.
    """

    by_output: Mapping[str, tuple[Producer, ...]]

    def producers_of(self, item_id: str) -> tuple[Producer, ...]:
        """Return every producer of `item_id`, in the deterministic sort order."""
        return self.by_output.get(item_id, ())

    @classmethod
    def from_producers(cls, producers: Sequence[Producer]) -> "ProducerIndex":
        """Return an index over `producers`, grouped by output item id and sorted.

        Sorted once, here, by `(method, output item id, source_id)` -- see the
        module docstring's determinism section for why this is the one place
        that ordering is fixed, rather than leaving each adapter to sort its
        own output and hoping the concatenation stays stable.
        """
        grouped: dict[str, list[Producer]] = {}
        for producer in sorted(producers, key=_sort_key):
            grouped.setdefault(producer.output.item, []).append(producer)
        return cls(by_output={item: tuple(group) for item, group in grouped.items()})

    @classmethod
    def merge(cls, indexes: Sequence["ProducerIndex"]) -> "ProducerIndex":
        """Return one index over every producer of `indexes`, re-sorted.

        Each adapter (`pipeline.obtain.recipes`, `.loot`, `.brewing`) builds
        its own `ProducerIndex`; `pipeline.cli.build` merges them into the one
        index `build_obtain_tree` reads. Re-sorting rather than concatenating
        keeps the ordering guarantee independent of which adapter ran first.
        """
        all_producers = [
            producer
            for index in indexes
            for group in index.by_output.values()
            for producer in group
        ]
        return cls.from_producers(all_producers)
