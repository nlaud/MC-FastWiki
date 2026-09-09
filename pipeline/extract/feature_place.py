"""Extract the places a player searches for that the game files as a feature.

A dungeon is the case this module exists for. Every player calls it a structure and
`data/curated/chest-sources.json` files its chest under one, but `worldgen/structure`
does not list it: the game holds it as `worldgen/configured_feature/monster_room.json`
and runs it through two placed features. Before this module it was the only lootable
place in the game with no page, and the chest that names it had nothing to link to.

## What is curated and what is derived

`data/curated/feature-places.json` carries two things only, because the wiki's
`resource_location` bucket has no row for a configured feature and so cannot answer
them: the display name and the wiki page. Everything a page states -- the dimension,
the height band, the attempts per chunk, the biomes -- is derived from the placed
features the curated entry names, because that data is in the pack and stating it by
hand would be the guess Decision 3 forbids.

## Why this is not `extract_generation`

`pipeline.extract.generation` answers "where does this *block* generate" and keys its
result by block id, reading the five configured feature types that name a block state
outright. A dungeon names none: `monster_room` carries `config: {}` because the game
builds the room in Java code rather than describing it in data. So the feature is
invisible to that module by construction, and it is reported in the skipped list of
`generation-report.json` along with every other type that places no single block.

What the two modules do share is the placement reading, and they share it literally:
`band_of_placement` and `rate_of_placement` are imported rather than restated, so a
dungeon's band resolves its anchors against the same dimension bounds as an ore vein
and its attempts obey the same rule about which counts run per chunk.

## One place, several passes

A dungeon generates in two passes, and neither is the whole answer. `monster_room`
runs 10 attempts per chunk from Y 0 to the world top; `monster_room_deep` runs 4 more
from Y -58 to Y -1. A page that showed either alone would halve the rate and cut the
band at zero, so the passes are summed into one attempt count and unioned into one
band. This mirrors what `GenerationScope` already does for a block whose several
placed features share a dimension.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pipeline.extract import ExtractError
from pipeline.extract.generation import (
    DIMENSION_BOUNDS,
    DIMENSION_TAGS,
    Dimension,
    band_of_placement,
    rate_of_placement,
)
from pipeline.extract.tags import TagIndex
from pipeline.fetch import decode_json

__all__ = [
    "CONFIGURED_FEATURE_DIRECTORY",
    "DEFAULT_FEATURE_PLACES_PATH",
    "FEATURE_PLACES_FILENAME",
    "PLACED_FEATURE_DIRECTORY",
    "FeaturePlace",
    "FeaturePlaceIndex",
    "extract_feature_places",
    "load_feature_places",
]

CONFIGURED_FEATURE_DIRECTORY = "worldgen/configured_feature/"
PLACED_FEATURE_DIRECTORY = "worldgen/placed_feature/"
BIOME_DIRECTORY = "worldgen/biome/"


class FeaturePlace(BaseModel, frozen=True):
    """Where one curated feature generates, derived entirely from the data pack.

    `min_y` and `max_y` span every pass together. `attempts_per_chunk` sums them,
    because a reader asking how often a dungeon appears wants both passes counted
    once, not the larger of the two.
    """

    id: str
    name: str
    page: str
    dimension: Dimension
    min_y: int | None = None
    max_y: int | None = None
    attempts_per_chunk: int | float | None = None
    biomes: tuple[str, ...] = ()
    all_biomes_of_dimension: bool = False
    placed_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class FeaturePlaceIndex:
    """The curated feature places, keyed by their configured-feature id."""

    places: Mapping[str, FeaturePlace] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.places)

    def __getitem__(self, item: str) -> FeaturePlace:
        return self.places[item]

    def __contains__(self, item: object) -> bool:
        return item in self.places

    def keys(self) -> Any:
        return self.places.keys()

    def values(self) -> Any:
        return self.places.values()

    def items(self) -> Any:
        return self.places.items()


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


def extract_feature_places(
    files: Mapping[str, bytes],
    curated: Mapping[str, Mapping[str, Any]],
) -> FeaturePlaceIndex:
    """Derive each curated feature place's generation facts from the worldgen files.

    `curated` maps a configured-feature id to its `name`, `page`, and the
    `placedFeatures` that run it. Raises `ExtractError` when a curated id names a
    configured feature, a placed feature, or a dimension the pack does not hold,
    because a curated row that has silently stopped matching upstream is a data gap
    rather than a page to render empty.
    """
    if not any(path.startswith("worldgen/") for path in files):
        return FeaturePlaceIndex()

    configured = _read_group(files, CONFIGURED_FEATURE_DIRECTORY)
    placed = _read_group(files, PLACED_FEATURE_DIRECTORY)

    biome_tags = TagIndex(files, registry="worldgen/biome")
    dimension_biomes: dict[Dimension, set[str]] = {
        dimension: set(biome_tags.resolve(tag)) for dimension, tag in DIMENSION_TAGS.items()
    }

    # Which biomes run which placed feature, read the same way `extract_generation`
    # reads it: a biome's `features` array is the only statement of this in the pack.
    feature_biomes: dict[str, set[str]] = {}
    for biome_id, data in _read_group(files, BIOME_DIRECTORY).items():
        for step in data.get("features", []):
            if not isinstance(step, list):
                continue
            for placed_id in step:
                if isinstance(placed_id, str):
                    feature_biomes.setdefault(placed_id, set()).add(biome_id)

    out: dict[str, FeaturePlace] = {}
    for feature_id, entry in sorted(curated.items()):
        if feature_id not in configured:
            raise ExtractError(
                f"curated feature place {feature_id!r} names no configured feature in this pack"
            )
        placed_ids = tuple(entry.get("placedFeatures", ()))
        if not placed_ids:
            raise ExtractError(f"curated feature place {feature_id!r} names no placed features")

        biomes: set[str] = set()
        bands: list[tuple[int | None, int | None]] = []
        attempts: list[int | float] = []
        for placed_id in placed_ids:
            if placed_id not in placed:
                raise ExtractError(
                    f"curated feature place {feature_id!r} names placed feature "
                    f"{placed_id!r}, which this pack does not hold"
                )
            biomes |= feature_biomes.get(placed_id, set())

        # The dimension is decided by the biomes that really run the passes, never
        # stated by hand, exactly as a structure's is.
        dimensions = [d for d, members in dimension_biomes.items() if biomes & members]
        if len(dimensions) != 1:
            raise ExtractError(
                f"curated feature place {feature_id!r} resolved {len(dimensions)} dimensions "
                f"from {len(biomes)} biomes; a place must generate in exactly one"
            )
        dimension = dimensions[0]
        floor, top = DIMENSION_BOUNDS[dimension]

        for placed_id in placed_ids:
            placement = placed[placed_id].get("placement", [])
            if not isinstance(placement, list):
                placement = []
            min_y, max_y, _surface, _densest = band_of_placement(placement, floor=floor, top=top)
            bands.append((min_y, max_y))
            tries, _chance = rate_of_placement(placement)
            if tries is not None:
                attempts.append(tries)

        lows = [low for low, _ in bands if low is not None]
        highs = [high for _, high in bands if high is not None]
        total: int | float | None = sum(attempts) if attempts else None
        if isinstance(total, float) and total.is_integer():
            total = int(total)

        in_dimension = sorted(biomes & dimension_biomes[dimension])
        covers_all = len(in_dimension) == len(dimension_biomes[dimension])
        out[feature_id] = FeaturePlace(
            id=feature_id,
            name=str(entry["name"]),
            page=str(entry["page"]),
            dimension=dimension,
            min_y=min(lows) if lows else None,
            max_y=max(highs) if highs else None,
            attempts_per_chunk=total,
            # The full list is always carried, even when it covers the whole
            # dimension. `all_biomes_of_dimension` is a rendering hint -- a page
            # says "all 55 overworld biomes" rather than listing them -- but the
            # biome pages still need the real ids to link back with, so dropping
            # them here would cost 55 reverse links to save nothing.
            biomes=tuple(in_dimension),
            all_biomes_of_dimension=covers_all,
            placed_features=placed_ids,
        )

    return FeaturePlaceIndex(places=out)


FEATURE_PLACES_FILENAME = "feature-places.json"
DEFAULT_FEATURE_PLACES_PATH = Path("data/curated") / FEATURE_PLACES_FILENAME


def load_feature_places(
    path: Path = DEFAULT_FEATURE_PLACES_PATH,
) -> dict[str, dict[str, Any]]:
    """Read and validate `feature-places.json`, returning feature id to its curated entry.

    Mirrors `pipeline.obtain.chests.load_chest_sources`: a Tier C document this
    project wrote, so every fault here is a shape fault worth naming precisely
    rather than working around.
    """
    if not path.is_file():
        raise ExtractError(f"curated feature places file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ExtractError(f"could not parse curated feature places at {path}: {error}") from error

    if not isinstance(data, dict):
        raise ExtractError(f"{path} does not hold a JSON object.")
    places = data.get("places")
    if not isinstance(places, dict):
        raise ExtractError(f"{path} does not declare a 'places' mapping.")

    out: dict[str, dict[str, Any]] = {}
    for feature_id, entry in places.items():
        if not isinstance(entry, dict) or "name" not in entry or "page" not in entry:
            raise ExtractError(
                f"{path} entry for {feature_id!r} must be an object declaring 'name' and 'page'."
            )
        if not isinstance(entry.get("placedFeatures"), list) or not entry["placedFeatures"]:
            raise ExtractError(
                f"{path} entry for {feature_id!r} must declare a non-empty 'placedFeatures' list."
            )
        out[feature_id] = entry
    return out
