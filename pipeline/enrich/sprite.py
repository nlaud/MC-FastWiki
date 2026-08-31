"""The `spritefile` bucket: which wiki-hosted image draws each icon.

Phase 4's search index and Phase 6's renderers both need one thing per entity: a
small image to put next to its name. The wiki does not serve that image under
the entity's own title. It catalogues every sprite it has cropped out of a
texture atlas or drawn for the wiki chrome in one bucket, `spritefile`, keyed by
a sprite *family* and an *id* within that family -- `InvSprite` "Raw Iron",
`BlockSprite` "acacia-button". This module reads that bucket and returns the
table `pipeline.normalize.reconcile` joins against a registry ID.

Three facts about the live table matter enough to shape this module. All three
were checked against `https://minecraft.wiki/api.php` on 2026-08-30.

1. **`Bucket:Spritefile` has four fields, and no `edition` field.** The schema
   page declares `name` (TEXT), `id` (TEXT), `file` (PAGE), and `deprecated`
   (BOOLEAN), plus the `page_name` every bucket carries. Selecting a field the
   schema does not have, such as `sprite_name`, answers HTTP 200 with
   `"error": "Field sprite_name not found in bucket spritefile."` -- the same
   quiet failure `pipeline.fetch.bucket` names as fact 2 of its own docstring.
   There being no `edition` column matters more than it first looks: every other
   bucket this pipeline reads carries Bedrock rows somewhere and hides the
   Java/Bedrock split behind a field. This one draws the split along the
   *family* instead. `VANILLA_FAMILIES` below is that split, so this module's
   `where` clause is empty and its family filter does the job an `edition`
   column would otherwise do.

2. **The table holds 20,013 rows across roughly 40 families, and most of them
   are not this project's concern.** `InvSprite` (4,953), `BlockSprite`
   (3,519), `ItemSprite` (3,044), and `EntitySprite` (1,383) are the four big
   Java Edition families. `Legacy*` (Legacy Console Edition, out of scope
   alongside Bedrock per CLAUDE.md's non-negotiable 1) and the families of
   other Mojang products -- Dungeons, Legends, Story Mode, Lego, a `Persona`
   skin line, a wiki `Movie`, and `Skin` itself -- add up to about 6,000 more
   rows that this project has no page to attach them to. `VANILLA_FAMILIES`
   names the ones this project draws from, and everything else is counted and
   dropped before the row-level checks below ever run, so the row-level report
   stays about content this project wanted and could not read, not about
   content it never wanted.

3. **A row can lack `name`, `id`, or `file`, and one row in roughly fifty
   claims to be `deprecated`.** None of the 20,013 rows sampled were missing
   any of the three required fields, and the `deprecated` field is either
   absent (19,604 rows -- the field was never set on that page) or the empty
   string (409 rows). An empty string is falsy under Python's own `bool()`,
   so both shapes read today as "not deprecated," and this module still parses
   whatever the field holds rather than assume the wiki will keep answering it
   the same way. `115` of the 4,953 `InvSprite` rows name a file that does not
   follow the `Invicon <Name>.png` pattern -- `Pancake Stack` names
   `File:PancakeInvSprite.png`, and `Sculk Block` names a `.gif`, not a `.png`
   -- so `file` is always read from the row and never guessed at from `id`.

The rows this module returns are still wiki facts, not files. `pipeline.fetch`
imageinfo.py` turns a `file` title into a URL and a hash, and
`pipeline.fetch.sprites` turns that into bytes on disk. This module's only job
is the bucket read: which family and id one wiki-hosted image answers to.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import EnrichError, SkippedRow, optional_text, row_page_name
from pipeline.fetch import Transport
from pipeline.fetch.bucket import fetch_bucket_rows
from pipeline.fetch.cache import ContentCache

__all__ = [
    "BUCKET",
    "COLUMNS",
    "FILE_NAMESPACE",
    "VANILLA_FAMILIES",
    "SpriteFile",
    "SpriteIndex",
    "fetch_sprite_index",
    "parse_sprite_files",
]

BUCKET = "spritefile"

# The columns this stage selects. There is no `edition` column to add to this
# list -- see fact 1 of the module docstring -- so `VANILLA_FAMILIES` is the
# only edition filter this module has.
COLUMNS = ("page_name", "name", "id", "file", "deprecated")

# The prefix of a wiki `File:` page. `resolve_icon` never builds one of these
# from a registry ID or a display name; it always reads the one the bucket row
# names, because fact 3 of the module docstring records 115 `InvSprite` rows
# that do not follow the pattern a guess would assume.
FILE_NAMESPACE = "File:"

# The sprite families this project draws icons from, each with its row count on
# 2026-08-30 for a reader who wants to sanity-check a future recount.
#
# `InvSprite`, `BlockSprite`, and `ItemSprite` cover the item and block icons
# Phase 6 needs. `EntitySprite` covers mobs. `EffectSprite` and `BiomeSprite`
# cover the status-effect and biome registries this project also reconciles.
# `EnvSprite` covers the structures and other world features that the
# collections stage of Phase 2 groups pages by. `AchievementSprite` and
# `NewAchievementSprite` cover the two advancement icon styles the wiki has
# used across Minecraft's history -- one bucket row per icon, and both eras
# still appear in `pipeline.enrich.advancement`'s table.
#
# Everything else is another product or another edition, and is out of scope
# for the same reason CLAUDE.md's non-negotiable 1 keeps Bedrock numbers off
# the screen: `DungeonsEntitySprite`, `LegendsSprite`, `StoryModeItemSprite`,
# `LegoSprite`, `PersonaSprite`, `MovieSprite`, and `SkinSprite` (and their
# many `Dungeons*`/`Legends*`/`StoryMode*` siblings) draw icons for Minecraft
# Dungeons, Minecraft Legends, Minecraft Story Mode, Minecraft: Education
# Edition's LEGO tie-in, wiki editor personas, wiki-hosted trailers, and player
# skins -- none of them the Java Edition reference this project builds.
# `LegacyBlockSprite` and `LegacyEntitySprite` draw icons for Legacy Console
# Edition, which sits alongside Bedrock as an edition this project does not
# cover.
VANILLA_FAMILIES = frozenset(
    {
        "InvSprite",  # 4953
        "BlockSprite",  # 3519
        "ItemSprite",  # 3044
        "EntitySprite",  # 1383
        "EnvSprite",  # 435
        "EffectSprite",  # 148
        "AchievementSprite",  # 175
        "BiomeSprite",  # 115
        "NewAchievementSprite",  # 136
    }
)


class SpriteFile(BaseModel, frozen=True):
    """One sprite the wiki has cropped or drawn, and the `File:` page that holds it."""

    family: str
    sprite_id: str
    file_title: str
    # Falsy on both shapes the live table uses today -- an absent field and an
    # empty string. See fact 3 of the module docstring.
    deprecated: bool = False
    # The bucket row's own page, kept for the same provenance reason every
    # other `pipeline.enrich` model keeps one: it is the wiki fact this row
    # came from, not necessarily the entity's own article.
    page: str


def _index_by_family(entries: Sequence[SpriteFile]) -> dict[str, dict[str, SpriteFile]]:
    """Return `entries` as a family, then a sprite id, then the entry itself.

    `parse_sprite_files` never produces two entries of one `(family,
    sprite_id)` pair -- an exact duplicate is dropped and a conflicting one
    becomes a `SkippedRow` -- so the inner dictionary never loses an entry to a
    later one silently. A `SpriteIndex` built by hand without going through
    `parse_sprite_files` gets no such promise, which is exactly why the
    validator below recomputes this and refuses a mismatch.
    """
    index: dict[str, dict[str, SpriteFile]] = {}
    for entry in entries:
        index.setdefault(entry.family, {})[entry.sprite_id] = entry
    return index


class SpriteIndex(BaseModel, frozen=True):
    """Every sprite this project reads from the wiki, indexed for a fast lookup.

    Build it with `SpriteIndex.build`. `by_family` is a field rather than a
    derived property for the reason `pipeline.enrich.resource_location.JoinTable`
    gives in full: the index is read once per registry ID by the reconciliation
    stage and built once here, and a frozen model cannot memoize. The validator
    recomputes it and refuses a table whose index does not match its own
    entries, so a hand-assembled index that disagrees with its own rows fails at
    construction instead of answering a lookup its entries do not support.
    """

    entries: tuple[SpriteFile, ...]
    by_family: Mapping[str, Mapping[str, SpriteFile]]
    # How many rows this build dropped for being another product's family. Kept
    # as a count and not a `SkippedRow` per row: the module docstring explains
    # why roughly 6,000 rows of Dungeons, Legends, Story Mode, Lego, Persona,
    # Movie, Skin, and Legacy Console sprites are content this project never
    # wanted, which is a different fact from content it wanted and could not
    # read.
    other_products: int = 0
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls,
        entries: Sequence[SpriteFile],
        skipped: Sequence[SkippedRow] = (),
        *,
        other_products: int = 0,
    ) -> "SpriteIndex":
        """Return an index over `entries`, with `by_family` computed from them."""
        return cls(
            entries=tuple(entries),
            by_family=_index_by_family(entries),
            other_products=other_products,
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _index_must_match_the_entries(self) -> "SpriteIndex":
        """Refuse an index whose `by_family` is not the index of its own entries."""
        expected = _index_by_family(self.entries)
        actual = {family: dict(table) for family, table in self.by_family.items()}
        if actual != expected:
            raise EnrichError("the family index does not match the entries of this sprite index.")
        return self

    def lookup(self, family: str, sprite_id: str) -> SpriteFile | None:
        """Return the sprite of `sprite_id` within `family`, or `None`.

        The lookup is exact, for the reason `JoinTable.candidates` gives: a
        fuzzy fallback here would hide a join that broke instead of reporting
        it, and every id that reaches this call already came from the same
        wiki that wrote the sprite table.
        """
        return self.by_family.get(family, {}).get(sprite_id)

    def file_titles(self) -> tuple[str, ...]:
        """Return the distinct `File:` titles this index holds, sorted.

        `pipeline.fetch.imageinfo` batches a read of every one of these, so a
        caller wants the set once rather than walking `entries` itself and
        re-deriving it -- several families can point at the same file, `Sculk
        Block`'s alias being one live example.
        """
        return tuple(sorted({entry.file_title for entry in self.entries}))


def parse_sprite_files(rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET) -> SpriteIndex:
    """Return the sprite index over `rows`, and a report of what was dropped.

    Pure: the rows go in as the API returned them and no network is touched.

    The family filter runs first and produces no `SkippedRow` at all --
    `SpriteIndex.other_products` counts it instead. The module docstring
    explains why: about 6,000 of the 20,013 rows belong to a product or an
    edition this project does not cover, and reporting each one individually
    would bury the row-level faults this function does want a person to see
    under six thousand lines that say nothing is wrong. A row with no `name` at
    all is swept into the same count, because a family this project can name
    cannot come from a blank field, and there is no more specific claim to make
    about it than "this is not one of the families this project reads."

    What survives the family filter is checked row by row, in this order:

    1. A missing `id` or `file` is a `SkippedRow`. The field was selected and
       the wiki answered nothing for it, which the module docstring's fact 3
       says has not happened yet but the row-level rule handles it anyway,
       the way `pipeline.enrich.resource_location` handles a resource
       location field the API has never been seen to omit.
    2. A `file` that does not start with `File:` is a `SkippedRow` naming the
       value. Nothing downstream can read a title in another namespace as an
       image.
    3. An exact duplicate `(family, sprite_id, file)` is dropped quietly --
       the bucket writes one row per wiki page that mentions the pair, the
       same reason `JoinTable` dedupes on `(display_name, registry_id, kind)`.
       A duplicate `(family, sprite_id)` whose `file` disagrees is a
       `SkippedRow` instead of a last-write-wins pick: two different images
       claiming one sprite id is a wiki fact in conflict with itself, and
       guessing which one is current is exactly the guess `resolve_icon` is
       built to refuse making.
    """
    if not rows:
        raise EnrichError(
            f"{source} answered no rows. An empty spritefile read is a failure to report, "
            f"not an empty index."
        )

    skipped: list[SkippedRow] = []
    other_products = 0
    kept: dict[tuple[str, str], SpriteFile] = {}
    order: list[tuple[str, str]] = []

    for row in rows:
        page = row_page_name(row, source=source)
        family = optional_text(row, "name")
        if family is None or family not in VANILLA_FAMILIES:
            other_products += 1
            continue
        sprite_id = optional_text(row, "id")
        if sprite_id is None:
            skipped.append(SkippedRow(page=page, subject=family, reason="the row has no sprite id"))
            continue
        file_title = optional_text(row, "file")
        if file_title is None:
            skipped.append(
                SkippedRow(
                    page=page, subject=f"{family} {sprite_id}", reason="the row has no file"
                )
            )
            continue
        if not file_title.startswith(FILE_NAMESPACE):
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=f"{family} {sprite_id}",
                    reason=f"the file {file_title!r} does not start with {FILE_NAMESPACE!r}",
                )
            )
            continue
        # The schema types this BOOLEAN, and the live table's only shapes for a
        # set value are an absent key and the empty string -- both falsy under
        # `bool()`, per fact 3 of the module docstring. Reading it this way
        # rather than testing for a specific true-ish string also reads a real
        # `True`/`"1"` correctly if the wiki ever answers one.
        deprecated = bool(row.get("deprecated"))
        key = (family, sprite_id)
        existing = kept.get(key)
        if existing is not None:
            if existing.file_title != file_title:
                skipped.append(
                    SkippedRow(
                        page=page,
                        subject=f"{family} {sprite_id}",
                        reason=(
                            f"this id already names {existing.file_title!r}, and this row "
                            f"names {file_title!r}"
                        ),
                    )
                )
            continue
        kept[key] = SpriteFile(
            family=family,
            sprite_id=sprite_id,
            file_title=file_title,
            deprecated=deprecated,
            page=page,
        )
        order.append(key)

    entries = tuple(kept[key] for key in order)
    return SpriteIndex.build(entries, skipped, other_products=other_products)


def fetch_sprite_index(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> SpriteIndex:
    """Fetch the `spritefile` bucket and return the sprite index.

    `revision` names the cache generation, as `fetch_bucket_rows` requires. No
    `where` clause narrows this read, because there is no `edition` column to
    narrow it by -- see fact 1 of the module docstring. Every row of the
    bucket crosses the wire, and `parse_sprite_files` does the filtering that a
    `where` clause does for `pipeline.enrich.resource_location`.
    """
    rows = fetch_bucket_rows(BUCKET, COLUMNS, revision=revision, cache=cache, transport=transport)
    return parse_sprite_files(rows)
