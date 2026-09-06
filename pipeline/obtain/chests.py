"""Curated structure and container attribution for chest loot tables.

`data/curated/chest-sources.json` maps every chest loot table mcmeta ships
to a human-readable structure name and container label in Title Case.
An unmapped chest table raises an ObtainError: an unnamed structure is a
data gap rather than a rendering detail.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, Field

from pipeline.obtain import ObtainError

__all__ = [
    "CHEST_SOURCES_FILENAME",
    "DEFAULT_CHEST_SOURCES_PATH",
    "ChestSource",
    "CuratedChestData",
    "load_chest_sources",
    "verify_chest_sources",
]

CHEST_SOURCES_FILENAME = "chest-sources.json"
DEFAULT_CHEST_SOURCES_PATH = Path("data/curated") / CHEST_SOURCES_FILENAME


class ChestSource(BaseModel, frozen=True):
    """Curated structure and container attribution for one chest loot table."""

    structure: str
    container: str


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
        )
    return result


def verify_chest_sources(
    found_tables: Iterable[str],
    curated: Mapping[str, ChestSource],
) -> None:
    """Raise ObtainError if any found chest loot table is missing from curated sources."""
    missing = [table for table in sorted(found_tables) if table not in curated]
    if missing:
        raise ObtainError(
            f"found {len(missing)} chest loot tables with no curated entry in "
            f"{CHEST_SOURCES_FILENAME}: {', '.join(missing)}"
        )
