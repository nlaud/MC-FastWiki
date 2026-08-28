"""Advancement titles, descriptions, and rewards, keyed by the Tier A internal ID.

Tier A owns the advancement tree: mcmeta's `data` branch has one file per
advancement, and the path of that file is the internal ID -- `advancement/story/
root.json` is `story/root`. What Tier A does not have is anything a human wrote.
The wiki has the display title (`Isn't It Iron Pick`), the plain-language
description of how to earn it, the flavour text the game shows, and the
experience reward. This module fetches those and keys them on `internal_id`, so
the join to the Tier A tree is a dictionary lookup rather than a name match.

**Only the `Advancement` page counts, and that is the whole trick to this
bucket.** 615 rows arrive; 126 of them are the live advancement list. The rest
are the same advancements written down again on other pages, and their
`internal_id` values collide exactly with the real ones:

* `Advancement/April Fools'` holds 99 rows for the joke snapshots, with roots
  the real game has never had -- `potato/`, `mines/`, `feats/`, `unlocks/` --
  and, worse, 30 more under `adventure/` that shadow real IDs.
* `Java Edition 1.12/Development versions`, `Java Edition 17w13a`, and a dozen
  other version pages hold historical snapshots. Five separate pages carry a
  `story/root`, and the ones from 2017 describe an advancement that has since
  been reworded; one of them says `Descriptions were not added yet.`
* 125 more rows sit in the `Minecraft Wiki:` namespace, which the shared
  namespace filter removes before any of this.

Read without the page filter, the last row to arrive wins, and which one that is
depends on the order the API returned them. The result would be a build that
sometimes shows a nine-year-old description and never says why. Filtered to the
one page, the 126 rows have no duplicate IDs at all, five roots, and every
`parent` resolving to a title on the same page.

**A parent is named by title, not by ID.** `story/mine_stone` says its parent is
`Minecraft`, not `story/root`. So the tree is built in two passes: titles first,
then parents resolved through them. `parent_id` is the resolved ID and
`parent_title` is what the wiki actually wrote, kept because a title that does
not resolve is a fact worth reporting rather than hiding.

**The reward is rendered HTML with the number buried in it.** The wiki writes an
experience reward as a sprite span followed by the digits and
`<span class="hidden-alt-text">XP</span>`. `experience` pulls the integer out of
that; `reward` keeps the original, because an advancement could one day reward
something that is not experience.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, model_validator

from pipeline.enrich import (
    EnrichError,
    SkippedRow,
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
    "ADVANCEMENT_PAGE",
    "BUCKET",
    "COLUMNS",
    "INTERNAL_ID",
    "AdvancementTree",
    "Reconciliation",
    "WikiAdvancement",
    "fetch_advancements",
    "parse_advancements",
]

BUCKET = "advancement"

COLUMNS = ("page_name", "title", "json")

# The one page whose rows describe the advancements of the current game. The
# module docstring holds what the other pages are and what reading them costs.
ADVANCEMENT_PAGE = "Advancement"

# An internal ID is a tab and a path under it, lowercase, as the data pack file
# path spells it: `story/root`, `adventure/kill_a_mob`, `husbandry/balanced_diet`.
INTERNAL_ID = re.compile(r"[a-z0-9_]+(?:/[a-z0-9_]+)+\Z")

# The experience reward, inside the wiki's rendered reward HTML. Anchored on the
# `hidden-alt-text` span that follows the digits, so it cannot match the sprite
# class name `xp-148` that sits earlier in the same string.
EXPERIENCE = re.compile(r"(\d+)\s*<span[^>]*hidden-alt-text[^>]*>\s*XP", re.IGNORECASE)


class WikiAdvancement(BaseModel, frozen=True):
    """One advancement, as the wiki describes it."""

    # The Tier A key: `story/mine_stone`. This is what the join uses.
    internal_id: str
    title: str
    # The wiki's plain description of how to earn it, as wikitext with links.
    # `None` on the handful of advancements the wiki has only written the game's
    # own flavour line for, such as `nether/find_bastion`, where the field holds
    # the em dash that means "nothing here yet". A renderer falls back to
    # `game_description`; treating the dash as text would print it as the
    # instructions.
    description: str | None
    # The flavour line the game itself shows under the title. Absent on some.
    game_description: str | None
    # What the wiki writes as the parent, which is a title. `parent_id` is that
    # title resolved through this page; `None` on a root, and `None` when the
    # title resolves to nothing, which the tree reports.
    parent_title: str | None
    parent_id: str | None
    # The item whose icon the wiki shows, as a display name: `Wooden Pickaxe`.
    icon: str | None
    # `plain`, `fancy`, or the background the wiki names for the tab.
    background: str | None
    # The experience reward, when the reward is experience, and the raw reward
    # field it was read out of.
    experience: int | None
    reward: str | None
    page: str
    wiki_url: str

    @property
    def tab(self) -> str:
        """Return the advancement tab: `story`, `nether`, `end`, and so on."""
        return self.internal_id.split("/", 1)[0]

    @property
    def is_root(self) -> bool:
        """Return whether this is the root of its tab."""
        return self.parent_title is None


class Reconciliation(BaseModel, frozen=True):
    """The result of joining this table to the Tier A advancement tree.

    Both halves are faults worth a build warning and they mean different things.
    `missing_from_wiki` is an advancement the game has and the wiki has not
    documented yet, which is normal in the days after a release and means the
    page renders with no description. `missing_from_tier_a` is the wiki
    describing an advancement the game does not have, which means either a wiki
    page written ahead of a release or -- the case worth catching -- the page
    filter in this module letting a snapshot row through.
    """

    matched: tuple[str, ...]
    missing_from_wiki: tuple[str, ...]
    missing_from_tier_a: tuple[str, ...]


class AdvancementTree(BaseModel, frozen=True):
    """Every advancement the wiki documents, keyed and linked by internal ID."""

    advancements: tuple[WikiAdvancement, ...]
    by_id: Mapping[str, WikiAdvancement]
    children: Mapping[str, tuple[str, ...]]
    roots: tuple[str, ...]
    skipped: tuple[SkippedRow, ...] = ()

    @classmethod
    def build(
        cls,
        advancements: Sequence[WikiAdvancement],
        skipped: Sequence[SkippedRow] = (),
    ) -> "AdvancementTree":
        """Return a tree over `advancements`, with the links computed."""
        children: dict[str, list[str]] = {}
        roots: list[str] = []
        for advancement in advancements:
            if advancement.parent_id is None:
                roots.append(advancement.internal_id)
            else:
                children.setdefault(advancement.parent_id, []).append(advancement.internal_id)
        return cls(
            advancements=tuple(advancements),
            by_id={advancement.internal_id: advancement for advancement in advancements},
            children={parent: tuple(ids) for parent, ids in children.items()},
            roots=tuple(roots),
            skipped=tuple(skipped),
        )

    @model_validator(mode="after")
    def _ids_must_be_unique_and_indexed(self) -> "AdvancementTree":
        """Refuse a tree with a duplicate ID or an index that is not its own.

        The duplicate check is the guard that makes the page filter load-bearing
        rather than advisory. Every way of reading this bucket wrongly ends in
        two rows sharing an internal ID, and that is exactly what this refuses.
        """
        if len(self.by_id) != len(self.advancements):
            counted: dict[str, int] = {}
            for advancement in self.advancements:
                counted[advancement.internal_id] = counted.get(advancement.internal_id, 0) + 1
            repeated = sorted(name for name, count in counted.items() if count > 1)
            raise EnrichError(f"these advancement IDs appear more than once: {repeated}.")
        expected = {advancement.internal_id: advancement for advancement in self.advancements}
        if dict(self.by_id) != expected:
            raise EnrichError("the ID index does not match the advancements of this tree.")
        return self

    def ancestry(self, internal_id: str) -> tuple[WikiAdvancement, ...]:
        """Return the chain from the root down to `internal_id`, inclusive.

        The parent chain a renderer shows above an advancement. Raises when the
        ID is unknown. The walk is bounded by the size of the tree, so a parent
        cycle -- which the wiki could write and nothing upstream forbids -- ends
        in an error rather than a hang.
        """
        chain: list[WikiAdvancement] = []
        seen: set[str] = set()
        current: str | None = internal_id
        while current is not None:
            if current in seen:
                raise EnrichError(f"the parent chain of {internal_id!r} is a cycle.")
            seen.add(current)
            advancement = self.by_id.get(current)
            if advancement is None:
                raise EnrichError(f"{current!r} is not an advancement of this tree.")
            chain.append(advancement)
            current = advancement.parent_id
        return tuple(reversed(chain))

    def reconcile(self, tier_a_ids: Iterable[str]) -> Reconciliation:
        """Join this table to the Tier A advancement IDs and report both gaps.

        `tier_a_ids` are the data-pack paths without the extension --
        `story/root` for `advancement/story/root.json` -- which is exactly the
        key this table is built on.
        """
        wiki = set(self.by_id)
        vanilla = set(tier_a_ids)
        return Reconciliation(
            matched=tuple(sorted(wiki & vanilla)),
            missing_from_wiki=tuple(sorted(vanilla - wiki)),
            missing_from_tier_a=tuple(sorted(wiki - vanilla)),
        )


def parse_experience(reward: str) -> int | None:
    """Return the experience an advancement rewards, or `None`.

    `None` means the reward is not experience, not that it is zero.
    """
    match = EXPERIENCE.search(reward)
    return int(match[1]) if match is not None else None


def parse_advancements(
    rows: Sequence[Mapping[str, Any]],
    *,
    page: str = ADVANCEMENT_PAGE,
    source: str = BUCKET,
) -> AdvancementTree:
    """Return the advancement tree of `rows`, and a report of what was dropped.

    Pure. Only rows on `page` are kept; the module docstring holds the reason,
    and the parameter exists so a caller can read the April Fools' page
    deliberately rather than by accident.

    Two passes: the first reads every row and collects titles, the second
    resolves each `parent` title to an internal ID. A parent that resolves to
    nothing leaves `parent_id` empty and adds a report line -- it is a broken
    link on the wiki, which should be visible, not a reason to drop a real
    advancement.
    """
    kept, skipped = main_namespace(rows, source=source)
    on_page: list[Mapping[str, Any]] = []
    for row in kept:
        row_page = row_page_name(row, source=source)
        if row_page == page:
            on_page.append(row)
        else:
            skipped.append(
                SkippedRow(
                    page=row_page,
                    subject=optional_text(row, "title"),
                    reason=f"the row is not on {page}, so it is a snapshot or a joke variant",
                )
            )

    parsed: list[tuple[dict[str, Any], str, str]] = []
    titles: dict[str, str] = {}
    for row in on_page:
        document = row_json(row, source=source)
        internal_id = optional_text(document, "internal_id")
        title = optional_text(document, "title")
        if internal_id is None or title is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=title or internal_id,
                    reason="the row has no internal_id or no title",
                )
            )
            continue
        if INTERNAL_ID.fullmatch(internal_id) is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=title,
                    reason=f"{internal_id!r} is not an advancement internal ID",
                )
            )
            continue
        parsed.append((document, internal_id, title))
        titles[title] = internal_id

    advancements: list[WikiAdvancement] = []
    for document, internal_id, title in parsed:
        parent_title = optional_text(document, "parent")
        parent_id = titles.get(parent_title) if parent_title is not None else None
        if parent_title is not None and parent_id is None:
            skipped.append(
                SkippedRow(
                    page=page,
                    subject=title,
                    reason=f"its parent {parent_title!r} is not an advancement on this page",
                )
            )
        reward = optional_text(document, "reward")
        advancements.append(
            WikiAdvancement(
                internal_id=internal_id,
                title=title,
                description=optional_text(document, "wiki_description"),
                game_description=optional_text(document, "game_description"),
                parent_title=parent_title,
                parent_id=parent_id,
                icon=optional_text(document, "image"),
                background=optional_text(document, "background"),
                experience=parse_experience(reward) if reward is not None else None,
                reward=reward,
                page=page,
                wiki_url=wiki_url(page),
            )
        )
    return AdvancementTree.build(advancements, skipped)


def fetch_advancements(
    *,
    revision: str,
    page: str = ADVANCEMENT_PAGE,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> AdvancementTree:
    """Fetch the `advancement` bucket and return the tree the wiki documents.

    The `where` clause narrows to the one page that matters, which is 126 rows
    of 615. `parse_advancements` filters again on what arrives, so the clause is
    a saving rather than the filter of record.
    """
    rows = fetch_bucket_rows(
        BUCKET,
        COLUMNS,
        revision=revision,
        where=(("page_name", page),),
        cache=cache,
        transport=transport,
    )
    return parse_advancements(rows, page=page)
