"""Tier C: hand-maintained aliases and overrides, loaded from `/data/curated`.

`/data/curated` did not exist before this task. It holds two documents, each
carrying an envelope of `verifiedFor` (a Minecraft release ID) and a `note`
explaining why the file exists and the bar for adding to it, wrapping the
payload the rest of this module reads:

* `aliases.json` -- extra search terms for a handful of entity IDs, the kind
  of community shorthand no registry ID or wiki display name spells out --
  `gapple` for `minecraft:golden_apple`.
* `overrides.json` -- a partial correction to `name`, `kind`, `icon`, `blurb`,
  or `wikiUrl` for one entity ID, for the rare case where Tier A or Tier B is
  simply wrong and nobody upstream is going to fix it before the next build.

Both are committed, hand-maintained files that a person reviews line by line,
which is why `.gitattributes` deliberately does *not* mark `/data/curated` as
`linguist-generated` the way it marks `/data/dist` -- see that file's own
comment on the pattern. This module is the reader, not the writer: nothing
here mutates either file, and every fault it can name is either a shape fault
in a file this project owns (Tier C is "our own file," so a typo here is our
bug) or a version comparison, never a network read.

## Decision D3: "behind" is a position, never a parsed version string

`verifiedFor` names the Minecraft release a curated entry was last checked
against. Whether that release is *behind* the version this build targets has
to be answered without parsing either string as a number, because
`"1.21.10" < "1.21.4"` is true under ordinary string or dotted-tuple
comparison and false under the game's own ordering -- Minecraft's own version
numbers are not semantic versions, and a parser confident enough to get most
of them right is exactly the parser that gets this one wrong silently.

`release_order` sidesteps the whole class of trap: it is `pipeline.fetch.
version_manifest.VersionManifest.versions`, Mojang's own list, newest first,
and "behind" becomes a question of *position* in that list rather than a
question of arithmetic on the string. A document is stale exactly when its
`verifiedFor` sits at a later position than `target_version` does.

**`target_version` is a separate argument and must not be inferred from
`release_order[0]`.** The manifest lists every snapshot and pre-release
alongside the releases, newest first, so its first entry is almost never the
version a build targets. Measured on 2026-08-31, `release_order[0]` was
`26.3-snapshot-10` while `latest.release` -- the only kind of version
`VersionManifest` lets a build run against -- was `26.2`. Reading the target
off the front of the list therefore reported every curated document as stale
against a snapshot this project will not build, which is the specific noise
that teaches a reader to stop reading the staleness report at all.

A `verifiedFor` that `release_order` does not contain at all is a different
and louder fault: it is not "old," it is a typo or a release Mojang has since
delisted, and treating an unknown string as merely equal to nothing would
hide exactly the mistake this check exists to catch. `load_curated` raises
`NormalizeError` for that case, and for a `target_version` the list does not
know either, rather than silently marking the document stale.

## Stale is a warning, not a rejection

An override verified for the version behind the one this build targets is
still better than no override at all -- Tier C content does not expire the
moment a new Minecraft release ships, and the alternative to "possibly one
version stale" is "Tier A's naive fallback name, unconditionally, forever."
So `load_curated` keeps every stale document's content and reports the
staleness in `CuratedData.stale` for `pipeline.normalize.merge`'s report to
carry forward, exactly the same shape of decision `pipeline.normalize.
reconcile` and `pipeline.enrich` both already make for their own gaps: a
build-time report, never a build-time failure, for a fact about content
rather than a fact about whether the pipeline understood what it read.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from pipeline.normalize import NormalizeError
from pipeline.normalize.entity import ENTITY_ID_PATTERN, EntityKind

__all__ = [
    "ALIASES_FILENAME",
    "OVERRIDES_FILENAME",
    "CuratedData",
    "EntityOverride",
    "StaleDocument",
    "load_curated",
]

# The two documents this module reads, by their file name inside the
# directory `load_curated` is given.
ALIASES_FILENAME = "aliases.json"
OVERRIDES_FILENAME = "overrides.json"


class EntityOverride(BaseModel, frozen=True, populate_by_name=True, extra="forbid"):
    """A hand-written correction to one entity's `name`, `kind`, `icon`, `blurb`, or `wikiUrl`.

    Every field is optional, because an override corrects only the fields
    that are wrong -- an entry that names only `icon` leaves every other
    field to whichever tier the merge would otherwise choose. `extra=
    "forbid"` is deliberate and stricter than most models in this codebase:
    `/data/curated/overrides.json` is this project's own file, so a key that
    is not one of these five is a typo in a file we wrote, not a wiki mid-edit,
    and CLAUDE.md's Tier C rule says that stops the build rather than being
    silently ignored.
    """

    name: str | None = None
    kind: EntityKind | None = None
    icon: str | None = None
    blurb: str | None = None
    wiki_url: str | None = Field(default=None, alias="wikiUrl")


class StaleDocument(BaseModel, frozen=True):
    """One curated document whose `verifiedFor` sits behind the build's target version.

    Carried in `CuratedData.stale` for the merge report, never used to drop
    the document's content -- see the module docstring's "stale is a
    warning" section.
    """

    document: str
    verified_for: str
    current: str


class CuratedData(BaseModel, frozen=True):
    """Everything `load_curated` read from `/data/curated`, ready for the merge stage."""

    aliases: Mapping[str, tuple[str, ...]]
    overrides: Mapping[str, EntityOverride]
    stale: tuple[StaleDocument, ...] = ()


def _read_document(path: Path, *, name: str) -> dict[str, Any]:
    """Return the parsed JSON object of `path`, or raise `NormalizeError`.

    Every fault here is a Tier C shape fault: the file is not readable, is not
    JSON, is not a JSON object, or is missing the `verifiedFor` envelope every
    curated document carries. This project wrote `path`, so any of these
    means a typo in our own file, not an upstream source mid-edit.
    """
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
    verified_for = document.get("verifiedFor")
    if not isinstance(verified_for, str) or not verified_for:
        raise NormalizeError(f"{name} carries no string verifiedFor field.")
    return document


def _parse_aliases(document: Mapping[str, Any], *, name: str) -> dict[str, tuple[str, ...]]:
    """Return the `entityId -> aliases` map of `aliases.json`, or raise `NormalizeError`."""
    raw = document.get("aliases", {})
    if not isinstance(raw, dict):
        raise NormalizeError(f"{name}'s 'aliases' is {raw!r}, not an object.")
    parsed: dict[str, tuple[str, ...]] = {}
    for entity_id, values in raw.items():
        if not isinstance(entity_id, str) or ENTITY_ID_PATTERN.fullmatch(entity_id) is None:
            raise NormalizeError(
                f"{name} names {entity_id!r} as an alias key, which is not a valid entity ID "
                f"matching {ENTITY_ID_PATTERN.pattern!r}."
            )
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise NormalizeError(
                f"{name}'s aliases for {entity_id!r} is {values!r}, not a list of strings."
            )
        parsed[entity_id] = tuple(values)
    return parsed


def _parse_overrides(document: Mapping[str, Any], *, name: str) -> dict[str, EntityOverride]:
    """Return the `entityId -> EntityOverride` map of `overrides.json`, or raise on a fault."""
    raw = document.get("entities", {})
    if not isinstance(raw, dict):
        raise NormalizeError(f"{name}'s 'entities' is {raw!r}, not an object.")
    parsed: dict[str, EntityOverride] = {}
    for entity_id, payload in raw.items():
        if not isinstance(entity_id, str) or ENTITY_ID_PATTERN.fullmatch(entity_id) is None:
            raise NormalizeError(
                f"{name} names {entity_id!r} as an override key, which is not a valid entity ID "
                f"matching {ENTITY_ID_PATTERN.pattern!r}."
            )
        try:
            parsed[entity_id] = EntityOverride.model_validate(payload)
        except ValidationError as error:
            raise NormalizeError(
                f"{name}'s override for {entity_id!r} is malformed: {error}"
            ) from error
    return parsed


def load_curated(
    directory: Path, *, release_order: Sequence[str], target_version: str
) -> CuratedData:
    """Return the curated aliases and overrides of `directory`, or raise `NormalizeError`.

    Pure over the filesystem: reads `aliases.json` and `overrides.json` from
    `directory` and touches no network. `release_order` is Mojang's own
    ordering, newest first -- `pipeline.fetch.version_manifest.
    VersionManifest.versions`'s IDs -- and `target_version` is the release
    this build is running against, which is
    `VersionManifest.latest_release_id` rather than the front of the list.
    The module docstring's Decision D3 section holds both halves of the
    reasoning: why position rather than a parsed version string answers
    "behind," and why the target cannot be read off `release_order[0]`.

    Raises when `release_order` is empty, because there is then no version to
    judge staleness against at all. Raises when `target_version`, or a
    document's `verifiedFor`, names a release `release_order` does not
    contain -- a typo in this project's own file, not a version comparison
    that can be silently skipped. Raises when either document is missing, is
    not JSON, is not an object, or holds a malformed alias list or override.
    Never raises for a document that is merely behind the target version;
    that is `CuratedData.stale`'s job to carry, not a build-stopping fault.
    """
    if not release_order:
        raise NormalizeError(
            "load_curated was given an empty release_order, so there is no version to judge "
            "a curated document's verifiedFor against."
        )
    try:
        target_position = release_order.index(target_version)
    except ValueError as error:
        raise NormalizeError(
            f"load_curated was given target_version={target_version!r}, which release_order does "
            f"not contain. The target of a build is one of Mojang's own version IDs, so a target "
            f"the manifest does not name is a caller bug rather than a version to compare."
        ) from error

    aliases_document = _read_document(directory / ALIASES_FILENAME, name=ALIASES_FILENAME)
    overrides_document = _read_document(directory / OVERRIDES_FILENAME, name=OVERRIDES_FILENAME)

    aliases = _parse_aliases(aliases_document, name=ALIASES_FILENAME)
    overrides = _parse_overrides(overrides_document, name=OVERRIDES_FILENAME)

    stale: list[StaleDocument] = []
    for filename, document in (
        (ALIASES_FILENAME, aliases_document),
        (OVERRIDES_FILENAME, overrides_document),
    ):
        verified_for = document["verifiedFor"]
        try:
            position = release_order.index(verified_for)
        except ValueError as error:
            raise NormalizeError(
                f"{filename} names verifiedFor={verified_for!r}, which release_order does not "
                f"contain. A verifiedFor that names no known release is a typo, not a version "
                f"behind the target -- comparing it as equal to anything would hide the typo."
            ) from error
        if position > target_position:
            stale.append(
                StaleDocument(document=filename, verified_for=verified_for, current=target_version)
            )

    return CuratedData(aliases=aliases, overrides=overrides, stale=tuple(stale))
