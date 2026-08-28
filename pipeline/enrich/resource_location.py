"""The join table: a wiki display name to a vanilla registry ID.

This is the first stage of Tier B and the one every other stage waits on. The
wiki names things the way a player reads them -- `Bottle o' Enchanting`, `Block
of Gold` -- and the vanilla data names them the way the game stores them --
`experience_bottle`, `gold_block`. Every other bucket writes display names:
`droptable` says the mob dropped `Rotten Flesh`, `trade` says the villager wants
`Paper`, `crafting_recipe` says the output is `Block of Gold`. None of them says
a registry ID. So without this table nothing Tier B produces can be attached to
the Tier A entity it belongs to.

CLAUDE.md states the rule as a gotcha: the wiki's `display_name` does not always
match the vanilla registry name, so always join through the `resource_location`
bucket. What that sentence does not say is how much of the bucket has to be
thrown away first.

**The raw table is mostly not about Minecraft.** 5,000-plus rows, of which 3,690
are Java. Of those, 966 come from `User:`, `Minecraft Wiki:`, and `Forum:`
pages: `User:Hipposgrumm/Memes/Bucketolotl`, the Hebrew and Toki Pona
translation projects, and sandbox drafts of potions that do not exist. A
translation row is the dangerous kind, because it is well-formed: it maps the
Turkish display name `Taş` to `stone` and the Toki Pona `poki moku` to `bowl`.
Nothing about the row says it is a translation -- only the page it sits on does.
The namespace filter in `pipeline.enrich` drops all 966 and takes the ambiguous
display names from 25 down to 16.

**A row may have no `resource_location` at all.** The Bucket API omits a field
whose value is null, so 29 main-namespace rows arrive with a display name and
nothing to join it to. They are removed content and April Fools' blocks --
`Etho Slab`, `Horse Saddle`, `Dirt (Minecraft 4k)`. They are skipped and
reported, not defaulted.

**The remaining 16 ambiguities are real and are not this module's to resolve.**
`kind` settles two of them: `Eye of Ender` is both the item `ender_eye` and the
entity `eye_of_ender`, and `Obsidian Boat` is both an item and a boat entity.
The other 14 it cannot touch. `Air` is both `air` and `air_block`, and both are
blocks. `Music Disc` is the display name of all 23 discs. `Villager` is both
`villager` and `nitwit`. So `resolve` refuses to choose: it returns one ID or it
raises, and `candidates` is there for a caller that wants to see the choice. A
join table that guessed would put a wrong registry ID on a wiki fact, which is
the exact failure mode this table exists to prevent.

**A pair is written once per page that mentions it, so the table is
deduplicated.** `Stone` maps to `stone` on 14 separate pages. 2,724 surviving
rows carry 2,457 distinct entries, and without the dedupe every repeated name
would read as ambiguous.

The table is built by `parse_resource_locations`, which is pure. The Java filter
lives in the parser rather than in the query, so one place decides it; the fetch
function still sends `where('edition','java')` because it halves the rows on the
wire, not because it is the filter of record.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import (
    EnrichError,
    SkippedRow,
    clean_text,
    group_by,
    main_namespace,
    optional_text,
    row_json,
    row_page_name,
    wiki_url,
)
from pipeline.fetch import Transport
from pipeline.fetch.bucket import fetch_bucket_rows
from pipeline.fetch.cache import ContentCache

__all__ = [
    "BUCKET",
    "COLUMNS",
    "JAVA_EDITION",
    "KNOWN_KINDS",
    "NAMESPACE",
    "NO_DISPLAY_NAME",
    "JoinTable",
    "ResourceLocation",
    "fetch_join_table",
    "parse_resource_locations",
]

BUCKET = "resource_location"

# The columns this stage selects. `page_name` carries the namespace and the
# attribution URL; `json` carries `Type`, which is the only thing that separates
# an item from an entity of the same name.
COLUMNS = ("page_name", "edition", "display_name", "resource_location", "json")

# The value of the `Edition` field that this project keeps. Non-negotiable 1.
JAVA_EDITION = "java"

# The namespace of a vanilla registry ID. The bucket stores the path alone --
# `stone`, not `minecraft:stone` -- and CLAUDE.md requires that IDs be
# namespaced everywhere downstream, so `ResourceLocation.registry_id` adds it.
NAMESPACE = "minecraft"

# What the wiki writes as the display name of a page that has none. It is
# content, not an empty field, so `text_or_none` cannot catch it.
NO_DISPLAY_NAME = "No displayed name"

# The `Type` values observed across the 2,724 main-namespace Java rows on
# 2026-08-27, with their counts: block 1502, item 788, entity 168, env 82,
# biome 65, effect 49, and 70 rows with no `Type` at all -- the enchantments,
# which the wiki does not classify.
#
# This is documentation and a test fixture, not a whitelist. `kind` stays a
# plain lowercase string so that a type the wiki adds next year arrives intact
# instead of failing a build over a value that is merely new.
KNOWN_KINDS = frozenset({"block", "item", "entity", "env", "biome", "effect"})


class ResourceLocation(BaseModel, frozen=True):
    """One display name, and the registry ID the wiki says it means."""

    display_name: str
    # The registry path, unprefixed, exactly as the bucket stores it.
    resource_location: str
    # The wiki's `Type`. Lowercased. `None` for the rows the wiki leaves
    # unclassified, which are the enchantments.
    kind: str | None
    # The main-namespace page the row was written on, and its article URL. The
    # licence obliges attribution, and the page is also where a later stage goes
    # for the blurb and the infobox.
    page: str
    wiki_url: str

    @property
    def registry_id(self) -> str:
        """Return the namespaced ID, which is what every other stage keys on."""
        if ":" in self.resource_location:
            return self.resource_location
        return f"{NAMESPACE}:{self.resource_location}"


class JoinTable(BaseModel, frozen=True):
    """Every display name the wiki maps to a registry ID, and both lookups.

    Build it with `JoinTable.build`. The two indexes are fields rather than
    derived-on-read properties because the table is read thousands of times by
    later stages and built once, and because a frozen model cannot memoize. The
    validator below recomputes them, so a table assembled by hand with an index
    that does not match its entries fails at construction instead of answering
    lookups that the entries do not support.

    Both directions are needed. Display name to ID is the join every other
    bucket performs. ID to display name is what the Tier A/Tier B
    reconciliation report walks, to name the vanilla entities the wiki has no
    page for.
    """

    entries: tuple[ResourceLocation, ...]
    by_display_name: Mapping[str, tuple[ResourceLocation, ...]]
    by_registry_id: Mapping[str, tuple[ResourceLocation, ...]]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls,
        entries: Sequence[ResourceLocation],
        skipped: Sequence[SkippedRow] = (),
    ) -> "JoinTable":
        """Return a table over `entries`, with both indexes computed."""
        return cls(
            entries=tuple(entries),
            by_display_name=group_by(entries, lambda entry: entry.display_name),
            by_registry_id=group_by(entries, lambda entry: entry.registry_id),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _indexes_must_match_the_entries(self) -> "JoinTable":
        """Refuse a table whose indexes are not the indexes of its entries."""
        by_name = group_by(self.entries, lambda entry: entry.display_name)
        if dict(self.by_display_name) != by_name:
            raise EnrichError("the display-name index does not match the entries of this table.")
        by_id = group_by(self.entries, lambda entry: entry.registry_id)
        if dict(self.by_registry_id) != by_id:
            raise EnrichError("the registry-ID index does not match the entries of this table.")
        return self

    def candidates(
        self, display_name: str, *, kind: str | None = None
    ) -> tuple[ResourceLocation, ...]:
        """Return every entry for `display_name`, narrowed by `kind` when given.

        The lookup is exact. Every name in this table and every name that the
        other buckets write come from the same wiki, so they agree on spelling
        and case; a fuzzy fallback here would hide a join that broke rather than
        report it, and search-time fuzziness is Phase 4's job, on the built
        index, not the pipeline's on the source data.
        """
        found = self.by_display_name.get(display_name, ())
        if kind is None:
            return found
        return tuple(entry for entry in found if entry.kind == kind)

    def resolve(self, display_name: str, *, kind: str | None = None) -> str:
        """Return the one registry ID of `display_name`, or raise `EnrichError`.

        Raises when the name is unknown, and raises when it names more than one
        distinct ID. Both are join failures a build should hear about: the first
        means a bucket wrote a name this table does not have, the second means
        the caller has to say which `kind` it wants, or that the pair is one of
        the genuinely ambiguous ones the module docstring lists.
        """
        found = self.candidates(display_name, kind=kind)
        described = display_name if kind is None else f"{display_name} ({kind})"
        if not found:
            raise EnrichError(f"{described!r} is not a display name of the join table.")
        ids = {entry.registry_id for entry in found}
        if len(ids) > 1:
            listed = ", ".join(sorted(ids))
            raise EnrichError(f"{described!r} names more than one registry ID: {listed}.")
        return found[0].registry_id

    def ambiguous_names(self) -> Mapping[str, tuple[str, ...]]:
        """Return every display name that maps to more than one registry ID.

        The report behind the count in the module docstring. A build prints it
        so that a new ambiguity -- a wiki rename, a new variant -- is visible
        the day it appears rather than the day a renderer shows the wrong item.
        """
        ambiguous: dict[str, tuple[str, ...]] = {}
        for name, group in self.by_display_name.items():
            ids = sorted({entry.registry_id for entry in group})
            if len(ids) > 1:
                ambiguous[name] = tuple(ids)
        return ambiguous


def parse_resource_locations(
    rows: Sequence[Mapping[str, Any]], *, source: str = BUCKET
) -> JoinTable:
    """Return the join table over `rows`, and a report of what was dropped.

    Pure: the rows go in as the API returned them and no network is touched.
    Five filters run, in this order, and each one records what it removed.

    1. Non-main-namespace rows, which are translations and sandboxes.
    2. Non-Java rows. The filter is here rather than only in the query so that
       one place decides it and a caller cannot get an unfiltered table by
       forgetting a `where` clause.
    3. Rows with no display name, which have nothing to be joined *from*.
    4. Rows whose display name is the wiki's `No displayed name` placeholder.
    5. Rows with no `resource_location`, which are removed and joke content.

    What survives is deduplicated on (display name, registry ID, kind). The raw
    table repeats a pair once per wiki page that mentions it -- `Stone` appears
    14 times -- and a duplicate entry would make every name look ambiguous. When
    a pair appears on several pages, the page named exactly after the display
    name wins, because that is the article the entity's own page will be; when
    none matches, the first page in alphabetical order wins, so the answer does
    not depend on the order the API happened to return.
    """
    kept, skipped = main_namespace(rows, source=source)
    # Keyed by the identity of an entry; the value collects every page that
    # wrote it, so the page choice below is made over all of them.
    pages: dict[tuple[str, str, str | None], set[str]] = {}
    order: list[tuple[str, str, str | None]] = []
    for row in kept:
        page = row_page_name(row, source=source)
        document = row_json(row, source=source)
        edition = optional_text(document, "Edition")
        display_name = optional_text(row, "display_name")
        if edition != JAVA_EDITION:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=display_name,
                    reason=f"the row is {edition or 'no'} edition, not {JAVA_EDITION}",
                )
            )
            continue
        if display_name is None:
            skipped.append(
                SkippedRow(page=page, subject=None, reason="the row has no display name")
            )
            continue
        if display_name == NO_DISPLAY_NAME:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=display_name,
                    reason="the wiki records no display name for this page",
                )
            )
            continue
        location = optional_text(row, "resource_location")
        if location is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=display_name,
                    reason="the row has no resource_location to join to",
                )
            )
            continue
        raw_kind = optional_text(document, "Type")
        kind = clean_text(raw_kind).lower() if raw_kind is not None else None
        identity = (display_name, location, kind)
        if identity not in pages:
            pages[identity] = set()
            order.append(identity)
        pages[identity].add(page)

    entries = []
    for display_name, location, kind in order:
        candidates = pages[(display_name, location, kind)]
        page = display_name if display_name in candidates else min(candidates)
        entries.append(
            ResourceLocation(
                display_name=display_name,
                resource_location=location,
                kind=kind,
                page=page,
                wiki_url=wiki_url(page),
            )
        )
    return JoinTable.build(entries, skipped)


def fetch_join_table(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> JoinTable:
    """Fetch the `resource_location` bucket and return the join table.

    `revision` names the cache generation, as `fetch_bucket_rows` requires: pass
    the Minecraft version for a build, or a date for a wiki-only refresh.

    The `where` clause is a bandwidth saving, not the edition filter. It halves
    what crosses the wire, and `parse_resource_locations` filters again on the
    rows that arrive, so a server that ignored the clause would still not put a
    Bedrock ID in the table.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        where=(("edition", JAVA_EDITION),),
        cache=cache,
        transport=transport,
    )
    return parse_resource_locations(rows)
