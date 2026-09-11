"""Extract fact values from a member entity's already-merged sections.

A column in a collection names a fact key such as ``food.nutrition``.
The fact provider reads it off the **member's own already-merged entity**,
out of its ``FoodInfo`` section, rather than going back to
``item_components``.

This is not an incidental choice. It is what guarantees the Food collection
and the Apple page can never disagree: there is one number, formatted once
at the boundary that already owns it, and both surfaces print it.
``pipeline/extract/food.py`` rounds ``saturation`` exactly once because the
raw component carries float32 noise (``beef`` reads ``1.8000001``,
``suspicious_stew`` reads ``7.2000003``). A collection that re-read the raw
payload would print ``7.2000003`` where the item page prints ``7.2``.

A member missing the fact renders an empty cell, not a zero.
"""

from __future__ import annotations

from pipeline.normalize.entity import Entity, Section

__all__ = ["extract_fact"]


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


# The fact key namespace maps dotted keys to (section_type, attribute_name).
# Each fact key reads from the member's own merged entity.
_FACT_REGISTRY: dict[str, tuple[str, str]] = {
    "food.nutrition": ("FoodInfo", "nutrition"),
    "food.saturation": ("FoodInfo", "saturation"),
    "enchant.maxLevel": ("EnchantInfo", "max_level"),
}


def extract_fact(entity: Entity, fact_key: str) -> str:
    """Return the formatted display string for *fact_key* on *entity*.

    Returns an empty string when the entity does not carry the fact,
    which a renderer displays as a blank cell rather than a zero.
    """
    entry = _FACT_REGISTRY.get(fact_key)
    if entry is None:
        return ""

    section_type, attr_name = entry
    section = _get_section(entity, section_type)
    if section is None:
        return ""

    value = getattr(section, attr_name, None)
    if value is None:
        return ""

    if isinstance(value, (int, float)):
        return _format_number(value)

    return str(value)
