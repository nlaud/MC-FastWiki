"""Parse the wiki's `Breeding` page into per-mob breeding food requirements.

mcmeta does not carry breeding items: they live in mob Java code, not in a
datapack, so this is Tier B. The wiki's `Breeding` page carries one sortable
wikitable marked `data-description="Breeding foods"`.

## Java Edition only

Every Bedrock divergence is marked with edition templates.
This module reuses `pipeline.enrich.markup.scope_editions` rather than
writing a second edition filter: lines scoped to `Edition.BEDROCK` are
dropped, and lines scoped to Java or unmarked are kept.

## Timings

The `Breeding` page states both timings this module carries in prose rather
than in the table, so they are constants here rather than parsed cells:
"After breeding, the parents cannot be fed to breed again for five minutes"
gives `BREEDING_COOLDOWN_SECONDS`, and "Most baby mobs take 20 minutes to
grow up, while snifflets take 40 minutes" gives `DEFAULT_BABY_GROWTH_SECONDS`
and the `SLOW_GROWTH_MOBS` exception. They live here, keyed off the mob name
the table's own `EntityLink` yields, so no later stage has to guess which mob
is the slow one from its food list -- a guess that is wrong for any mob that
shares a food with the Sniffer, the Chicken included.

## Taming qualifier

The mob cell carries a `(Tamed)` qualifier for mobs that must be tamed
before they can breed (e.g. Wolf, Cat, Horse, Donkey, Llama, Trader Llama,
Nautilus). Taming items are not part of this table's items column and are
maintained in `/data/curated/taming.json` instead, ensuring breeding and
taming items never share a field.
"""

import re
from collections.abc import Mapping
from typing import Final

from pydantic import BaseModel

from pipeline.enrich import EnrichError, SkippedRow, clean_text
from pipeline.enrich.markup import (
    Edition,
    find_template,
    scope_editions,
    split_lines,
    split_template,
)
from pipeline.fetch import Transport
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.wikitext import fetch_page_wikitext

__all__ = [
    "BREEDING_COOLDOWN_SECONDS",
    "DEFAULT_BABY_GROWTH_SECONDS",
    "PAGE_TITLE",
    "SLOW_GROWTH_MOBS",
    "SLOW_GROWTH_SECONDS",
    "BreedingIndex",
    "MobBreeding",
    "fetch_breeding",
    "parse_breeding",
]

PAGE_TITLE: Final[str] = "Breeding"

# Both timings are stated in the page's prose, not in the `Breeding foods`
# table; see the module docstring for the sentences they come from.
BREEDING_COOLDOWN_SECONDS: Final[int] = 300
DEFAULT_BABY_GROWTH_SECONDS: Final[int] = 1200
SLOW_GROWTH_SECONDS: Final[int] = 2400
# Mob display names, as the table's own `EntityLink` writes them.
SLOW_GROWTH_MOBS: Final[frozenset[str]] = frozenset({"Sniffer"})

# The table description on the wikitable carrying breeding foods.
_TABLE_PATTERN = re.compile(
    r'\{\|[^\n]*data-description="Breeding foods"[^\n]*\n?(.*?)\n?\|\}',
    re.DOTALL | re.IGNORECASE,
)
_ROW_SPLIT = re.compile(r'\n\|-[^\n]*')
_CELL_SPLIT = re.compile(r'\n\|(?![}-])')
_TAMED_MARKER = re.compile(r'\(tamed\)', re.IGNORECASE)


class MobBreeding(BaseModel, frozen=True):
    """Breeding requirements for one mob."""

    mob: str
    items: tuple[str, ...]
    requires_taming: bool = False
    cooldown_seconds: int = BREEDING_COOLDOWN_SECONDS
    baby_growth_seconds: int = DEFAULT_BABY_GROWTH_SECONDS


class BreedingIndex(BaseModel, frozen=True):
    """Per-mob breeding lookup table, keyed by mob display name."""

    by_mob: Mapping[str, MobBreeding]
    skipped: tuple[SkippedRow, ...] = ()

    @property
    def mobs(self) -> tuple[MobBreeding, ...]:
        """Return all parsed MobBreeding rows."""
        return tuple(self.by_mob.values())


