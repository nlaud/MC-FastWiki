"""Curated structure and container attribution for chest loot tables.

`data/curated/chest-sources.json` maps every chest loot table mcmeta ships
to a human-readable structure name and container label in Title Case.
An unmapped chest table raises an ObtainError: an unnamed structure is a
data gap rather than a rendering detail.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pipeline.obtain import ObtainError

__all__ = [
    "CHEST_SOURCES_FILENAME",
    "DEFAULT_CHEST_SOURCES_PATH",
    "ChestSource",
    "CuratedChestData",
    "by_structure",
    "load_chest_sources",
    "verify_chest_sources",
]

CHEST_SOURCES_FILENAME = "chest-sources.json"
DEFAULT_CHEST_SOURCES_PATH = Path("data/curated") / CHEST_SOURCES_FILENAME


def _coerce_structure_ref(v: Any) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,)
    if isinstance(v, (list, tuple)):
        return tuple(str(x) for x in v)
    raise ValueError(f"invalid structureRef: {v!r}")


class ChestSource(BaseModel, frozen=True, populate_by_name=True):
    """Curated structure and container attribution for one loot table.

    `ref` is the registry id of the entity or block a player interacts with,
    where the source *is* one thing a page exists for: the piglin you barter
    with, the sheep you shear, the armadillo you brush. It is optional because
    most sources are not one entity -- a chest in a mineshaft, a fishing
    catch, a hero-of-the-village gift -- and inventing a ref for those would
    point a link at a page that does not answer the question the label asks.
    A renderer with a `ref` draws the label as a link, and without one draws
    it as plain text, the same rule `pipeline.normalize.merge` uses for a name
    it cannot resolve to exactly one entity.

    `structure_ref` is the tuple of namespaced structure IDs this chest table
    belongs to, linking forward to structure entity pages.
    """

    structure: str
    container: str
    ref: str | None = None
    structure_ref: tuple[str, ...] = Field(default=(), alias="structureRef")

    @field_validator("structure_ref", mode="before")
    @classmethod
    def _validate_structure_ref(cls, v: Any) -> tuple[str, ...]:
        return _coerce_structure_ref(v)


class CuratedChestData(BaseModel, frozen=True):
    """The contents of `chest-sources.json`."""

    verified_for: str = Field(alias="verifiedFor")
    note: str
    chests: Mapping[str, ChestSource]


def load_chest_sources(path: Path = DEFAULT_CHEST_SOURCES_PATH) -> dict[str, ChestSource]:
    """Read and validate `chest-sources.json`, returning chest loot table paths to ChestSource."""
    if not path.is_file():
        raise ObtainError(f"curated chest sources file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ObtainError(f"could not parse curated chest sources at {path}: {error}") from error

    if not isinstance(data, dict):
        raise ObtainError(f"{path} does not hold a JSON object.")

    chests_dict = data.get("chests")
    if not isinstance(chests_dict, dict):
        raise ObtainError(f"{path} does not declare a 'chests' mapping.")

    result: dict[str, ChestSource] = {}
    for table_id, entry in chests_dict.items():
        if not isinstance(entry, dict) or "structure" not in entry or "container" not in entry:
            raise ObtainError(
                f"{path} entry for {table_id!r} must be an object declaring 'structure' "
                f"and 'container'."
            )
        result[table_id] = ChestSource(
            structure=entry["structure"],
            container=entry["container"],
            ref=entry.get("ref"),
            structure_ref=_coerce_structure_ref(entry.get("structureRef")),
        )
    return result


def by_structure(
    curated: Mapping[str, ChestSource],
) -> dict[str, list[tuple[str, ChestSource]]]:
    """Map structure ID to its list of (table_path, ChestSource) container entries."""
    result: dict[str, list[tuple[str, ChestSource]]] = {}
    for table_path, source in curated.items():
        for s_ref in source.structure_ref:
            result.setdefault(s_ref, []).append((table_path, source))
    return result


def verify_chest_sources(
    found_tables: Iterable[str],
    curated: Mapping[str, ChestSource],
    *,
    extracted_structures: Iterable[str] | None = None,
) -> None:
    """Raise ObtainError if any found chest loot table is missing from curated sources,
    or if any structureRef names an unknown structure.
    """
    missing = [table for table in sorted(found_tables) if table not in curated]
    if missing:
        raise ObtainError(
            f"found {len(missing)} chest loot tables with no curated entry in "
            f"{CHEST_SOURCES_FILENAME}: {', '.join(missing)}"
        )

    if extracted_structures is not None:
        known = set(extracted_structures)
        unknown: set[str] = set()
        for table in found_tables:
            source = curated.get(table)
            if source is not None:
                for s_ref in source.structure_ref:
                    if s_ref not in known:
                        unknown.add(s_ref)
        if unknown:
            raise ObtainError(
                f"structureRef in {CHEST_SOURCES_FILENAME} names unknown structure(s): "
                f"{', '.join(sorted(unknown))}"
            )
