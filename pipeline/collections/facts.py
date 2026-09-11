"""Extract fact values for collection tables.

A column in a collection names a fact key such as ``food.nutrition`` or
``obtain.foundIn``. A fact reads whichever single upstream artifact the
member's own page renders from -- an already-merged entity section, or the
obtain graph -- so the collection and the member page cannot disagree.

This is not an incidental choice. It is what guarantees the Food collection
and the Apple page can never disagree: there is one number, formatted once
at the boundary that already owns it, and both surfaces print it.
``pipeline/extract/food.py`` rounds ``saturation`` exactly once because the
raw component carries float32 noise (``beef`` reads ``1.8000001``,
``suspicious_stew`` reads ``7.2000003``). A collection that re-read the raw
payload would print ``7.2000003`` where the item page prints ``7.2``.
The same invariant governs ``obtain.foundIn``: it reads the build's merged
producers and curated chest sources rather than inventing a separate source list.

A member missing the fact renders an empty cell, not a zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pipeline.normalize.entity import Entity, Section
from pipeline.obtain.chests import ChestSource
from pipeline.obtain.producer import ObtainMethod, ProducerIndex

__all__ = ["FactSource", "ObtainFact", "SectionFact", "extract_fact"]


class SectionFact(BaseModel, frozen=True):
    """A fact read off an already-merged entity section."""

    type: Literal["section"] = "section"
    section_type: str
    attr_name: str


class ObtainFact(BaseModel, frozen=True):
    """A fact read off the obtain graph (producers and sources)."""

    type: Literal["obtain"] = "obtain"
    field: str


FactSource = Annotated[SectionFact | ObtainFact, Field(discriminator="type")]


# The fact key namespace maps dotted keys to a FactSource descriptor.
_FACT_REGISTRY: dict[str, FactSource] = {
    "food.nutrition": SectionFact(section_type="FoodInfo", attr_name="nutrition"),
    "food.saturation": SectionFact(section_type="FoodInfo", attr_name="saturation"),
    "enchant.maxLevel": SectionFact(section_type="EnchantInfo", attr_name="max_level"),
    "obtain.foundIn": ObtainFact(field="foundIn"),
}


def _format_number(value: int | float) -> str:
    """Format a numeric value for display.

    Integers display without a decimal point. Floats display with minimal
    trailing zeros: ``7.2`` rather than ``7.20``, ``0.35`` rather than
    ``0.350000000000000``.
    """
    if isinstance(value, int):
        return str(value)
    # Strip trailing zeros but keep at least one decimal
    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return formatted


def _get_section(entity: Entity, section_type: str) -> Section | None:
    """Return the first section of the given type, or None."""
    for section in entity.sections:
        if section.type == section_type:
            return section
    return None


def _extract_section_fact(entity: Entity, spec: SectionFact) -> str:
    section = _get_section(entity, spec.section_type)
    if section is None:
        return ""

    value = getattr(section, spec.attr_name, None)
    if value is None:
        return ""

    if isinstance(value, (int, float)):
        return _format_number(value)

    return str(value)


def _extract_obtain_found_in(
    member_id: str,
    producer_index: ProducerIndex | None,
    sources: Mapping[str, ChestSource] | None,
) -> str:
    if producer_index is None:
        return ""

    producers = [
        p
        for p in producer_index.producers_of(member_id)
        if p.method is not ObtainMethod.CRAFTING
    ]
    if not producers:
        return ""

    if sources is None:
        from pipeline.emit.obtain import load_merged_sources

        sources = load_merged_sources()

    structures: set[str] = set()
    for p in producers:
        source = sources.get(p.source_id)
        if source is not None and source.structure:
            structures.add(source.structure)

    if structures:
        return ", ".join(sorted(structures))

    first_note = producers[0].note
    if first_note:
        return first_note

    return ""


def _extract_obtain_fact(
    entity: Entity,
    spec: ObtainFact,
    producer_index: ProducerIndex | None,
    sources: Mapping[str, ChestSource] | None,
) -> str:
    if spec.field == "foundIn":
        return _extract_obtain_found_in(entity.id, producer_index, sources)
    return ""


def extract_fact(
    entity: Entity,
    fact_key: str,
    *,
    producer_index: ProducerIndex | None = None,
    sources: Mapping[str, ChestSource] | None = None,
) -> str:
    """Return the formatted display string for *fact_key* on *entity*.

    Returns an empty string when the entity does not carry the fact,
    which a renderer displays as a blank cell rather than a zero.
    """
    entry = _FACT_REGISTRY.get(fact_key)
    if entry is None:
        return ""

    if isinstance(entry, SectionFact):
        return _extract_section_fact(entity, entry)
    return _extract_obtain_fact(entity, entry, producer_index, sources)
