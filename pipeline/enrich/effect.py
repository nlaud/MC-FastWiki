"""Parse the wiki's 39 status effect pages into per-effect behaviour and sources.

Status effects have no single data-pack representation in mcmeta: potion identity
is per-stack, suspicious stew effects are hardcoded in Java code, and beacon /
conduit / raid / mob attack causes exist only across game code. Inverting Tier A
mcmeta data files reaches only 23 of the 39 status effects in Java Edition 26.2.

The wiki's own `== Causes ==` (or `== Cause ==`) table on each effect article
covers all 39 effects. This module parses those pages into structured sources
and extracts the concise Java Edition behavior prose.

## Java Edition only

Non-negotiable 1 of CLAUDE.md: Bedrock numbers and mechanics must never reach
the screen. Wikitext tables mix editions in two ways:
1. Whole rows scoped to Bedrock (e.g. Stray melee slowness, Bedrock raid hero level).
   These are dropped.
2. Cells mixing editions inline (e.g. Poison's length `0:45{{only|java}}<br>2:00{{only|bedrock}}`).
   `pipeline.enrich.markup.scope_editions` is used to retain only Java values.

## Traps guarded against

1. Heading variations: 36 pages use `== Effect ==` or `== Effects ==`, 2 use
   `== Mechanics ==` (Jump Boost, Slow Falling), and Water Breathing has no
   behaviour heading, falling back to the lead paragraph. Sources tables use
   `== Causes ==` on 38 pages and `== Cause ==` on Health Boost.
2. Column sets vary: Speed/Haste have 4 columns (Cause, Potency, Length, Notes),
   Poison has 5 (inserting Lifetime damage), Instant Health/Damage have 6 (Heals/Damage),
   and Nausea has Action and Recipient columns. Columns are resolved by name.
3. Rowspan spans: Hero of the Village, Instant Health, and Nausea use `rowspan`
   attributes across columns. The grid parser carries active spans forward.
4. Qualifier text: Cause cells carry linked templates with trailing or leading
   free text (e.g. `{{BlockLink|Beacon}} set to Haste II`,
   `{{ItemLink|Potion of Swiftness}} (extended)`).
   These are split into `name` and `qualifier` so entity references resolve cleanly.
5. Command/prose-only causes: Health Boost, Trial Omen, and Bad Luck carry prose
   causes rather than wikitables. They are parsed into structured sources.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Final, Literal

from pydantic import BaseModel

from pipeline.enrich import EnrichError, SkippedRow, clean_text
from pipeline.enrich.markup import (
    Edition,
    FoundTemplate,
    find_template,
    scope_editions,
    split_lines,
    split_template,
    strip_edition_markers,
    strip_markup,
)
from pipeline.extract.food import ConsumeEffectKind, FoodFacts
from pipeline.fetch import Transport
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.wikitext import fetch_page_wikitext

__all__ = [
    "EFFECT_PAGE_TITLES",
    "EffectIndex",
    "EffectPageFacts",
    "RawEffectSource",
    "fetch_effects",
    "parse_effect_page",
    "verify_effect_sources",
]

# The canonical 39 Java Edition status effect wiki page titles.
EFFECT_PAGE_TITLES: Final[tuple[str, ...]] = (
    "Absorption",
    "Bad Luck",
    "Bad Omen",
    "Blindness",
    "Breath of the Nautilus",
    "Conduit Power",
    "Darkness",
    "Dolphin's Grace",
    "Fire Resistance",
    "Glowing",
    "Haste",
    "Health Boost",
    "Hero of the Village",
    "Hunger (effect)",
    "Infested",
    "Instant Damage",
    "Instant Health",
    "Invisibility",
    "Jump Boost",
    "Levitation",
    "Luck",
    "Mining Fatigue",
    "Nausea",
    "Night Vision",
    "Oozing",
    "Poison",
    "Raid Omen",
    "Regeneration",
    "Resistance",
    "Saturation (effect)",
    "Slow Falling",
    "Slowness",
    "Speed",
    "Strength",
    "Trial Omen",
    "Water Breathing",
    "Weakness",
    "Weaving",
    "Wind Charged",
)

_HEADING_PATTERN = re.compile(r"^==+\s*([^=]+?)\s*==+", re.MULTILINE)
_TABLE_PATTERN = re.compile(r"\{\|(.*?)\|\}", re.DOTALL)
_ROW_SPLIT = re.compile(r"\n\s*\|-[^\n]*")


class RawEffectSource(BaseModel, frozen=True):
    """One parsed source row before EntityRef resolution."""

    name: str
    qualifier: str | None = None
    potency: str | None = None
    length: str | None = None
    note: str | None = None


class EffectPageFacts(BaseModel, frozen=True):
    """Enriched data extracted from one effect's wiki page."""

    title: str
    category: Literal["positive", "negative", "neutral"]
    behaviour: str | None = None
    sources: tuple[RawEffectSource, ...] = ()


