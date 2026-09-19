"""Extract biome facts from worldgen data pack files.

A biome page must answer what spawns there, what generates there, and what its
climate is: the temperature, downfall, precipitation, and dimension.

Upstream Minecraft Java data packs express biomes in `worldgen/biome/*.json`.

## Where the spawn table lives

Up to 26.2 a biome stated `spawners` and `spawn_costs` at its top level, and gave
each entry a `minCount` and a `maxCount`. 26.3 moved both facts behind a named
gameplay attribute and merged the two counts into one:

    attributes["minecraft:gameplay/natural_mob_spawns"].argument
        .spawns_by_category[<category>][] = {type, weight, count}
        .spawn_costs

`count` is a fixed integer or an int provider; `_group_size` resolves both into
the `(min, max)` pair the rest of this module already spoke. Measured against
the `26.3-data` tag, all 67 biomes carry the attribute and 811 mob/biome pairs
come out of it. `deep_dark` and `the_void` carry it with empty categories, which
is what the game really says about them.

## Precipitation rule

The game files declare `has_precipitation: bool` and a floating-point `temperature`.
Precipitation resolves to:
- `none` when `has_precipitation` is false
- `snow` when `has_precipitation` is true and `temperature < 0.15`
- `rain` when `has_precipitation` is true and `temperature >= 0.15`

## Duplicate spawner entries

A biome file may list the same mob within a single spawn category multiple times.
For example, Jungle declares `minecraft:chicken` twice under `creature` at weight 10
each. Duplicate spawner entries are summed per `(category, entity_type)` and their
group-size ranges unioned: Jungle chicken resolves to one entry at weight 20 and
group size 4-4. The category total is the sum over all spawners in that category.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from pipeline.extract import ExtractError
from pipeline.extract.generation import DIMENSION_TAGS, Dimension
from pipeline.extract.tags import TagIndex
from pipeline.fetch import decode_json

__all__ = [
    "BIOME_DIRECTORY",
    "BiomeEntry",
    "BiomeIndex",
    "BiomeSpawnEntry",
    "Precipitation",
    "extract_biomes",
    "resolve_precipitation",
]

BIOME_DIRECTORY = "worldgen/biome/"
DEFAULT_NAMESPACE = "minecraft"
SNOW_TEMPERATURE_THRESHOLD = 0.15

# Where a biome states what spawns in it. Up to 26.2 a biome carried `spawners`
# and `spawn_costs` at its top level. 26.3 moved both behind a named gameplay
# attribute, so the same two facts now sit under
# `attributes["minecraft:gameplay/natural_mob_spawns"].argument`.
NATURAL_MOB_SPAWNS = "minecraft:gameplay/natural_mob_spawns"

Precipitation = Literal["rain", "snow", "none"]


def resolve_precipitation(has_precipitation: bool, temperature: float) -> Precipitation:
    """Derive precipitation from has_precipitation flag and temperature threshold."""
    if not has_precipitation:
        return "none"
    if temperature < SNOW_TEMPERATURE_THRESHOLD:
        return "snow"
    return "rain"


class BiomeSpawnEntry(BaseModel, frozen=True):
    """One mob spawner entry within a biome's category."""

    entity_type: str
    weight: int
    min_count: int
    max_count: int


class BiomeEntry(BaseModel, frozen=True):
    """All extracted facts for one biome registry ID."""

    id: str
    path: str
    # `None` where no dimension tag lists the biome. See `extract_biomes`.
    dimension: Dimension | None = None
    temperature: float
    temperature_modifier: str | None = None
    downfall: float
    has_precipitation: bool
    precipitation: Precipitation
    spawners: Mapping[str, tuple[BiomeSpawnEntry, ...]]
    category_totals: Mapping[str, int]
    creature_spawn_probability: float | None = None
    spawn_costs: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class BiomeIndex:
    """The full set of extracted biomes, keyed by namespaced ID."""

    biomes: Mapping[str, BiomeEntry] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.biomes)

    def __getitem__(self, item: str) -> BiomeEntry:
        return self.biomes[item]

    def __iter__(self) -> Iterator[str]:
        return iter(self.biomes)

    def __contains__(self, item: object) -> bool:
        return item in self.biomes

    def keys(self) -> Iterable[str]:
        return self.biomes.keys()

    def values(self) -> Iterable[BiomeEntry]:
        return self.biomes.values()

    def items(self) -> Iterable[tuple[str, BiomeEntry]]:
        return self.biomes.items()


