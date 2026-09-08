"""Extract natural generation facts from worldgen data pack files.

A block page must answer where and how a block generates in the world: the dimension,
the Y height band, the peak density depth for trapezoid distributions, the placement
attempts per chunk, the vein size, and the biomes that run the feature.

Upstream Minecraft Java data packs express generation across three layers:
1. `worldgen/configured_feature`: what gets placed (the block state and vein configuration).
2. `worldgen/placed_feature`: where and how often (height range/map, count, rarity filters).
3. `worldgen/biome`: which placed features run in that biome across 11 generation steps.

This module covers the five configured feature types that name a block state outright:
`ore`, `simple_block`, `disk`, `scattered_ore`, and `block_blob`. All other feature types
use complex or nested providers (e.g. tree structures, vegetation patches) and are
reported as skipped rows in `data/reports/generation-report.json`.

## One block generates in one dimension per scope, not one dimension overall

Three blocks generate in two dimensions at once: `gravel` (`ore_gravel` plus
`ore_gravel_nether`), and `brown_mushroom` and `red_mushroom`, whose `*_normal`
placed feature is itself listed by three nether biomes as well as by the overworld.
An earlier cut of this module carried one dimension per block, picked the overworld
when a block's features disagreed, and special-cased the two mushroom features by id
so the disagreement would not raise. That silently deleted every nether vein and the
nether biomes with it, and a Gravel page that says "Overworld" is a wrong answer to
"where do I find this".

So a block carries one `GenerationScope` per dimension it generates in. Every scope
states its own band, its own attempt count, and its own biomes, because all three of
those are dimension-specific: the same `above_bottom` anchor is Y -64 in the overworld
and Y 0 in the nether, and no single band spans two worlds honestly.

## A height anchor is not a Y coordinate, and a heightmap is not a band

`height_range` states a band in anchors that resolve against the dimension's own build
range, and the band is clipped into that range: `ore_diamond` declares `above_bottom -80`,
which is Y -144 in a world whose floor is -64, and printing that would send a player 80
blocks below bedrock. The trapezoid peak is taken from the *declared* band rather than
the clipped one, because that is where the density really is.

`heightmap` states no band at all. It puts the feature on a surface, wherever that
surface happens to be, so those veins carry `surface` and no numbers. Filling in the
dimension's full build range instead -- which an earlier cut did -- made every sweet
berry bush and dead bush claim "Y -64 to 320", which is the whole world and is not
what any file says.

## A count before the position is an attempt; a count after it is patch density

Placement modifiers run in order. A `count` ahead of the `height_range` or `heightmap`
modifier multiplies the positions the feature tries per chunk, which is what "attempts
per chunk" means. A `count` *after* it scatters that many blocks around one position
that was already chosen, which is the size of a patch and not a per-chunk rate: 38 of
the placed features this module reads state their count that way. Neither number is an
attempt count, so such a vein carries none rather than a figure that reads like one.
`noise_threshold_count` decides the count from terrain noise, so it carries none either.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from pipeline.extract import ExtractError
from pipeline.extract.tags import TagIndex
from pipeline.fetch import decode_json

__all__ = [
    "DIMENSION_BOUNDS",
    "DIMENSION_TAGS",
    "POSITION_MODIFIERS",
    "SUPPORTED_CONFIGURED_TYPES",
    "BlockGeneration",
    "Dimension",
    "GenerationExtractionResult",
    "GenerationReport",
    "GenerationScope",
    "SkippedFeature",
    "VeinFacts",
    "extract_generation",
    "resolve_anchor",
]

SUPPORTED_CONFIGURED_TYPES: frozenset[str] = frozenset(
    {
        "minecraft:ore",
        "minecraft:simple_block",
        "minecraft:disk",
        "minecraft:scattered_ore",
        "minecraft:block_blob",
    }
)

# The two modifiers that choose where in the column a feature lands. Everything
# before one of these runs per chunk; everything after it runs per position.
POSITION_MODIFIERS: frozenset[str] = frozenset(
    {"minecraft:height_range", "minecraft:heightmap"}
)


class Dimension(StrEnum):
    """The dimension a block or feature belongs to."""

    OVERWORLD = "overworld"
    NETHER = "nether"
    END = "end"


# The build range of each dimension, which is what a height anchor resolves against.
# These are not in the data branch -- mcmeta publishes no `dimension_type` group -- so
# they are stated here, and `test_extract_generation` pins them against the anchors of
# real features that reach the floor and the ceiling of each world.
DIMENSION_BOUNDS: Mapping[Dimension, tuple[int, int]] = {
    Dimension.OVERWORLD: (-64, 320),
    Dimension.NETHER: (0, 128),
    Dimension.END: (0, 256),
}

# The biome tag that names each dimension's biomes. The counts come from resolving
# these, never from a literal, so a version that adds a biome does not silently turn
# "every biome" into "all but one".
DIMENSION_TAGS: Mapping[Dimension, str] = {
    Dimension.OVERWORLD: "is_overworld",
    Dimension.NETHER: "is_nether",
    Dimension.END: "is_end",
}


class VeinFacts(BaseModel, frozen=True):
    """One placed feature's contribution to a block's generation in one dimension.

    `min_y` and `max_y` are `None` together for a feature placed on a heightmap,
    which states a surface rather than a band; `surface` is what a reader tests.
    `tries` is the attempts per chunk where the placement states one, and `None`
    where it does not -- see the module docstring on counts.
    """

    feature: str
    dimension: Dimension
    min_y: int | None = None
    max_y: int | None = None
    surface: bool = False
    densest_y: int | None = None
    tries: int | float | None = None
    chunk_chance: int | None = None
    vein_size: int | None = None


class GenerationScope(BaseModel, frozen=True):
    """How one block generates in one dimension."""

    dimension: Dimension
    min_y: int | None = None
    max_y: int | None = None
    densest_y: int | None = None
    surface_only: bool = False
    attempts_per_chunk: int | float | None = None
    biome_count: int
    all_biomes_of_dimension: bool
    biomes: tuple[str, ...] = ()
    veins: tuple[VeinFacts, ...] = ()


class BlockGeneration(BaseModel, frozen=True):
    """The natural generation facts of one block, one scope per dimension."""

    block_id: str
    scopes: tuple[GenerationScope, ...] = ()


class SkippedFeature(BaseModel, frozen=True):
    """One configured feature skipped because it does not name a block state outright."""

    feature_id: str
    feature_type: str
    reason: str = (
        "nested state providers place several blocks rather than naming a single block "
        "state outright"
    )


class GenerationReport(BaseModel, frozen=True):
    """Report of skipped configured features."""

    skipped_features: tuple[SkippedFeature, ...] = ()


class GenerationExtractionResult(BaseModel, frozen=True):
    """The outcome of natural generation extraction."""

    blocks: dict[str, BlockGeneration]
    report: GenerationReport


def resolve_anchor(anchor: Any, *, floor: int, top: int) -> int:
    """Resolve a height anchor representation to an absolute integer Y coordinate."""
    if isinstance(anchor, int):
        return anchor
    if isinstance(anchor, dict):
        if "absolute" in anchor:
            return int(anchor["absolute"])
        if "above_bottom" in anchor:
            return floor + int(anchor["above_bottom"])
        if "below_top" in anchor:
            return top - int(anchor["below_top"])
        if "bottom" in anchor:
            return floor
        if "top" in anchor:
            return top
    if anchor == "bottom":
        return floor
    if anchor == "top":
        return top
    raise ExtractError(f"unrecognized anchor format: {anchor!r}")


def _extract_blocks_from_config(
    cf_type: str, config: Mapping[str, Any]
) -> tuple[list[str], int | None]:
    """Return the list of block IDs placed by this configured feature, and optional vein size."""
    blocks: list[str] = []
    vein_size: int | None = None

    if cf_type in ("minecraft:ore", "minecraft:scattered_ore"):
        vein_size = config.get("size")
        for target in config.get("targets", []):
            state = target.get("state", {})
            if "Name" in state:
                blocks.append(state["Name"])
    elif cf_type == "minecraft:simple_block":
        to_place = config.get("to_place", {})
        if to_place.get("type") == "minecraft:simple_state_provider":
            state = to_place.get("state", {})
            if "Name" in state:
                blocks.append(state["Name"])
    elif cf_type == "minecraft:disk":
        sp = config.get("state_provider", {})
        if sp.get("type") == "minecraft:simple_state_provider":
            state = sp.get("state", {})
            if "Name" in state:
                blocks.append(state["Name"])
    elif cf_type == "minecraft:block_blob":
        state = config.get("state", {})
        if "Name" in state:
            blocks.append(state["Name"])

    return blocks, vein_size


def _band(
    placement: Sequence[Any], *, floor: int, top: int
) -> tuple[int | None, int | None, bool, int | None]:
    """Return `(min_y, max_y, surface, densest_y)` for one placement list.

    A `height_range` states a band, clipped into the dimension's build range, with the
    trapezoid peak taken from the declared band. A `heightmap` states a surface and no
    band. A placement with neither states nothing, and gets nothing.
    """
    height_range = next(
        (
            m
            for m in placement
            if isinstance(m, Mapping) and m.get("type") == "minecraft:height_range"
        ),
        None,
    )
    if height_range is not None:
        height = height_range.get("height", {})
        raw_min = resolve_anchor(height.get("min_inclusive"), floor=floor, top=top)
        raw_max = resolve_anchor(height.get("max_inclusive"), floor=floor, top=top)
        densest_y: int | None = None
        if height.get("type") == "minecraft:trapezoid":
            raw_peak = (raw_min + raw_max) // 2
            densest_y = max(min(raw_peak, top), floor)
        return max(raw_min, floor), min(raw_max, top), False, densest_y

    heightmap = any(
        isinstance(m, Mapping) and m.get("type") == "minecraft:heightmap" for m in placement
    )
    return None, None, heightmap, None


def _rate(placement: Sequence[Any]) -> tuple[int | float | None, int | None]:
    """Return `(tries, chunk_chance)` for one placement list.

    Only the modifiers ahead of the position modifier are read, because those are the
    ones that run per chunk; see the module docstring. A placement that states its count
    only after the position gets no `tries` rather than a number that is not an attempt
    count, and the "no modifier at all means one attempt" fallback is withheld from it
    for the same reason.
    """
    before: list[Mapping[str, Any]] = []
    after: list[Mapping[str, Any]] = []
    seen_position = False
    for modifier in placement:
        if not isinstance(modifier, Mapping):
            continue
        if modifier.get("type") in POSITION_MODIFIERS:
            seen_position = True
            continue
        (after if seen_position else before).append(modifier)

    def first(modifiers: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any] | None:
        return next((m for m in modifiers if m.get("type") == kind), None)

    if first(before, "minecraft:noise_threshold_count") is not None:
        return None, None

    rarity = first(before, "minecraft:rarity_filter")
    chunk_chance = rarity.get("chance") if rarity is not None else None

    count = first(before, "minecraft:count")
    if count is not None:
        raw = count.get("count")
        if isinstance(raw, int):
            return raw, chunk_chance
        if isinstance(raw, Mapping) and raw.get("type") == "minecraft:uniform":
            average = (raw.get("min_inclusive", 0) + raw.get("max_inclusive", 0)) / 2
            return (int(average) if average.is_integer() else average), chunk_chance
        return None, chunk_chance

    if first(after, "minecraft:count") is not None:
        # Patch density, not a per-chunk rate. State the rarity, if any, and nothing else.
        return None, chunk_chance

    if chunk_chance is not None:
        return None, chunk_chance
    return 1, None


def _densest_y_of_scope(
    veins: Sequence[VeinFacts], min_y: int | None, max_y: int | None
) -> int | None:
    """Return the scope's densest depth if every peaked vein agrees and covers its band."""
    peaked = [v for v in veins if v.densest_y is not None]
    if not peaked or min_y is None or max_y is None:
        return None
    if any(p.densest_y != peaked[0].densest_y for p in peaked):
        return None
    if min(p.min_y for p in peaked if p.min_y is not None) != min_y:
        return None
    if max(p.max_y for p in peaked if p.max_y is not None) != max_y:
        return None
    return peaked[0].densest_y


