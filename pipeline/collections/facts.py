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

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pipeline.collections import CollectionError
from pipeline.normalize.entity import Entity, EntityRef, Section
from pipeline.obtain.chests import ChestSource
from pipeline.obtain.producer import ObtainMethod, ProducerIndex

__all__ = ["FactSource", "FactValue", "ObtainFact", "SectionFact", "extract_fact"]


class FactValue(BaseModel, frozen=True):
    """A formatted fact value, optionally carrying link references."""

    text: str = ""
    refs: tuple[EntityRef, ...] = ()

    @classmethod
    def from_refs(cls, refs: Sequence[EntityRef]) -> FactValue:
        return cls(text=", ".join(r.name for r in refs), refs=tuple(refs))


class SectionFact(BaseModel, frozen=True):
    """A fact read off an already-merged entity section."""

    type: Literal["section"] = "section"
    section_type: str
    attr_name: str = ""
    ref: bool = False
    count: Literal["containers", "distinct_items"] | None = None
    unit: Literal["percent", "ticks_as_time", "ticks_as_operations"] | None = None


class ObtainFact(BaseModel, frozen=True):
    """A fact read off the obtain graph (producers and sources)."""

    type: Literal["obtain"] = "obtain"
    field: str
    method: str | None = None


FactSource = Annotated[SectionFact | ObtainFact, Field(discriminator="type")]


