"""Curated producer table for one-off obtain methods without upstream adapters.

Loads `data/curated/producers.json` into `Producer` instances and provides
structure and container attribution for world generation entries via `ChestSource`.
Every curated row is validated strictly: `extra="forbid"` rejects unknown keys,
and every output item must exist in the item registry so a typo cannot invent an item.
"""

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field

from pipeline.obtain import ObtainError
from pipeline.obtain.chests import ChestSource
from pipeline.obtain.producer import ObtainMethod, Producer, ProducerInput, ProducerOutput

__all__ = [
    "DEFAULT_PRODUCERS_PATH",
    "PRODUCERS_FILENAME",
    "CuratedProducerEntry",
    "CuratedProducersDocument",
    "load_curated_producers",
    "load_curated_sources",
]

PRODUCERS_FILENAME = "producers.json"
DEFAULT_PRODUCERS_PATH = Path("data/curated") / PRODUCERS_FILENAME


class CuratedProducerEntry(BaseModel, frozen=True, extra="forbid"):
    """One row of the curated producer table.

    Every row must declare output, method, source_id, and the wiki page it was verified on.
    For world_generation entries, structure and container are also required.
    """

    output: str
    method: ObtainMethod
    inputs: tuple[str, ...] = ()
    source_id: str
    station: str | None = None
    note: str | None = None
    structure: str | None = None
    container: str | None = None
    wiki: str


class CuratedProducersDocument(BaseModel, frozen=True, extra="forbid"):
    """The envelope of `producers.json`."""

    verified_for: str = Field(alias="verifiedFor")
    note: str
    producers: tuple[CuratedProducerEntry, ...]


def _load_document(path: Path) -> CuratedProducersDocument:
    if not path.is_file():
        raise ObtainError(f"curated producers file not found at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ObtainError(f"could not parse curated producers at {path}: {error}") from error

    try:
        return CuratedProducersDocument.model_validate(data)
    except Exception as error:
        raise ObtainError(f"invalid curated producers document at {path}: {error}") from error


def load_curated_producers(
    path: Path = DEFAULT_PRODUCERS_PATH,
    *,
    item_registry: Iterable[str] | None = None,
) -> list[Producer]:
    """Read and validate `producers.json`, returning a list of `Producer`s.

    When `item_registry` is provided, every output item (and input item) is verified
    to exist in the registry, preventing typos from inventing non-existent items.
    """
    doc = _load_document(path)

    known_items: set[str] | None = None
    if item_registry is not None:
        known_items = {item if ":" in item else f"minecraft:{item}" for item in item_registry}

    producers: list[Producer] = []
    for entry in doc.producers:
        if known_items is not None:
            if entry.output not in known_items:
                raise ObtainError(
                    f"curated producer output {entry.output!r} is not in the item registry."
                )
            for inp in entry.inputs:
                if inp not in known_items:
                    raise ObtainError(
                        f"curated producer input {inp!r} for {entry.output!r} "
                        f"is not in the item registry."
                    )

        if entry.method is ObtainMethod.WORLD_GENERATION and (
            entry.structure is None or entry.container is None
        ):
            raise ObtainError(
                f"world_generation producer {entry.source_id!r} must declare "
                f"structure and container."
            )

        producers.append(
            Producer(
                method=entry.method,
                output=ProducerOutput(item=entry.output, count=1),
                inputs=tuple(ProducerInput(item=inp) for inp in entry.inputs),
                source_id=entry.source_id,
                station=entry.station,
                note=entry.note,
            )
        )

    return producers


def load_curated_sources(path: Path = DEFAULT_PRODUCERS_PATH) -> dict[str, ChestSource]:
    """Read `producers.json` and return `ChestSource` attribution for world_generation rows."""
    doc = _load_document(path)
    sources: dict[str, ChestSource] = {}
    for entry in doc.producers:
        if entry.structure is not None and entry.container is not None:
            sources[entry.source_id] = ChestSource(
                structure=entry.structure,
                container=entry.container,
            )
    return sources