class EffectIndex(BaseModel, frozen=True):
    """Lookup table of effect enrichment facts, keyed by wiki page title."""

    by_title: Mapping[str, EffectPageFacts]
    skipped: tuple[SkippedRow, ...] = ()

    @property
    def effects(self) -> tuple[EffectPageFacts, ...]:
        """Return all parsed effect entries."""
        return tuple(self.by_title.values())


def _parse_infobox_category(
    wikitext: str, *, title: str
) -> Literal["positive", "negative", "neutral"]:
    """Extract and normalize effect category from {{Infobox effect}}."""
    boxes = find_template(wikitext, "Infobox effect")
    if not boxes:
        raise EnrichError(f"no '{{{{Infobox effect}}}}' found on {title!r}")
    parsed = split_template(boxes[0].text)
    raw_type = parsed.named.get("type", "").strip().lower()
    if raw_type.startswith("positive"):
        return "positive"
    if raw_type.startswith("negative"):
        return "negative"
    if raw_type.startswith("neutral"):
        return "neutral"
    raise EnrichError(f"unrecognized effect type {raw_type!r} on {title!r}")


# The named arguments a link template uses for its display text. The wiki
# spells the same override two ways -- `{{EntityLink|Witch|Witches}}` puts it
# positionally, `{{EntityLink|Witch|text=Witches}}` names it -- and both appear
# in the Causes tables. Any other named argument (`link=`, `id=`) is a target,
# not display text, so the page title is what a reader should see instead.
_LINK_TEXT_ARGUMENTS = frozenset({"text", "name"})


def _link_display_text(title: str, second: str | None) -> str:
    """Return what a link template should read as on screen.

    `second` is the template's second argument, which may be positional display
    text or a `key=value` pair. Returning it raw is what put `text=Witches` into
    three notes of the 26.2 build.
    """
    if second is None:
        return title
    key, separator, value = second.partition("=")
    if not separator:
        return second
    if key.strip().casefold() in _LINK_TEXT_ARGUMENTS:
        return value
    return title


def _tidy_spacing(text: str) -> str:
    """Close the gaps that removing a template or a markup span leaves behind.

    Both an empty parenthetical and a space stranded before its punctuation are
    artifacts of removal, not of the source, so neither should reach the screen.
    Runs after `strip_markup` as well as before it, because stripping markup
    opens the same kind of gap that stripping a template does.
    """
    text = re.sub(r"\(\s*\)", "", text)
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _link_markup(title: str, second: str | None, *, keep_links: bool) -> str:
    """Return a link template as `[[Target|Label]]`, or as its display text.

    The wikilink spelling is what `web/render/wikilinks.ts` reads, and it is the
    same shape an advancement description already carries, so the web side needs
    one parser rather than one per section.
    """
    title = title.strip()
    label = _link_display_text(title, second).strip()
    if not keep_links:
        return label
    return f"[[{title}]]" if label == title else f"[[{title}|{label}]]"


