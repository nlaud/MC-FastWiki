"""Manifest model, the four member-resolution rules, and the loader.

A manifest is one JSON file under ``pipeline/collections/manifests/``.
It names the page, the members, and the columns. It never names a Python
symbol, so adding a collection stays a data change.

The ``rule`` field is a pydantic discriminated union on ``type``, the same
shape ``StructurePlacement`` already uses in ``pipeline/normalize/entity.py``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pipeline.collections import CollectionError

__all__ = [
    "CollectionLayout",
    "CollectionManifest",
    "ColumnDef",
    "ComponentRule",
    "KindRule",
    "ListLayout",
    "ListRule",
    "MemberRule",
    "ObtainRule",
    "SectionRule",
    "TagRule",
    "TreeLayout",
    "load_manifests",
]

MANIFESTS_DIR = Path(__file__).parent / "manifests"


# ---------------------------------------------------------------------------
# Member-resolution rules
# ---------------------------------------------------------------------------


class ComponentRule(BaseModel, frozen=True, populate_by_name=True):
    """Select every item that carries a named item component."""

    type: Literal["component"] = "component"
    component: str = Field(min_length=1)


class TagRule(BaseModel, frozen=True, populate_by_name=True):
    """Select every ID under a vanilla tag, in any registry."""

    type: Literal["tag"] = "tag"
    registry: str = Field(min_length=1)
    tag: str = Field(min_length=1)


class KindRule(BaseModel, frozen=True, populate_by_name=True):
    """Select every entity of a given ``EntityKind``."""

    type: Literal["kind"] = "kind"
    kind: str = Field(min_length=1)


class ListRule(BaseModel, frozen=True, populate_by_name=True):
    """Select an explicit list of entity IDs.

    The escape hatch: when no tag or component covers the members,
    the manifest states them outright. A dozen lines.
    """

    type: Literal["list"] = "list"
    ids: tuple[str, ...] = ()


class SectionRule(BaseModel, frozen=True, populate_by_name=True):
    """Select every entity that carries a named section."""

    type: Literal["section"] = "section"
    section: str = Field(min_length=1)


class ObtainRule(BaseModel, frozen=True, populate_by_name=True):
    """Select every entity that has at least one Producer of the named ObtainMethod."""

    type: Literal["obtain"] = "obtain"
    method: str = Field(min_length=1)


MemberRule = Annotated[
    ComponentRule | TagRule | KindRule | ListRule | SectionRule | ObtainRule,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Layout definition
# ---------------------------------------------------------------------------


class ListLayout(BaseModel, frozen=True, populate_by_name=True):
    """Flat member list layout (default)."""

    type: Literal["list"] = "list"


class TreeLayout(BaseModel, frozen=True, populate_by_name=True):
    """Tree layout grouped by root entity."""

    type: Literal["tree"] = "tree"
    section: str = Field(min_length=1)
    group_order: tuple[str, ...] = Field(default=(), alias="groupOrder")


CollectionLayout = Annotated[
    ListLayout | TreeLayout,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Column definition
# ---------------------------------------------------------------------------


class ColumnDef(BaseModel, frozen=True, populate_by_name=True):
    """One column in the collection table."""

    fact: str = Field(min_length=1)
    label: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# The manifest itself
# ---------------------------------------------------------------------------


class CollectionManifest(BaseModel, frozen=True, populate_by_name=True):
    """One collection page, as declared by a JSON file.

    ``id`` becomes the entity ID ``collection:<id>``. It must satisfy
    ``ENTITY_ID_PATTERN`` once the namespace is prepended.

    ``sortBy`` accepts ``"name"`` or any fact key named in ``columns``.
    ``sortDirection`` defaults to ``"ascending"``.
    ``note`` is the repo's established stand-in for a comment.

    A collection has no sprite of its own -- the wiki publishes no
    ``Invicon Food.png`` -- so its icon is borrowed, and the manifest states
    which one it borrows rather than any code deriving it. Decision 3 forbids
    *constructing* a sprite filename, and neither field does: both name a key
    that something else already resolved through the ``spritefile`` bucket.

    ``iconFrom`` names an entity ID and borrows that entity's own icon. This
    is the safer of the two, because the build fails when the entity is
    absent or iconless, so a typo cannot reach the atlas as a quietly
    unresolved key.

    ``icon`` names a sprite key outright, for a key that belongs to no entity,
    such as one of the curated HUD icons in ``data/curated/hud-sprites.json``.
    No shipped manifest needs it today. It stays because the alternative for
    the first collection that wants a non-entity icon is to widen ``iconFrom``
    into something that no longer means what its name says.

    At most one of the two may be set.
    """

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    blurb: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    icon: str | None = None
    icon_from: str | None = Field(default=None, alias="iconFrom")
    rule: MemberRule
    layout: CollectionLayout = Field(default_factory=ListLayout)
    columns: tuple[ColumnDef, ...] = ()
    sort_by: str | None = Field(default=None, alias="sortBy")
    sort_direction: Literal["ascending", "descending"] = Field(
        default="ascending", alias="sortDirection"
    )
    note: str | None = None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_manifests(
    directory: Path | None = None,
) -> Sequence[CollectionManifest]:
    """Load every ``*.json`` manifest from *directory*, sorted by ``id``.

    Raises ``CollectionError`` on a malformed file or on duplicate IDs.
    """
    root = directory if directory is not None else MANIFESTS_DIR
    if not root.is_dir():
        raise CollectionError(
            f"The manifests directory {root} does not exist. "
            f"There should be at least one .json manifest file in it."
        )

    paths = sorted(root.glob("*.json"))
    if not paths:
        return ()

    manifests: list[CollectionManifest] = []
    seen_ids: dict[str, Path] = {}

    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CollectionError(
                f"Failed to read manifest {path.name}: {exc}"
            ) from exc

        try:
            manifest = CollectionManifest.model_validate(raw)
        except Exception as exc:
            raise CollectionError(
                f"Manifest {path.name} is malformed: {exc}"
            ) from exc

        if manifest.icon is not None and manifest.icon_from is not None:
            raise CollectionError(
                f"Manifest {path.name} sets both 'icon' ({manifest.icon!r}) and 'iconFrom' "
                f"({manifest.icon_from!r}). A collection borrows one icon, so name it one way: "
                f"'iconFrom' to borrow an entity's icon, 'icon' for a key no entity owns."
            )

        if manifest.id in seen_ids:
            raise CollectionError(
                f"Duplicate collection ID {manifest.id!r}: "
                f"declared in both {seen_ids[manifest.id].name} and {path.name}."
            )
        seen_ids[manifest.id] = path

        # Validate sortBy references a valid fact key or "name"
        if manifest.sort_by is not None:
            valid_keys = {"name"} | {col.fact for col in manifest.columns}
            if manifest.sort_by not in valid_keys:
                raise CollectionError(
                    f"Manifest {path.name}: sortBy={manifest.sort_by!r} does not name "
                    f"'name' or any column fact key. Valid keys: {sorted(valid_keys)}."
                )

        if isinstance(manifest.layout, TreeLayout):
            if manifest.columns:
                raise CollectionError(
                    f"Manifest {path.name}: tree layout does not support 'columns'. "
                    f"Tree collections render as an indented hierarchy without tabular columns."
                )
            if manifest.sort_by is not None:
                raise CollectionError(
                    f"Manifest {path.name}: tree layout does not support 'sortBy'. "
                    f"Tree collections are ordered by their hierarchy."
                )

        manifests.append(manifest)

    return sorted(manifests, key=lambda m: m.id)