def parse_breeding(wikitext: str, *, source: str = PAGE_TITLE) -> BreedingIndex:
    """Parse the `Breeding foods` table into a `BreedingIndex`, or raise `EnrichError`."""
    match = _TABLE_PATTERN.search(wikitext)
    if match is None:
        raise EnrichError(
            f"{source} contains no 'Breeding foods' table. An absent table is a shape fault, "
            f"not a wiki with no breeding mobs."
        )

    table_body = match.group(1).strip()
    if not table_body:
        raise EnrichError(f"{source} has an empty 'Breeding foods' table.")

    rows = _ROW_SPLIT.split(table_body)

    by_mob: dict[str, MobBreeding] = {}
    skipped: list[SkippedRow] = []

    # Row 0 is the table header: !Mob !Items !Other
    for raw_row in rows[1:]:
        row_str = raw_row.strip()
        if not row_str or row_str.startswith("!"):
            continue

        cells = _CELL_SPLIT.split("\n" + row_str)
        cells = [c.strip() for c in cells if c.strip()]
        if len(cells) < 2:
            skipped.append(
                SkippedRow(
                    page=source,
                    subject=None,
                    reason="row has fewer than 2 cells (expected Mob and Items)",
                )
            )
            continue

        mob_cell = cells[0]
        items_cell = cells[1]

        # Parse mobs in mob_cell
        mob_entries: list[tuple[str, bool]] = []
        for line in split_lines(mob_cell):
            entity_templates = find_template(line, "EntityLink")
            for t in entity_templates:
                parsed = split_template(t.text)
                mob_name = (
                    parsed.positional[-1] if parsed.positional else parsed.named.get("link", "")
                )
                mob_name = clean_text(mob_name)
                is_tamed = bool(_TAMED_MARKER.search(line))
                if mob_name:
                    mob_entries.append((mob_name, is_tamed))

        if not mob_entries:
            skipped.append(
                SkippedRow(
                    page=source,
                    subject=None,
                    reason=f"row contains no mob EntityLink templates: {row_str!r}",
                )
            )
            continue

        # Parse items in items_cell with edition filtering
        item_lines = split_lines(items_cell)
        scopes = scope_editions(item_lines)
        row_items: list[str] = []
        for scope in scopes:
            if scope.edition is Edition.BEDROCK:
                continue
            templates = list(find_template(scope.line, "ItemLink")) + list(
                find_template(scope.line, "BlockLink")
            )
            for t in templates:
                parsed = split_template(t.text)
                item_name = (
                    parsed.positional[-1] if parsed.positional else parsed.named.get("link", "")
                )
                item_name = clean_text(item_name)
                if item_name and item_name not in row_items:
                    row_items.append(item_name)

        if not row_items:
            mobs_label = ", ".join(m[0] for m in mob_entries)
            skipped.append(
                SkippedRow(
                    page=source,
                    subject=mobs_label,
                    reason=f"row contains no Java breeding item templates: {row_str!r}",
                )
            )
            continue

        for mob_name, is_tamed in mob_entries:
            by_mob[mob_name] = MobBreeding(
                mob=mob_name,
                items=tuple(row_items),
                requires_taming=is_tamed,
                baby_growth_seconds=(
                    SLOW_GROWTH_SECONDS
                    if mob_name in SLOW_GROWTH_MOBS
                    else DEFAULT_BABY_GROWTH_SECONDS
                ),
            )

    return BreedingIndex(by_mob=by_mob, skipped=tuple(skipped))


def fetch_breeding(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> BreedingIndex:
    """Fetch the `Breeding` page's wikitext and return its `BreedingIndex`."""
    report = fetch_page_wikitext([PAGE_TITLE], revision=revision, cache=cache, transport=transport)
    contents = report.contents()
    text = contents.get(PAGE_TITLE)
    if text is None:
        raise EnrichError(
            f"the wiki answered no wikitext for {PAGE_TITLE!r}. An empty scrape is a failure "
            f"to report, not a wiki with no Breeding page."
        )
    return parse_breeding(text, source=PAGE_TITLE)