def _read_group(files: Mapping[str, bytes], prefix: str) -> dict[str, dict[str, Any]]:
    """Return the JSON of one worldgen group, keyed by namespaced id."""
    out: dict[str, dict[str, Any]] = {}
    for path, raw in sorted(files.items()):
        if not path.startswith(prefix) or not path.endswith(".json"):
            continue
        rel = path.removeprefix(prefix).removesuffix(".json")
        data = decode_json(raw, source=path)
        if isinstance(data, dict):
            out[f"minecraft:{rel}"] = data
    return out


def extract_generation(files: Mapping[str, bytes]) -> GenerationExtractionResult:
    """Extract natural generation info for blocks from the vanilla worldgen files.

    `files` is the mapping of archive paths to byte content.
    Returns `GenerationExtractionResult` holding `blocks` and `report`.
    """
    if not any(p.startswith("worldgen/") for p in files):
        return GenerationExtractionResult(blocks={}, report=GenerationReport())

    biome_tags = TagIndex(files, registry="worldgen/biome")
    dimension_biomes: dict[Dimension, set[str]] = {
        dimension: set(biome_tags.resolve(tag)) for dimension, tag in DIMENSION_TAGS.items()
    }

    configured: dict[str, dict[str, Any]] = {}
    skipped: list[SkippedFeature] = []
    for cf_id, data in _read_group(files, "worldgen/configured_feature/").items():
        cf_type = str(data.get("type", ""))
        if cf_type in SUPPORTED_CONFIGURED_TYPES:
            configured[cf_id] = data
        else:
            skipped.append(SkippedFeature(feature_id=cf_id, feature_type=cf_type))

    feature_biomes: dict[str, set[str]] = {}
    for biome_id, data in _read_group(files, "worldgen/biome/").items():
        for step in data.get("features", []):
            if not isinstance(step, list):
                continue
            for placed_id in step:
                if isinstance(placed_id, str):
                    feature_biomes.setdefault(placed_id, set()).add(biome_id)

    # (block id, dimension) -> the veins of that block in that dimension, and the
    # biomes those veins run in.
    scoped_veins: dict[tuple[str, Dimension], list[VeinFacts]] = {}
    scoped_biomes: dict[tuple[str, Dimension], set[str]] = {}

    for placed_id, placed in _read_group(files, "worldgen/placed_feature/").items():
        reference = placed.get("feature")
        if not isinstance(reference, str) or reference not in configured:
            continue
        config = configured[reference].get("config", {})
        if not isinstance(config, dict):
            continue
        blocks, vein_size = _extract_blocks_from_config(
            str(configured[reference].get("type", "")), config
        )
        if not blocks:
            continue

        biomes = feature_biomes.get(placed_id, set())
        if not biomes:
            # A feature no biome runs, such as the bonemeal-only grass patches.
            continue

        placement = placed.get("placement", [])
        if not isinstance(placement, list):
            placement = []
        tries, chunk_chance = _rate(placement)

        for dimension, dimension_set in dimension_biomes.items():
            in_dimension = biomes & dimension_set
            if not in_dimension:
                continue
            floor, top = DIMENSION_BOUNDS[dimension]
            min_y, max_y, surface, densest_y = _band(placement, floor=floor, top=top)
            vein = VeinFacts(
                feature=placed_id,
                dimension=dimension,
                min_y=min_y,
                max_y=max_y,
                surface=surface,
                densest_y=densest_y,
                tries=tries,
                chunk_chance=chunk_chance,
                vein_size=vein_size,
            )
            for block in blocks:
                key = (block, dimension)
                scoped_veins.setdefault(key, []).append(vein)
                scoped_biomes.setdefault(key, set()).update(in_dimension)

    block_scopes: dict[str, list[GenerationScope]] = {}
    for (block, dimension), veins in sorted(scoped_veins.items()):
        banded = [v for v in veins if v.min_y is not None and v.max_y is not None]
        min_y = min((v.min_y for v in banded if v.min_y is not None), default=None)
        max_y = max((v.max_y for v in banded if v.max_y is not None), default=None)
        biomes_here = sorted(scoped_biomes[(block, dimension)])
        counted = [v.tries for v in veins if v.chunk_chance is None and v.tries is not None]
        attempts: int | float | None = sum(counted) if counted else None
        if isinstance(attempts, float) and attempts.is_integer():
            attempts = int(attempts)
        all_of_dimension = len(biomes_here) == len(dimension_biomes[dimension])
        block_scopes.setdefault(block, []).append(
            GenerationScope(
                dimension=dimension,
                min_y=min_y,
                max_y=max_y,
                densest_y=_densest_y_of_scope(veins, min_y, max_y),
                surface_only=all(v.surface for v in veins),
                attempts_per_chunk=attempts,
                biome_count=len(biomes_here),
                all_biomes_of_dimension=all_of_dimension,
                biomes=() if all_of_dimension else tuple(biomes_here),
                veins=tuple(veins),
            )
        )

    order = list(Dimension)
    blocks_out = {
        block: BlockGeneration(
            block_id=block,
            scopes=tuple(sorted(scopes, key=lambda s: order.index(s.dimension))),
        )
        for block, scopes in sorted(block_scopes.items())
    }
    return GenerationExtractionResult(
        blocks=blocks_out,
        report=GenerationReport(skipped_features=tuple(skipped)),
    )