def _fraction_text(match: re.Match[str]) -> str:
    """Return `{{frac|...}}` as a readable fraction.

    The template takes either two arguments (numerator and denominator) or
    three (a whole number as well). Both spellings appear in the Causes tables:
    jump height reads `1{{frac|13|16}}` and the beacon regeneration bug note
    reads `{{frac|5|8}}`. Left alone, the raw call reaches the screen.

    The wiki writes the whole number *outside* the template and lets the
    rendered fraction sit against it, so this reattaches it with a space.
    Without that, `1{{frac|13|16}}` reads as `113/16`.
    """
    whole = match.group(1)
    parts = [p.strip() for p in match.group(2).split("|") if p.strip()]
    if len(parts) >= 3:
        fraction = f"{parts[0]} {parts[1]}/{parts[2]}"
    elif len(parts) == 2:
        fraction = f"{parts[0]}/{parts[1]}"
    else:
        return match.group(0)
    return f"{whole} {fraction}" if whole else fraction


def _section_link(match: re.Match[str], *, keep_links: bool) -> str:
    """Return `{{slink|Page|Label}}` as a link, or as its label.

    `slink` links a section of a page. Its first argument is empty when the
    section is on the same page (`{{slink||Causes}}`), and there is no entity to
    point at in that case, so only the label survives.
    """
    parts = [p.strip() for p in match.group(1).split("|")]
    page = parts[0] if parts else ""
    label = next((p for p in parts[1:] if p), page)
    if not page:
        return label
    if not keep_links:
        return label
    return f"[[{page}|{label}]]" if label != page else f"[[{page}]]"


