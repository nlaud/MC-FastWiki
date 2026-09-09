"""Extract natural structure facts from worldgen data pack files.

A structure page must answer where the structure generates in the world: the dimension,
the biomes that carry it, the generation step, its placement rules (spacing, separation,
frequency, concentric rings, exclusion zones), its structure set siblings with weights,
its mob spawn overrides, and its suppressed spawn categories.

Upstream Minecraft Java data packs express structures across two registries:
1. `worldgen/structure`: what gets placed, its biomes tag reference, generation step,
   and spawn overrides.
2. `worldgen/structure_set`: how structures are grouped into sets, their weights within
   the set, and their world placement configuration (random_spread or concentric_rings).
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from pipeline.extract import ExtractError
from pipeline.extract.generation import DIMENSION_TAGS, Dimension
from pipeline.extract.tags import TagIndex
from pipeline.fetch import decode_json

__all__ = [
    "ConcentricRingsPlacement",
    "ExclusionZone",
    "RandomSpreadPlacement",
    "SiblingStructure",
    "StructureEntry",
    "StructureIndex",
    "StructurePlacement",
    "StructureSpawnOverride",
    "extract_structures",
]

STRUCTURE_DIRECTORY = "worldgen/structure/"
STRUCTURE_SET_DIRECTORY = "worldgen/structure_set/"
DEFAULT_NAMESPACE = "minecraft"


class ExclusionZone(BaseModel, frozen=True):
    """An area around another structure set where this structure cannot place."""

    other_set: str
    chunk_count: int


class RandomSpreadPlacement(BaseModel, frozen=True):
    """Placement across the world with spacing and separation."""

    type: Literal["minecraft:random_spread"] = "minecraft:random_spread"
    spacing: int
    separation: int
    spread_type: str | None = None
    frequency: float | None = None
    frequency_reduction_method: str | None = None
    exclusion_zone: ExclusionZone | None = None
    salt: int | None = None


class ConcentricRingsPlacement(BaseModel, frozen=True):
    """Placement in concentric rings around the world origin (e.g. Strongholds)."""

    type: Literal["minecraft:concentric_rings"] = "minecraft:concentric_rings"
    count: int
    distance: int
    spread: int
    preferred_biomes: str
    salt: int | None = None


StructurePlacement = Annotated[
    RandomSpreadPlacement | ConcentricRingsPlacement,
    Field(discriminator="type"),
]


class SiblingStructure(BaseModel, frozen=True):
    """Another structure belonging to the same structure set, with its relative weight."""

    structure: str
    weight: int


class StructureSpawnOverride(BaseModel, frozen=True):
    """One mob spawn override inside a structure bounding box."""

    category: str
    entity_type: str
    min_count: int
    max_count: int
    weight: int


class StructureEntry(BaseModel, frozen=True):
    """All extracted facts for one structure registry ID."""

    id: str
    path: str
    structure_type: str
    step: str
    biomes: tuple[str, ...]
    dimension: Dimension
    set_id: str
    siblings: tuple[SiblingStructure, ...]
    placement: StructurePlacement
    spawns: tuple[StructureSpawnOverride, ...] = ()
    suppressed_spawns: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructureIndex:
    """The full set of extracted structures, keyed by namespaced ID."""

    structures: Mapping[str, StructureEntry] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.structures)

    def __getitem__(self, item: str) -> StructureEntry:
        return self.structures[item]

    def __iter__(self) -> Iterator[str]:
        return iter(self.structures)

    def __contains__(self, item: object) -> bool:
        return item in self.structures

    def keys(self) -> Iterable[str]:
        return self.structures.keys()

    def values(self) -> Iterable[StructureEntry]:
        return self.structures.values()

    def items(self) -> Iterable[tuple[str, StructureEntry]]:
        return self.structures.items()


def _namespaced(path: str) -> str:
    if ":" in path:
        return path
    return f"{DEFAULT_NAMESPACE}:{path}"


def _resolve_biomes(
    biomes_ref: Any,
    *,
    biome_tags: TagIndex,
    source: str,
) -> tuple[str, ...]:
    """Resolve a structure's `biomes` field into a sorted tuple of namespaced biome IDs."""
    if isinstance(biomes_ref, str):
        if biomes_ref.startswith("#"):
            tag_name = biomes_ref[1:]
            if tag_name.startswith(f"{DEFAULT_NAMESPACE}:"):
                tag_name = tag_name.removeprefix(f"{DEFAULT_NAMESPACE}:")
            return tuple(sorted(biome_tags.resolve(tag_name)))
        return (_namespaced(biomes_ref),)

    if isinstance(biomes_ref, Sequence):
        resolved: set[str] = set()
        for item in biomes_ref:
            if not isinstance(item, str):
                continue
            if item.startswith("#"):
                tag_name = item[1:]
                if tag_name.startswith(f"{DEFAULT_NAMESPACE}:"):
                    tag_name = tag_name.removeprefix(f"{DEFAULT_NAMESPACE}:")
                resolved.update(biome_tags.resolve(tag_name))
            else:
                resolved.add(_namespaced(item))
        return tuple(sorted(resolved))

    raise ExtractError(f"{source} has unsupported 'biomes' field: {biomes_ref!r}")