# The fact key namespace maps dotted keys to a FactSource descriptor.
_FACT_REGISTRY: dict[str, FactSource] = {
    "food.nutrition": SectionFact(section_type="FoodInfo", attr_name="nutrition"),
    "food.saturation": SectionFact(section_type="FoodInfo", attr_name="saturation"),
    "enchant.maxLevel": SectionFact(section_type="EnchantInfo", attr_name="max_level"),
    "obtain.foundIn": ObtainFact(field="foundIn"),
    "compost.chance": SectionFact(
        section_type="CompostInfo", attr_name="chance", unit="percent"
    ),
    "fuel.burnTime": SectionFact(
        section_type="FuelInfo", attr_name="burn_time", unit="ticks_as_time"
    ),
    "fuel.operations": SectionFact(
        section_type="FuelInfo", attr_name="burn_time", unit="ticks_as_operations"
    ),
    "chest.containers": SectionFact(
        section_type="ChestLoot", count="containers"
    ),
    "chest.items": SectionFact(
        section_type="ChestLoot", count="distinct_items"
    ),
    "profession.workstation": SectionFact(
        section_type="ProfessionInfo", attr_name="workstation", ref=True
    ),
    "profession.tradeCount": SectionFact(
        section_type="ProfessionInfo", attr_name="trade_count"
    ),
    "obtain.chance": ObtainFact(field="chance", method="bartering"),
    "obtain.stackRange": ObtainFact(field="stackRange", method="bartering"),
    "obtain.perAttempt": ObtainFact(field="perAttempt", method="bartering"),
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


def _extract_section_fact(entity: Entity, spec: SectionFact) -> FactValue:
    section = _get_section(entity, spec.section_type)
    if section is None:
        return FactValue()

    if spec.count == "containers":
        containers = getattr(section, "containers", ())
        return FactValue(text=str(len(containers))) if containers else FactValue()

    if spec.count == "distinct_items":
        containers = getattr(section, "containers", ())
        if not containers:
            return FactValue()
        distinct = {
            item.item.id
            for c in containers
            if hasattr(c, "items")
            for item in c.items
            if hasattr(item, "item")
        }
        return FactValue(text=str(len(distinct)))

    value: object = section
    for part in spec.attr_name.split("."):
        if value is None:
            break
        value = getattr(value, part, None)

    if value is None:
        return FactValue()

    if isinstance(value, EntityRef):
        if not spec.ref:
            raise CollectionError(
                f"Fact '{spec.section_type}.{spec.attr_name}' resolved to an EntityRef "
                f"({value.id}) but the SectionFact did not declare ref=True."
            )
        return FactValue.from_refs([value])

    if spec.ref:
        raise CollectionError(
            f"Fact '{spec.section_type}.{spec.attr_name}' declared ref=True "
            f"but resolved to {type(value).__name__} ({value!r})."
        )

    if spec.unit == "percent":
        return FactValue(text=f"{value}%")
    if spec.unit == "ticks_as_time":
        if isinstance(value, (int, float)):
            if value % 20 == 0:
                return FactValue(text=f"{int(value // 20)}s")
            return FactValue(text=f"{_format_number(value / 20)}s")
        return FactValue(text=f"{value}s")
    if spec.unit == "ticks_as_operations":
        if isinstance(value, (int, float)):
            if value % 200 == 0:
                return FactValue(text=str(int(value // 200)))
            return FactValue(text=_format_number(value / 200))
        return FactValue(text=str(value))

    if isinstance(value, (int, float)):
        return FactValue(text=_format_number(value))

    return FactValue(text=str(value))


def _extract_obtain_found_in(
    member_id: str,
    entities_by_id: Mapping[str, Entity] | None,
    producer_index: ProducerIndex | None,
    sources: Mapping[str, ChestSource] | None,
) -> FactValue:
    if producer_index is None:
        return FactValue()

    producers = [
        p
        for p in producer_index.producers_of(member_id)
        if p.method is not ObtainMethod.CRAFTING
    ]
    if not producers:
        return FactValue()

    if sources is None:
        from pipeline.emit.obtain import load_merged_sources

        sources = load_merged_sources()

    # Group chest sources by structure family name so multi-variant structures (e.g. Shipwreck)
    # expand deterministically while sorting structure families alphabetically.
    family_sources: dict[str, list[ChestSource]] = {}
    for p in producers:
        source = sources.get(p.source_id)
        if source is not None and source.structure:
            family_sources.setdefault(source.structure, []).append(source)

    refs: list[EntityRef] = []
    seen_ids: set[str] = set()

    # A ref is built only from an entity this build actually holds, because its
    # name has to be that structure's own. `structure` is a family label --
    # "Shipwreck" covers `shipwreck` and `shipwreck_beached`, "Village" covers
    # five -- so naming a variant by its family would print "Shipwreck,
    # Shipwreck" and claim a display name no entity carries. A caller with no
    # entity map gets no refs and falls through to the family text below.
    for family in sorted(family_sources):
        for source in family_sources[family]:
            for s_id in source.structure_ref:
                if s_id in seen_ids:
                    continue
                seen_ids.add(s_id)
                if entities_by_id is not None and s_id in entities_by_id:
                    ent = entities_by_id[s_id]
                    refs.append(EntityRef(id=ent.id, name=ent.name))

    if refs:
        return FactValue.from_refs(refs)

    if family_sources:
        return FactValue(text=", ".join(sorted(family_sources)))

    first_note = producers[0].note
    if first_note:
        return FactValue(text=first_note)

    return FactValue()


def _extract_obtain_fact(
    entity: Entity,
    spec: ObtainFact,
    *,
    entities_by_id: Mapping[str, Entity] | None = None,
    producer_index: ProducerIndex | None = None,
    sources: Mapping[str, ChestSource] | None = None,
) -> FactValue:
    if spec.field == "foundIn":
        return _extract_obtain_found_in(entity.id, entities_by_id, producer_index, sources)

    if producer_index is None:
        return FactValue()

    producers = producer_index.producers_of(entity.id)
    if spec.method is not None:
        producers = tuple(p for p in producers if p.method.value == spec.method)

    if not producers:
        return FactValue()

    # A member whose producer carries no odds renders empty cells
    producers_with_odds = [p for p in producers if p.chance is not None]
    if not producers_with_odds:
        return FactValue()

    if spec.field == "chance":
        total_chance = sum(p.chance for p in producers_with_odds if p.chance is not None)
        pct = total_chance * 100
        return FactValue(text=f"{pct:.3f}%")

    if spec.field == "perAttempt":
        total_per_attempt = sum(
            p.per_attempt for p in producers_with_odds if p.per_attempt is not None
        )
        return FactValue(text=f"{total_per_attempt:.3f}")

    if spec.field == "stackRange":
        low = min(p.output.count for p in producers_with_odds)
        high = max(
            p.count_max if p.count_max is not None else p.output.count
            for p in producers_with_odds
        )
        if low == high:
            return FactValue(text=str(low))
        return FactValue(text=f"{low}-{high}")

    return FactValue()


def extract_fact(
    entity: Entity,
    fact_key: str,
    *,
    entities_by_id: Mapping[str, Entity] | None = None,
    producer_index: ProducerIndex | None = None,
    sources: Mapping[str, ChestSource] | None = None,
) -> FactValue:
    """Return the formatted display string and optional refs for *fact_key* on *entity*.

    Returns an empty FactValue when the entity does not carry the fact,
    which a renderer displays as a blank cell rather than a zero.
    """
    entry = _FACT_REGISTRY.get(fact_key)
    if entry is None:
        return FactValue()

    if isinstance(entry, SectionFact):
        return _extract_section_fact(entity, entry)
    return _extract_obtain_fact(
        entity,
        entry,
        entities_by_id=entities_by_id,
        producer_index=producer_index,
        sources=sources,
    )