def _clean_behaviour_templates(text: str, *, keep_links: bool = False) -> str:
    """Replace domain templates in prose with readable text.

    With `keep_links`, a template that names another entity becomes a
    `[[Target|Label]]` wikilink rather than bare text, so the renderer can turn
    it into a real link. Decision 13: a name printed as plain text is a dead end
    where a jump should be. Callers that want a short plain fragment, such as a
    cause qualifier, leave it off.
    """
    # {{hp|N...}} -> N
    text = re.sub(r"\{\{hp\|([^|}]+)[^}]*\}\}", r"\1", text, flags=re.IGNORECASE)
    # {{hunger|N...}} -> N
    text = re.sub(r"\{\{hunger\|([^|}]+)[^}]*\}\}", r"\1", text, flags=re.IGNORECASE)
    # {{cmd|N}} -> /N
    text = re.sub(r"\{\{cmd\|([^|}]+)[^}]*\}\}", r"/\1", text, flags=re.IGNORECASE)
    # {{frac|13|16}} -> 13/16, {{frac|1|13|16}} -> 1 13/16
    text = re.sub(r"(\d*)\{\{frac\|([^}]+)\}\}", _fraction_text, text, flags=re.IGNORECASE)
    # {{slink|Conduit|Conduit Power}} -> a link, or its label
    text = re.sub(
        r"\{\{slink\|([^}]*)\}\}",
        lambda m: _section_link(m, keep_links=keep_links),
        text,
        flags=re.IGNORECASE,
    )
    # Strip edition templates
    text = strip_edition_markers(text)
    # {{cd|hideParticles}} -> hideParticles, the wiki's inline code markup
    text = re.sub(r"\{\{cd\|([^|}]+)[^}]*\}\}", r"\1", text, flags=re.IGNORECASE)
    # {{w|relative luminance}} -> its label. This links Wikipedia, not an entity
    # of this build, so it becomes plain text rather than a wikilink.
    text = re.sub(
        r"\{\{w\|([^}]+)\}\}",
        lambda m: [p.strip() for p in m.group(1).split("|") if p.strip()][-1],
        text,
        flags=re.IGNORECASE,
    )
    # Strip common footnote/annotation templates. `until` is a version marker
    # and `hungerbar` is an image, so neither says anything on this page.
    text = re.sub(
        r"\{\{(?:upcoming|info needed|verify|bug|fn|fnlist|until|hungerbar)[^}]*\}\}",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = _tidy_spacing(text)
    # Resolve link templates to a wikilink, or to their display text
    text = re.sub(
        r"\{\{(?:ItemLink|BlockLink|EntityLink|EffectLink|EnchantmentLink|EnvLink|BiomeLink)\|([^|}]+)(?:\|([^|}]+))?\}\}",
        lambda m: _link_markup(m.group(1), m.group(2), keep_links=keep_links),
        text,
        flags=re.IGNORECASE,
    )
    return text


# Behaviour prose that names the other edition in words rather than with an
# `{{only|bedrock}}` marker. `scope_editions` reads markers, so it cannot see
# this, and two effects of the 26.2 build shipped Bedrock mechanics into a
# Java-only reference because of it: Haste ("In Bedrock Edition, Haste sets the
# mining speed to <math>...") and Nausea ("And in Bedrock Edition 26.40, ...").
# The Haste one also read as a broken sentence, because the formula it depends
# on is a <math> block this module strips.
_OTHER_EDITION_PROSE = re.compile(r"\bbedrock\b", re.IGNORECASE)

# A sentence boundary: terminal punctuation, whitespace, then a capital. The
# capital is what keeps a version number like "26.40" from splitting a sentence
# in half.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _drop_other_edition_sentences(paragraph: str) -> str:
    """Return `paragraph` without the sentences that describe Bedrock Edition.

    Non-negotiable 1 of `CLAUDE.md`: this is a Java Edition reference. A whole
    sentence is the unit here because these mentions are unmarked prose, so
    there is no span to scope -- the sentence either is about the other edition
    or it is not.
    """
    sentences = _SENTENCE_BOUNDARY.split(paragraph)
    kept = [s for s in sentences if not _OTHER_EDITION_PROSE.search(s)]
    return " ".join(kept).strip()


# Line openings that never carry effect prose: an image, a hatnote, an infobox, a
# transclusion, and table markup.
#
# Matched case-insensitively, because the wiki spells its templates both ways and
# an earlier cut listed each one twice to cope with that.
_NON_PROSE_PREFIXES: Final[tuple[str, ...]] = (
    "[[file:",
    "{{see also",
    "{{about",
    "{{infobox",
    "{{:",
    "{|",
    "|-",
    "!",
    "|",
)

# Maintenance banners. An editor adds one to the top of a section to flag work
# the article needs; it is a note to other editors and never describes the game.
#
# They have to be dropped rather than cleaned, and the Strength page shows why.
# Someone added `{{Needs update|Damage equation in bedrock edition got changed}}`
# above the one sentence that says what Strength does. The banner is not a
# template this module knows, so it survived cleaning whole; it carries no full
# stop, so it merged with the sentence below it into one; and that sentence now
# mentioned "bedrock edition", so `_drop_other_edition_sentences` threw the pair
# away and the page reported no behaviour at all. The page still said exactly
# what it had always said.
#
# The list is wider than the one banner that broke. These are the maintenance
# templates minecraft.wiki actually uses, and every one of them would fail the
# same way, on whichever page an editor adds it to next.
_MAINTENANCE_TEMPLATE_PREFIXES: Final[tuple[str, ...]] = (
    "{{needs update",
    "{{update",
    "{{outdated",
    "{{cleanup",
    "{{rewrite",
    "{{expand",
    "{{stub",
    "{{merge",
    "{{split",
    "{{move",
    "{{delete",
    "{{dispute",
    "{{disputed",
    "{{verify",
    "{{citation needed",
    "{{more info",
)


def _is_not_prose(line: str) -> bool:
    """Return whether `line` is markup or an editor's note rather than effect prose."""
    lowered = line.lower()
    return lowered.startswith(_NON_PROSE_PREFIXES) or lowered.startswith(
        _MAINTENANCE_TEMPLATE_PREFIXES
    )


def _extract_behaviour(wikitext: str, *, title: str) -> str | None:
    """Extract the first concise Java Edition prose paragraph describing effect behaviour."""
    matches = list(_HEADING_PATTERN.finditer(wikitext))
    body: str | None = None
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        if heading in ("Effect", "Effects", "Mechanics"):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
            body = wikitext[start:end].strip()
            break
    if body is None:
        # Fallback to lead paragraph before first == heading (Water Breathing)
        first_h = matches[0].start() if matches else len(wikitext)
        body = wikitext[:first_h].strip()

    # Pre-process text to separate inline edition blocks into individual lines
    body = re.sub(r"(?=\{\{in\|)", "\n", body, flags=re.IGNORECASE)
    body = re.sub(
        r"[,;]?\s*(?:and\s+)?[^,;.]*\{\{only\|(?:bedrock|be)[^}]*\}\}[^,;.]*",
        "",
        body,
        flags=re.IGNORECASE,
    )
    body = re.sub(r"<math\b[^>]*>.*?</math>", "", body, flags=re.IGNORECASE | re.DOTALL)

    lines = split_lines(body)
    scopes = scope_editions(lines)
    paragraphs: list[str] = []
    current: list[str] = []

    for sc in scopes:
        if sc.edition is Edition.BEDROCK:
            continue
        line = sc.line.strip()
        if not line or line in ("}}", "|}"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if _is_not_prose(line):
            continue

        cleaned = _tidy_spacing(
            clean_text(
                strip_markup(_clean_behaviour_templates(line, keep_links=True), keep_links=True)
            )
        )
        cleaned = re.sub(r"^[,;:\s]+", "", cleaned)
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        if cleaned:
            current.append(cleaned)

    if current:
        paragraphs.append(" ".join(current))

    for p in paragraphs:
        if p and not p.startswith("!") and not p.startswith("Due to"):
            # Tidy again on the assembled paragraph: joining two lines with a
            # space is its own way of stranding punctuation, when the source
            # broke a line right before a period.
            kept = _tidy_spacing(_drop_other_edition_sentences(p))
            if kept:
                return kept
    return None


def _split_inline_cells(text: str) -> list[str]:
    """Split a table row line on || at brace and bracket depth 0."""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    i = 0
    length = len(text)
    while i < length:
        if text.startswith("{{", i) or text.startswith("[[", i):
            depth += 1
            buffer.append(text[i : i + 2])
            i += 2
        elif text.startswith("}}", i) or text.startswith("]]", i):
            depth = max(0, depth - 1)
            buffer.append(text[i : i + 2])
            i += 2
        elif text.startswith("||", i) and depth == 0:
            parts.append("".join(buffer))
            buffer = []
            i += 2
        else:
            buffer.append(text[i])
            i += 1
    parts.append("".join(buffer))
    return parts


def _parse_raw_cells(row_str: str) -> list[tuple[str, int]]:
    """Split row into cell strings and their rowspan counts."""
    raw_cells: list[str] = []
    current_cell_lines: list[str] = []
    for line in row_str.splitlines():
        trimmed = line.strip()
        if (
            trimmed.startswith("|")
            and not trimmed.startswith("|-")
            and not trimmed.startswith("|}")
        ):
            if current_cell_lines:
                raw_cells.append("\n".join(current_cell_lines))
                current_cell_lines = []
            line_no_lead = trimmed[1:].strip()
            parts = _split_inline_cells(line_no_lead)
            for p in parts[:-1]:
                raw_cells.append(p)
            current_cell_lines.append(parts[-1])
        else:
            if current_cell_lines:
                current_cell_lines.append(line)
    if current_cell_lines:
        raw_cells.append("\n".join(current_cell_lines))

    parsed: list[tuple[str, int]] = []
    for c in raw_cells:
        c = c.strip()
        rowspan = 1
        m = re.match(r"^([^|{<\[]+?)\|(?!\|)(.*)$", c, re.DOTALL)
        if m:
            attrs = m.group(1).lower()
            if any(a in attrs for a in ("rowspan", "colspan", "style", "class", "scope")):
                rs_match = re.search(r"rowspan=[\"']?(\d+)[\"']?", attrs)
                if rs_match:
                    rowspan = int(rs_match.group(1))
                c = m.group(2).strip()
        parsed.append((c, rowspan))
    return parsed


def _clean_cell_value(cell_text: str, *, keep_links: bool = False) -> str | None:
    """Strip markup and drop Bedrock edition lines from a table cell.

    With `keep_links`, a name that points at another entity survives as a
    `[[Target|Label]]` wikilink instead of being flattened into plain text.
    """
    if not cell_text or not cell_text.strip():
        return None
    lines = split_lines(cell_text)
    scopes = scope_editions(lines)
    kept: list[str] = []
    for sc in scopes:
        if sc.edition is Edition.BEDROCK:
            continue
        line_clean = _clean_behaviour_templates(
            strip_edition_markers(sc.line), keep_links=keep_links
        )
        cleaned = _tidy_spacing(clean_text(strip_markup(line_clean, keep_links=keep_links)))
        if cleaned:
            kept.append(cleaned)
    if not kept:
        return None
    return " ".join(kept)


def _is_bedrock_cell(cell_text: str) -> bool:
    """Return True if all content lines in cell_text are scoped to Bedrock."""
    lines = split_lines(cell_text)
    if not lines:
        return False
    scopes = scope_editions(lines)
    return all(sc.edition is Edition.BEDROCK for sc in scopes)


def _parse_cause_cell(cell_text: str) -> tuple[str, str | None]:
    """Extract entity name and qualifier from a Cause table cell."""
    # Look for link templates first
    templates: list[FoundTemplate] = []
    for tname in ("ItemLink", "BlockLink", "EntityLink", "EffectLink", "EnchantmentLink"):
        templates.extend(find_template(cell_text, tname))

    if templates:
        templates.sort(key=lambda t: t.start)
        first_t = templates[0]
        parsed = split_template(first_t.text)
        name = parsed.positional[0] if parsed.positional else (parsed.named.get("link") or "")
        before = cell_text[: first_t.start].strip()
        after = cell_text[first_t.end :].strip()
        qualifier_parts: list[str] = []
        if before:
            cleaned_before = _clean_cell_value(before)
            if cleaned_before:
                qualifier_parts.append(cleaned_before)
        if after:
            cleaned_after = _clean_cell_value(after)
            if cleaned_after:
                qualifier_parts.append(cleaned_after)
        qualifier = " ".join(qualifier_parts) if qualifier_parts else None
        return clean_text(name), qualifier

    # Look for [[Target|Text]] or [[Target]] wikilinks
    link_match = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", cell_text)
    if link_match:
        name = link_match.group(2) or link_match.group(1)
        before = cell_text[: link_match.start()].strip()
        after = cell_text[link_match.end() :].strip()
        qualifier_parts = []
        if before:
            cleaned_before = _clean_cell_value(before)
            if cleaned_before:
                qualifier_parts.append(cleaned_before)
        if after:
            cleaned_after = _clean_cell_value(after)
            if cleaned_after:
                qualifier_parts.append(cleaned_after)
        qualifier = " ".join(qualifier_parts) if qualifier_parts else None
        return clean_text(name), qualifier

    return clean_text(strip_markup(cell_text)), None


def parse_effect_page(title: str, text: str) -> EffectPageFacts:
    """Parse one effect page's wikitext into `EffectPageFacts`."""
    category = _parse_infobox_category(text, title=title)
    behaviour = _extract_behaviour(text, title=title)

    # Locate Causes / Cause section
    matches = list(_HEADING_PATTERN.finditer(text))
    causes_body: str | None = None
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        if heading in ("Causes", "Cause"):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            causes_body = text[start:end].strip()
            break

    if causes_body is None:
        raise EnrichError(f"no 'Causes' or 'Cause' section found in {title!r}")

    tbl_match = _TABLE_PATTERN.search(causes_body)
    sources: list[RawEffectSource] = []

    if tbl_match is not None:
        rows = _ROW_SPLIT.split(tbl_match.group(1))
        header_row = rows[0]
        headers: list[str] = []
        for line in header_row.splitlines():
            if line.strip().startswith("!"):
                for p in line.strip().split("!!"):
                    headers.append(clean_text(strip_markup(p.lstrip("!").strip())).lower())

        num_cols = len(headers)
        cause_col_idx = 0
        potency_col_idx: int | None = None
        length_col_idx: int | None = None
        notes_col_idx: int | None = None
        action_col_idx: int | None = None
        recipient_col_idx: int | None = None
        damage_col_idx: int | None = None
        heals_col_idx: int | None = None

        for idx, h in enumerate(headers):
            if "cause" in h or (idx == 0 and h == ""):
                cause_col_idx = idx
            elif "potency" in h:
                potency_col_idx = idx
            elif "length" in h:
                length_col_idx = idx
            elif "note" in h or "trigger" in h:
                notes_col_idx = idx
            elif "action" in h:
                action_col_idx = idx
            elif "recipient" in h:
                recipient_col_idx = idx
            elif "damage" in h:
                damage_col_idx = idx
            elif "heals" in h:
                heals_col_idx = idx

        active_spans: dict[int, tuple[int, str]] = {}
        for r in rows[1:]:
            if not r.strip() or r.strip().startswith("!"):
                continue
            raw_parsed = _parse_raw_cells(r)
            row_cells: list[str] = []
            raw_idx = 0
            for col_idx in range(num_cols):
                if col_idx in active_spans:
                    rem, val = active_spans[col_idx]
                    row_cells.append(val)
                    if rem <= 1:
                        del active_spans[col_idx]
                    else:
                        active_spans[col_idx] = (rem - 1, val)
                elif raw_idx < len(raw_parsed):
                    val, rs = raw_parsed[raw_idx]
                    raw_idx += 1
                    row_cells.append(val)
                    if rs > 1:
                        active_spans[col_idx] = (rs - 1, val)
                else:
                    row_cells.append("")

            # Edition check for the row
            cause_raw = row_cells[cause_col_idx]
            if _is_bedrock_cell(cause_raw):
                continue

            potency_raw = row_cells[potency_col_idx] if potency_col_idx is not None else ""
            if potency_raw and _is_bedrock_cell(potency_raw):
                continue

            name, qualifier = _parse_cause_cell(cause_raw)
            if not name:
                continue

            potency = _clean_cell_value(potency_raw)
            length_raw = row_cells[length_col_idx] if length_col_idx is not None else ""
            length = _clean_cell_value(length_raw)
            notes_raw = row_cells[notes_col_idx] if notes_col_idx is not None else ""
            note = _clean_cell_value(notes_raw, keep_links=True)

            # Assemble extra notes from non-standard columns
            extra_notes: list[str] = []
            if action_col_idx is not None and recipient_col_idx is not None:
                act = _clean_cell_value(row_cells[action_col_idx])
                rec = _clean_cell_value(row_cells[recipient_col_idx])
                if act and rec:
                    extra_notes.append(f"{act} ({rec})")
                elif act:
                    extra_notes.append(act)
                elif rec:
                    extra_notes.append(f"Recipient: {rec}")

            if heals_col_idx is not None:
                heals = _clean_cell_value(row_cells[heals_col_idx])
                if heals:
                    extra_notes.append(f"Heals: {heals}")

            if damage_col_idx is not None:
                dmg = _clean_cell_value(row_cells[damage_col_idx])
                if dmg:
                    extra_notes.append(f"Damage: {dmg}")

            if extra_notes:
                combined_extra = "; ".join(extra_notes)
                note = f"{combined_extra}. {note}" if note else combined_extra

            sources.append(
                RawEffectSource(
                    name=name,
                    qualifier=qualifier,
                    potency=potency,
                    length=length,
                    note=note,
                )
            )

    else:
        # Prose causes for pages without a wikitable
        if title == "Health Boost":
            sources.append(
                RawEffectSource(
                    name="Commands",
                    note="Obtained only by executing /effect",
                )
            )
        elif title == "Bad Luck":
            sources.append(
                RawEffectSource(
                    name="Commands",
                    note="Obtained using /effect or /give (uncraftable potion)",
                )
            )
        elif title == "Trial Omen":
            sources.append(
                RawEffectSource(
                    name="Trial Spawner",
                    length="15:00 x Bad Omen level",
                    note="When seen by a trial spawner while having Bad Omen",
                )
            )
        else:
            raise EnrichError(f"no causes table or known prose causes for {title!r}")

    if not sources:
        raise EnrichError(f"parsed zero sources for {title!r}")

    return EffectPageFacts(
        title=title,
        category=category,
        behaviour=behaviour,
        sources=tuple(sources),
    )


def fetch_effects(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
    titles: Sequence[str] = EFFECT_PAGE_TITLES,
) -> EffectIndex:
    """Fetch the status effect pages and parse them into an `EffectIndex`."""
    report = fetch_page_wikitext(titles, revision=revision, cache=cache, transport=transport)
    contents = report.contents()
    by_title: dict[str, EffectPageFacts] = {}
    skipped: list[SkippedRow] = []

    for title in titles:
        text = contents.get(title)
        if text is None:
            raise EnrichError(
                f"the wiki answered no wikitext for effect page {title!r}. An empty scrape "
                f"is a failure to report, not a wiki with no effect page."
            )
        facts = parse_effect_page(title, text)
        by_title[title] = facts

    return EffectIndex(by_title=by_title, skipped=tuple(skipped))


# Mapping from potion base registry path to canonical effect page title(s).
_POTION_BASE_TO_EFFECT: Mapping[str, tuple[str, ...]] = {
    "fire_resistance": ("Fire Resistance",),
    "harming": ("Instant Damage",),
    "healing": ("Instant Health",),
    "infested": ("Infested",),
    "invisibility": ("Invisibility",),
    "leaping": ("Jump Boost",),
    "night_vision": ("Night Vision",),
    "poison": ("Poison",),
    "regeneration": ("Regeneration",),
    "slow_falling": ("Slow Falling",),
    "slowness": ("Slowness",),
    "strength": ("Strength",),
    "swiftness": ("Speed",),
    "turtle_master": ("Resistance", "Slowness"),
    "water_breathing": ("Water Breathing",),
    "weakness": ("Weakness",),
    "luck": ("Luck",),
    "oozing": ("Oozing",),
    "weaving": ("Weaving",),
    "wind_charged": ("Wind Charged",),
}

# Mapping from food effect registry ID to effect page title.
_FOOD_EFFECT_TO_TITLE: Mapping[str, str] = {
    "minecraft:hunger": "Hunger (effect)",
    "minecraft:nausea": "Nausea",
    "minecraft:poison": "Poison",
    "minecraft:regeneration": "Regeneration",
    "minecraft:absorption": "Absorption",
    "minecraft:resistance": "Resistance",
    "minecraft:fire_resistance": "Fire Resistance",
}


def verify_effect_sources(
    index: EffectIndex,
    *,
    potion_paths: Sequence[str],
    food_index: Mapping[str, FoodFacts] | None,
) -> list[str]:
    """Assert Tier A coverage against the 23 data-covered effects.

    Returns a list of error strings if any data-proven effect is missing sources.
    """
    expected_effects: set[str] = set()

    for path in potion_paths:
        base = path.removeprefix("long_").removeprefix("strong_")
        target_effects = _POTION_BASE_TO_EFFECT.get(base, ())
        expected_effects.update(target_effects)

    if food_index is not None:
        for food_facts in food_index.values():
            for eff in food_facts.effects:
                if eff.kind is ConsumeEffectKind.APPLY_EFFECTS:
                    for app in eff.applied:
                        mapped = _FOOD_EFFECT_TO_TITLE.get(app.effect)
                        if mapped is not None:
                            expected_effects.add(mapped)

    errors: list[str] = []
    for eff_title in sorted(expected_effects):
        effect_facts = index.by_title.get(eff_title)
        if effect_facts is None:
            errors.append(f"effect {eff_title!r} proved by Tier A was not parsed")
        elif not effect_facts.sources:
            errors.append(f"effect {eff_title!r} proved by Tier A has zero parsed sources")

    return errors