def _parse_placement(placement_dict: Mapping[str, Any], *, source: str) -> StructurePlacement:
    ptype = placement_dict.get("type")
    if ptype == "minecraft:random_spread":
        spacing = placement_dict.get("spacing")
        separation = placement_dict.get("separation")
        if not isinstance(spacing, int) or not isinstance(separation, int):
            raise ExtractError(f"{source} random_spread placement missing spacing or separation")

        ez: ExclusionZone | None = None
        ez_dict = placement_dict.get("exclusion_zone")
        if isinstance(ez_dict, Mapping):
            other_set = ez_dict.get("other_set")
            chunk_count = ez_dict.get("chunk_count")
            if isinstance(other_set, str) and isinstance(chunk_count, int):
                ez = ExclusionZone(other_set=other_set, chunk_count=chunk_count)

        freq = placement_dict.get("frequency")
        frequency = float(freq) if isinstance(freq, int | float) else None
        freq_method = placement_dict.get("frequency_reduction_method")
        spread_type = placement_dict.get("spread_type")
        salt = placement_dict.get("salt")

        return RandomSpreadPlacement(
            spacing=spacing,
            separation=separation,
            spread_type=str(spread_type) if spread_type is not None else None,
            frequency=frequency,
            frequency_reduction_method=str(freq_method) if freq_method is not None else None,
            exclusion_zone=ez,
            salt=int(salt) if isinstance(salt, int) else None,
        )

    if ptype == "minecraft:concentric_rings":
        count = placement_dict.get("count")
        distance = placement_dict.get("distance")
        spread = placement_dict.get("spread")
        preferred = placement_dict.get("preferred_biomes")
        if (
            not isinstance(count, int)
            or not isinstance(distance, int)
            or not isinstance(spread, int)
            or not isinstance(preferred, str)
        ):
            raise ExtractError(f"{source} concentric_rings placement missing required fields")

        salt = placement_dict.get("salt")
        return ConcentricRingsPlacement(
            count=count,
            distance=distance,
            spread=spread,
            preferred_biomes=preferred,
            salt=int(salt) if isinstance(salt, int) else None,
        )

    raise ExtractError(f"{source} has unknown placement type: {ptype!r}")