def _namespaced(path: str) -> str:
    if ":" in path:
        return path
    return f"{DEFAULT_NAMESPACE}:{path}"


def _natural_mob_spawns(data: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    """Return the `argument` of a biome's natural-mob-spawns attribute.

    Raises `ExtractError` when the attribute is absent. Every biome of the pack
    carries it -- `deep_dark` and `the_void` carry it with empty categories,
    which is what the game really says about them -- so a biome without one is a
    pack this reader does not understand, not a biome where nothing spawns.
    """
    attributes = data.get("attributes")
    if not isinstance(attributes, Mapping):
        raise ExtractError(f"{path} missing or invalid 'attributes' mapping")
    attribute = attributes.get(NATURAL_MOB_SPAWNS)
    if not isinstance(attribute, Mapping):
        raise ExtractError(f"{path} carries no {NATURAL_MOB_SPAWNS!r} attribute")
    argument = attribute.get("argument")
    if not isinstance(argument, Mapping):
        raise ExtractError(
            f"{path} carries a {NATURAL_MOB_SPAWNS!r} attribute with no 'argument' mapping"
        )
    return argument


def _group_size(count: Any) -> tuple[int, int] | None:
    """Return the `(min, max)` group size of one spawner entry, or `None`.

    26.2 stated this as two integers, `minCount` and `maxCount`. 26.3 states it
    as one `count`, which is either a fixed integer or an int provider -- in
    vanilla, always `minecraft:uniform` with an inclusive pair. A fixed count is
    the same number twice, which is exactly what the two old fields held for the
    605 entries that did not vary.

    Any other provider returns `None` and the entry is dropped rather than
    guessed at, the same rule this module already applied to a malformed entry.
    """
    if isinstance(count, bool):
        return None
    if isinstance(count, int):
        return count, count
    if isinstance(count, Mapping):
        low = count.get("min_inclusive")
        high = count.get("max_inclusive")
        if isinstance(low, int) and isinstance(high, int) and not isinstance(low, bool):
            return low, high
    return None


def extract_biomes(files: Mapping[str, bytes]) -> BiomeIndex:
    """Extract all biomes from vanilla worldgen data pack files.

    `files` is the mapping returned by `pipeline.fetch.mcmeta.fetch_data_files`.
    Returns a `BiomeIndex` holding all extracted `BiomeEntry` objects.
    Raises `ExtractError` on malformed data or dimension resolution failure.
    """
    if not any(k.startswith(BIOME_DIRECTORY) for k in files):
        return BiomeIndex(biomes={})

    biome_tags = TagIndex(files, registry="worldgen/biome")
    dimension_biomes: dict[Dimension, set[str]] = {
        dimension: set(biome_tags.resolve(tag)) for dimension, tag in DIMENSION_TAGS.items()
    }

    biomes_out: dict[str, BiomeEntry] = {}
    for path, raw in sorted(files.items()):
        if not path.startswith(BIOME_DIRECTORY) or not path.endswith(".json"):
            continue
        rel = path.removeprefix(BIOME_DIRECTORY).removesuffix(".json")
        biome_id = _namespaced(rel)
        data = decode_json(raw, source=path)
        if not isinstance(data, Mapping):
            raise ExtractError(f"{path} does not declare a JSON object")

        # Dimension resolution against the three dimension tags.
        #
        # A biome in no dimension tag carries no dimension, rather than a default.
        # `the_void` is the one such biome in 26.2, and it is deliberately in none of
        # them: it is the biome the superflat "The Void" preset uses and the one that
        # fills empty space, so it belongs to no single world. An earlier cut special-
        # cased it by ID and said Overworld, which put a claim on the page that no data
        # file makes -- the guess Decision 3 forbids. Two or more matches is still a
        # contradiction in the tags and still raises.
        matching_dims = [
            dimension
            for dimension, b_set in dimension_biomes.items()
            if biome_id in b_set
        ]
        if len(matching_dims) == 1:
            dimension = matching_dims[0]
        elif len(matching_dims) == 0:
            dimension = None
        else:
            raise ExtractError(
                f"Biome {biome_id} resolves {len(matching_dims)} dimensions "
                f"({matching_dims}), expected at most 1"
            )

        temperature = data.get("temperature")
        if not isinstance(temperature, int | float):
            raise ExtractError(f"{path} missing or invalid 'temperature'")
        temperature_val = float(temperature)

        temp_mod = data.get("temperature_modifier")
        temperature_modifier = str(temp_mod) if isinstance(temp_mod, str) else None

        downfall = data.get("downfall")
        if not isinstance(downfall, int | float):
            raise ExtractError(f"{path} missing or invalid 'downfall'")
        downfall_val = float(downfall)

        has_precip = data.get("has_precipitation")
        if not isinstance(has_precip, bool):
            raise ExtractError(f"{path} missing or invalid 'has_precipitation'")

        precipitation = resolve_precipitation(has_precip, temperature_val)

        # Spawners extraction with duplicate merging per (category, entity_type)
        spawn_argument = _natural_mob_spawns(data, path)
        raw_spawners = spawn_argument.get("spawns_by_category")
        if not isinstance(raw_spawners, Mapping):
            raise ExtractError(
                f"{path} missing or invalid 'spawns_by_category' mapping under "
                f"attributes.{NATURAL_MOB_SPAWNS!r}"
            )

        category_entries: dict[str, list[BiomeSpawnEntry]] = {}
        category_totals: dict[str, int] = {}

        for category, sp_list in sorted(raw_spawners.items()):
            if not isinstance(sp_list, list):
                continue

            # Merge duplicates per entity_type
            merged: dict[str, dict[str, Any]] = {}
            for entry in sp_list:
                if not isinstance(entry, Mapping):
                    continue
                etype = entry.get("type")
                wt = entry.get("weight")
                group = _group_size(entry.get("count"))
                if isinstance(etype, str) and isinstance(wt, int) and group is not None:
                    min_c, max_c = group
                    namespaced_etype = _namespaced(etype)
                    if namespaced_etype in merged:
                        curr = merged[namespaced_etype]
                        curr["weight"] += wt
                        curr["min_count"] = min(curr["min_count"], min_c)
                        curr["max_count"] = max(curr["max_count"], max_c)
                    else:
                        merged[namespaced_etype] = {
                            "weight": wt,
                            "min_count": min_c,
                            "max_count": max_c,
                        }

            entries = tuple(
                BiomeSpawnEntry(
                    entity_type=etype,
                    weight=info["weight"],
                    min_count=info["min_count"],
                    max_count=info["max_count"],
                )
                for etype, info in merged.items()
            )
            category_entries[category] = list(entries)
            category_totals[category] = sum(e.weight for e in entries)

        # `creature_spawn_probability` is read where the game still states it.
        # 26.3 dropped the field from every biome file -- five carried it in 26.2,
        # all of them badlands or snowy variants -- so this resolves to `None`
        # everywhere on that pack. The field stays optional rather than removed,
        # because a value that upstream stopped publishing is not a value this
        # project may invent, and the game may state it again.
        raw_prob = data.get("creature_spawn_probability")
        creature_spawn_probability = (
            float(raw_prob) if isinstance(raw_prob, int | float) else None
        )

        spawn_costs_out: dict[str, dict[str, float]] = {}
        raw_costs = spawn_argument.get("spawn_costs")
        if isinstance(raw_costs, Mapping):
            for cost_type, cost_dict in raw_costs.items():
                if isinstance(cost_dict, Mapping):
                    parsed_cost: dict[str, float] = {}
                    for k, v in cost_dict.items():
                        if isinstance(v, int | float):
                            parsed_cost[str(k)] = float(v)
                    if parsed_cost:
                        spawn_costs_out[_namespaced(cost_type)] = parsed_cost

        biomes_out[biome_id] = BiomeEntry(
            id=biome_id,
            path=rel,
            dimension=dimension,
            temperature=temperature_val,
            temperature_modifier=temperature_modifier,
            downfall=downfall_val,
            has_precipitation=has_precip,
            precipitation=precipitation,
            spawners={cat: tuple(entries) for cat, entries in category_entries.items()},
            category_totals=category_totals,
            creature_spawn_probability=creature_spawn_probability,
            spawn_costs=spawn_costs_out,
        )

    return BiomeIndex(biomes=biomes_out)
