"""Loader and tier expander for curated facts (compostable and fuel).

Reads `data/curated/compostable.json` and `data/curated/fuel.json`.
Expands tier tags through `TagIndex`, resolves explicit-ID precedence,
checks for staleness against `release_order`, and raises on the five faults:

1. An ID listed explicitly in two tiers.
2. An ID, or a tag member, that names no entity in this build.
3. A tag that resolves to zero members, meaning upstream renamed or dropped it.
4. A chance outside 1 to 100, or a burn time that is not a positive integer.
5. A `verifiedFor` release that `release_order` does not contain.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pipeline.extract.tags import TagIndex
from pipeline.normalize import NormalizeError
from pipeline.normalize.curated import StaleDocument

__all__ = [
    "COMPOSTABLE_FILENAME",
    "FUEL_FILENAME",
    "CuratedFacts",
    "CuratedFactsReport",
    "FactOverride",
    "load_curated_facts",
]

COMPOSTABLE_FILENAME = "compostable.json"
FUEL_FILENAME = "fuel.json"


class FactOverride(BaseModel, frozen=True):
    """An explicit ID overriding tag membership from another tier."""

    entity_id: str
    from_value: int
    to_value: int
    tag_tier: int
    explicit_tier: int


class CuratedFactsReport(BaseModel, frozen=True):
    """Diagnostics and overrides from expanding curated fact tiers."""

    compost_overrides: tuple[FactOverride, ...] = ()
    fuel_overrides: tuple[FactOverride, ...] = ()
    stale: tuple[StaleDocument, ...] = ()

    @property
    def overrides(self) -> tuple[FactOverride, ...]:
        return (*self.compost_overrides, *self.fuel_overrides)

    @property
    def all_overrides(self) -> tuple[str, ...]:
        return tuple(
            f"{o.entity_id} ({o.from_value} -> {o.to_value})"
            for o in self.overrides
        )


class CuratedFacts(BaseModel, frozen=True):
    """Resolved entity facts read from `/data/curated`."""

    compostable: Mapping[str, int]
    fuel: Mapping[str, int]
    report: CuratedFactsReport


def _read_json_object(path: Path, *, name: str) -> dict[str, Any]:
    """Read and return a JSON object from `path`, or raise `NormalizeError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise NormalizeError(f"{name} could not be read at {path}: {error}") from error
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise NormalizeError(f"{name} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise NormalizeError(
            f"{name} is a JSON {type(document).__name__} at the top level, not an object."
        )
    return document


def _check_version(
    document: Mapping[str, Any],
    *,
    name: str,
    release_order: Sequence[str],
    target_version: str,
) -> StaleDocument | None:
    """Validate `verifiedFor` against `release_order` (Fault 5) and report staleness."""
    verified_for = document.get("verifiedFor")
    if not isinstance(verified_for, str) or not verified_for:
        raise NormalizeError(f"{name} carries no string verifiedFor field.")
    try:
        position = release_order.index(verified_for)
    except ValueError as error:
        raise NormalizeError(
            f"{name} names verifiedFor={verified_for!r}, which release_order does not "
            f"contain. A verifiedFor that names no known release is a typo, not a version "
            f"behind the target -- comparing it as equal to anything would hide the typo."
        ) from error
    try:
        target_position = release_order.index(target_version)
    except ValueError as error:
        raise NormalizeError(
            f"load_curated_facts was given target_version={target_version!r}, which release_order "
            f"does not contain."
        ) from error

    if position > target_position:
        return StaleDocument(document=name, verified_for=verified_for, current=target_version)
    return None


def _expand_fact_tiers(
    document: Mapping[str, Any],
    *,
    name: str,
    value_key: str,
    is_chance: bool,
    item_tags: TagIndex,
    known_entity_ids: set[str],
) -> tuple[dict[str, int], list[FactOverride]]:
    """Expand tiers of tags and items into an entity_id -> value map."""
    raw_tiers = document.get("tiers")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise NormalizeError(f"{name} has no valid non-empty 'tiers' list.")

    # Global exclude tags
    global_exclude_tags = document.get("excludeTags", [])
    if not isinstance(global_exclude_tags, list):
        raise NormalizeError(f"{name}'s 'excludeTags' must be a list of strings.")

    excluded_ids: set[str] = set()
    for tag_name in global_exclude_tags:
        if not isinstance(tag_name, str):
            raise NormalizeError(f"{name} excludeTag {tag_name!r} is not a string.")
        if not item_tags.holds(tag_name):
            raise NormalizeError(f"{name} names tag {tag_name!r}, which resolved to zero members.")
        resolved = item_tags.resolve(tag_name)
        if not resolved:
            raise NormalizeError(f"{name} names tag {tag_name!r}, which resolved to zero members.")
        excluded_ids.update(resolved)

    seen_explicit: dict[str, int] = {}
    tag_members_by_tier: dict[int, set[str]] = {}

    for idx, raw_tier in enumerate(raw_tiers):
        if not isinstance(raw_tier, dict):
            raise NormalizeError(f"{name} tier {idx} is not an object.")

        value = raw_tier.get(value_key)
        # Fault 4: validate value
        if is_chance:
            if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 100):
                raise NormalizeError(
                    f"{name} tier chance {value!r} is outside 1 to 100."
                )
        else:
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise NormalizeError(
                    f"{name} tier burn time {value!r} is not a positive integer."
                )

        explicit_items = raw_tier.get("items", [])
        if not isinstance(explicit_items, list):
            raise NormalizeError(f"{name} tier {value} 'items' is not a list.")

        for item in explicit_items:
            if not isinstance(item, str):
                raise NormalizeError(f"{name} tier {value} contains non-string item {item!r}.")
            # Fault 1: duplicate explicit item
            if item in seen_explicit:
                raise NormalizeError(
                    f"{name} lists {item!r} explicitly in multiple tiers "
                    f"({seen_explicit[item]}, {value})."
                )
            # Fault 2: explicit item not in build
            if item not in known_entity_ids:
                raise NormalizeError(
                    f"{name} explicitly names {item!r}, which names no entity in this build."
                )
            seen_explicit[item] = value

        tags = raw_tier.get("tags", [])
        if not isinstance(tags, list):
            raise NormalizeError(f"{name} tier {value} 'tags' is not a list.")

        tier_tag_members: set[str] = set()
        for tag_name in tags:
            if not isinstance(tag_name, str):
                raise NormalizeError(f"{name} tier {value} contains non-string tag {tag_name!r}.")
            # Fault 3: tag resolves to 0 members
            if not item_tags.holds(tag_name):
                raise NormalizeError(
                    f"{name} names tag {tag_name!r}, which resolved to zero members."
                )
            members = item_tags.resolve(tag_name)
            if not members:
                raise NormalizeError(
                    f"{name} names tag {tag_name!r}, which resolved to zero members."
                )
            # Filter excluded tags
            active_members = set(members) - excluded_ids
            for member in active_members:
                # Fault 2: tag member not in build
                if member not in known_entity_ids:
                    raise NormalizeError(
                        f"{name} tag {tag_name!r} member {member!r} names no entity in this build."
                    )
                tier_tag_members.add(member)

        if value not in tag_members_by_tier:
            tag_members_by_tier[value] = set()
        tag_members_by_tier[value].update(tier_tag_members)

    tag_assigned: dict[str, int] = {}
    for tier_val, tier_members in tag_members_by_tier.items():
        for m in tier_members:
            if m in tag_assigned and tag_assigned[m] != tier_val:
                raise NormalizeError(
                    f"{name} has conflicting tag membership for {m!r} between tiers "
                    f"{tag_assigned[m]} and {tier_val}."
                )
            tag_assigned[m] = tier_val

    # Apply explicit ID precedence
    final_map: dict[str, int] = dict(tag_assigned)
    overrides: list[FactOverride] = []

    for item, explicit_value in seen_explicit.items():
        if item in tag_assigned and tag_assigned[item] != explicit_value:
            overrides.append(
                FactOverride(
                    entity_id=item,
                    from_value=tag_assigned[item],
                    to_value=explicit_value,
                    tag_tier=tag_assigned[item],
                    explicit_tier=explicit_value,
                )
            )
        final_map[item] = explicit_value

    return final_map, overrides


def load_curated_facts(
    directory: Path,
    *,
    item_tags: TagIndex,
    known_entity_ids: set[str],
    release_order: Sequence[str],
    target_version: str,
) -> CuratedFacts:
    """Load and expand `compostable.json` and `fuel.json` from `directory`.

    Raises `NormalizeError` on any of the five documented faults.
    """
    if not release_order:
        raise NormalizeError("load_curated_facts was given an empty release_order.")

    compost_path = directory / COMPOSTABLE_FILENAME
    fuel_path = directory / FUEL_FILENAME

    compost_doc = _read_json_object(compost_path, name=COMPOSTABLE_FILENAME)
    fuel_doc = _read_json_object(fuel_path, name=FUEL_FILENAME)

    stale: list[StaleDocument] = []
    c_stale = _check_version(
        compost_doc,
        name=COMPOSTABLE_FILENAME,
        release_order=release_order,
        target_version=target_version,
    )
    if c_stale is not None:
        stale.append(c_stale)

    f_stale = _check_version(
        fuel_doc,
        name=FUEL_FILENAME,
        release_order=release_order,
        target_version=target_version,
    )
    if f_stale is not None:
        stale.append(f_stale)

    compostable_map, compost_overrides = _expand_fact_tiers(
        compost_doc,
        name=COMPOSTABLE_FILENAME,
        value_key="chance",
        is_chance=True,
        item_tags=item_tags,
        known_entity_ids=known_entity_ids,
    )

    fuel_map, fuel_overrides = _expand_fact_tiers(
        fuel_doc,
        name=FUEL_FILENAME,
        value_key="burnTime",
        is_chance=False,
        item_tags=item_tags,
        known_entity_ids=known_entity_ids,
    )

    report = CuratedFactsReport(
        compost_overrides=tuple(sorted(compost_overrides, key=lambda o: o.entity_id)),
        fuel_overrides=tuple(sorted(fuel_overrides, key=lambda o: o.entity_id)),
        stale=tuple(stale),
    )

    return CuratedFacts(
        compostable=compostable_map,
        fuel=fuel_map,
        report=report,
    )