def extract_structures(files: Mapping[str, bytes]) -> StructureIndex:
    """Extract all structures from vanilla worldgen data pack files.

    `files` is the mapping returned by `pipeline.fetch.mcmeta.fetch_data_files`.
    Returns a `StructureIndex` holding all extracted `StructureEntry` objects.
    Raises `ExtractError` on malformed data or dimension resolution failure.
    """
    if not any(k.startswith(STRUCTURE_DIRECTORY) for k in files):
        return StructureIndex(structures={})

    biome_tags = TagIndex(files, registry="worldgen/biome")
    dimension_biomes: dict[Dimension, set[str]] = {
        dimension: set(biome_tags.resolve(tag)) for dimension, tag in DIMENSION_TAGS.items()
    }

    # 1. Parse all structure sets
    struct_set_info: dict[str, tuple[str, StructurePlacement, tuple[SiblingStructure, ...]]] = {}
    for path, raw in sorted(files.items()):
        if not path.startswith(STRUCTURE_SET_DIRECTORY) or not path.endswith(".json"):
            continue
        rel = path.removeprefix(STRUCTURE_SET_DIRECTORY).removesuffix(".json")
        set_id = _namespaced(rel)
        data = decode_json(raw, source=path)
        if not isinstance(data, Mapping):
            raise ExtractError(f"{path} does not declare a JSON object")

        placement_dict = data.get("placement")
        if not isinstance(placement_dict, Mapping):
            raise ExtractError(f"{path} has no placement mapping")
        placement = _parse_placement(placement_dict, source=path)

        struct_entries = data.get("structures")
        if not isinstance(struct_entries, list):
            raise ExtractError(f"{path} has no structures list")

        siblings_all: list[SiblingStructure] = []
        for s_entry in struct_entries:
            if not isinstance(s_entry, Mapping):
                continue
            s_name = s_entry.get("structure")
            s_weight = s_entry.get("weight")
            if isinstance(s_name, str) and isinstance(s_weight, int):
                siblings_all.append(
                    SiblingStructure(structure=_namespaced(s_name), weight=s_weight)
                )

        for sibling in siblings_all:
            others = tuple(s for s in siblings_all if s.structure != sibling.structure)
            struct_set_info[sibling.structure] = (set_id, placement, others)

    # 2. Parse all structures
    structures_out: dict[str, StructureEntry] = {}
    for path, raw in sorted(files.items()):
        if not path.startswith(STRUCTURE_DIRECTORY) or not path.endswith(".json"):
            continue
        rel = path.removeprefix(STRUCTURE_DIRECTORY).removesuffix(".json")
        struct_id = _namespaced(rel)
        data = decode_json(raw, source=path)
        if not isinstance(data, Mapping):
            raise ExtractError(f"{path} does not declare a JSON object")

        stype = data.get("type")
        if not isinstance(stype, str):
            raise ExtractError(f"{path} has no 'type'")

        step = data.get("step")
        if not isinstance(step, str):
            raise ExtractError(f"{path} has no 'step'")

        biomes = _resolve_biomes(data.get("biomes"), biome_tags=biome_tags, source=path)
        biome_set = set(biomes)

        matching_dims = [
            dimension
            for dimension, b_set in dimension_biomes.items()
            if bool(biome_set & b_set)
        ]
        if len(matching_dims) != 1:
            raise ExtractError(
                f"Structure {struct_id} resolves {len(matching_dims)} dimensions "
                f"({matching_dims}), expected exactly 1"
            )
        dimension = matching_dims[0]

        # Spawn overrides and suppression
        spawns: list[StructureSpawnOverride] = []
        suppressed: list[str] = []
        spawn_overrides = data.get("spawn_overrides")
        if isinstance(spawn_overrides, Mapping):
            for category, cat_data in sorted(spawn_overrides.items()):
                if not isinstance(cat_data, Mapping):
                    continue
                spawn_list = cat_data.get("spawns")
                if isinstance(spawn_list, list):
                    if not spawn_list:
                        suppressed.append(category)
                    else:
                        for entry in spawn_list:
                            if not isinstance(entry, Mapping):
                                continue
                            entity_type = entry.get("type")
                            min_c = entry.get("minCount")
                            max_c = entry.get("maxCount")
                            weight = entry.get("weight")
                            if (
                                isinstance(entity_type, str)
                                and isinstance(min_c, int)
                                and isinstance(max_c, int)
                                and isinstance(weight, int)
                            ):
                                spawns.append(
                                    StructureSpawnOverride(
                                        category=category,
                                        entity_type=_namespaced(entity_type),
                                        min_count=min_c,
                                        max_count=max_c,
                                        weight=weight,
                                    )
                                )

        set_meta = struct_set_info.get(struct_id)
        if set_meta is None:
            raise ExtractError(f"Structure {struct_id} has no matching structure_set entry")
        set_id, placement, siblings = set_meta

        structures_out[struct_id] = StructureEntry(
            id=struct_id,
            path=rel,
            structure_type=stype,
            step=step,
            biomes=biomes,
            dimension=dimension,
            set_id=set_id,
            siblings=siblings,
            placement=placement,
            spawns=tuple(spawns),
            suppressed_spawns=tuple(sorted(suppressed)),
        )

    return StructureIndex(structures=structures_out)
