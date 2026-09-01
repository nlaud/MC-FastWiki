"""Nine fields of `{{Infobox entity}}` that the Bucket API does not carry.

`pipeline.enrich.droptable`, `.trade`, and the rest all read a Bucket table:
structured rows, a JSON blob, a clean edition split. The infobox has none of
that. `health`, `damage`, `size`, `usableitems`, `armor`, `behavior`,
`mobtype`, `speed`, and `knockbackresistance` live only in the free-form
wikitext of `{{Infobox entity}}` on each mob's own page, mixed with prose,
citations, and -- the whole reason this module exists as carefully as it does
-- Bedrock numbers sitting inline with the Java ones they are meant to replace.

Non-negotiable 1 of CLAUDE.md: a Bedrock number reaching the screen is a
correctness bug. `pipeline.enrich.markup` carries the edition filter that
makes that promise; this module is the nine field parsers built on top of it,
plus the report. **A field that cannot be read confidently is never guessed.**
There is no fallback path anywhere below that returns a plausible number --
only `UnparsedField`, with the raw wikitext attached so a person can judge it.
That mirrors the `SkippedRow` convention every other `pipeline.enrich` module
keeps, for the same reason CLAUDE.md gives: a wrong number mid-match is worse
than a gap.

`EnrichError` stays reserved for a shape fault, exactly as the package
docstring states it: a page that should carry `{{Infobox entity}}` and does
not. That stops the build, because it means this module no longer understands
the page it was asked to read. A field within a well-formed infobox that this
module cannot parse is never that -- it is an `UnparsedField`.

## How a field becomes zero or more values

Every field parser walks the same three passes, built once here rather than
six times:

1. `markup.split_lines` cuts the field's raw text into display lines.
2. A line-by-line walk (`_content_rows`) reads each line through
   `markup.classify_heading`: a `REGION` heading is consumed and adds no
   label; a `BLOCK` or `UNMARKED` heading replaces the label the following
   lines carry (`'''Large:'''`, `'''Adult:'''`, `'''Melee:'''`); everything
   else is a content row, carrying whatever label is currently active. A row
   whose line reads as Bedrock (`markup.scope_editions`) is dropped here and
   recorded as a `FilteredLine` -- never handed to a field parser at all.
3. The field's own parser reads each surviving row's raw line for its own
   shape -- an `{{hp|...}}` count, a `Height:`/`Width:` pair, a leading or
   trailing label of its own. Nothing here second-guesses the edition filter;
   a row this pass sees has already been decided Java or unmarked.

If a field carries text but produces no value at all, one `UnparsedField` is
recorded for the *whole* field with the raw wikitext attached, rather than one
per unreadable line. Frog's `damage` ("Instant kill, ignores health...", no
`{{hp}}` template at all) and Wither Skeleton's `speed` ("0.25 when idle and
0.3125 when attacking", two numbers glued into one sentence with no clean
label to hang either one on) are both exactly this: real prose, correctly
read as nothing rather than as a guess.

## Where a range comes from, and why no separator word is ever parsed

Section 3 of the implementation brief lists three ways the wiki writes a
damage range: an en dash (`{{hp|4.75}} – {{hp|11.75}}`, Iron Golem), a hyphen
(`{{hp|2}} - {{hp|4}}`, Stray), and the word "to" (`{{hp|2}} to {{hp|5}}`,
Piglin). This module never parses any of the three. A range is simply *two*
`{{hp|...}}` (or `{{health|...}}`, `{{armor|...}}`) templates found on one
line, in document order, regardless of what separator sits between them --
counting templates is exact where matching a separator word is not, and it
reads all three forms with the same code path.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, model_validator

from pipeline.enrich import EnrichError, group_by, wiki_url
from pipeline.enrich.markup import (
    HORIZONTAL_RULE,
    Edition,
    HeadingKind,
    classify_heading,
    find_template,
    scope_editions,
    split_lines,
    split_template,
    strip_edition_markers,
    strip_markup,
)

__all__ = [
    "ARMOR_TEMPLATE_NAMES",
    "DEFAULT_REPORT_PATH",
    "FIELD_ARMOR",
    "FIELD_BEHAVIOR",
    "FIELD_DAMAGE",
    "FIELD_HEALTH",
    "FIELD_KNOCKBACK_RESISTANCE",
    "FIELD_MOBTYPE",
    "FIELD_SIZE",
    "FIELD_SPEED",
    "FIELD_USABLE_ITEMS",
    "HEALTH_TEMPLATE_NAMES",
    "INFOBOX_TEMPLATE_NAME",
    "ArmorValue",
    "DamageValue",
    "Difficulty",
    "EntityInfobox",
    "FilteredLine",
    "HealthValue",
    "InfoboxReport",
    "LabelledText",
    "Measure",
    "SizeValue",
    "UnparsedField",
    "UsableItem",
    "parse_infobox",
    "parse_infoboxes",
    "select_infobox_pages",
    "write_report",
]

# The template every mob page carries its stats in.
INFOBOX_TEMPLATE_NAME = "Infobox entity"

# The nine infobox fields this module reads, under the name the wiki writes
# them as -- lowercase, no separator, exactly as `{{Infobox entity}}` args.
FIELD_HEALTH = "health"
FIELD_DAMAGE = "damage"
FIELD_SIZE = "size"
FIELD_USABLE_ITEMS = "usableitems"
FIELD_ARMOR = "armor"
FIELD_BEHAVIOR = "behavior"
FIELD_MOBTYPE = "mobtype"
FIELD_SPEED = "speed"
FIELD_KNOCKBACK_RESISTANCE = "knockbackresistance"

# The template names that carry a health point value. `{{health|...}}` is a
# second name for the same thing -- Dolphin and Hoglin both use it in place of
# `{{hp|...}}`, and nothing about its shape differs.
HEALTH_TEMPLATE_NAMES = ("hp", "health")
ARMOR_TEMPLATE_NAMES = ("armor",)

# Where `parse_infoboxes` writes its report by default. `data/reports/` is
# gitignored, and the writer takes an explicit path so a later emit stage can
# redirect it without touching this module.
DEFAULT_REPORT_PATH = Path("data") / "reports" / "unparsed-report.json"


class Difficulty(StrEnum):
    """The three difficulty tiers a `damage` line can be written under."""

    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"


class Measure(BaseModel, frozen=True):
    """A health point, armor point, or damage value -- a span when the wiki gives one.

    `minimum == maximum` for a fixed value, which every plain `{{hp|N}}`
    produces; `minimum < maximum` for the two-template ranges the module
    docstring explains.
    """

    minimum: Decimal
    maximum: Decimal

    @model_validator(mode="after")
    def _minimum_cannot_exceed_the_maximum(self) -> "Measure":
        """Refuse a range that runs backwards."""
        if self.minimum > self.maximum:
            raise EnrichError(f"a measure cannot range from {self.minimum} to {self.maximum}.")
        return self

    @property
    def is_fixed(self) -> bool:
        """Return whether this measure is a single value rather than a range."""
        return self.minimum == self.maximum


class HealthValue(BaseModel, frozen=True):
    """One health figure the infobox carries, and the variant it belongs to."""

    labels: tuple[str, ...]
    value: Measure


class DamageValue(BaseModel, frozen=True):
    """One damage figure, its variant, and the difficulty tier(s) it applies at."""

    labels: tuple[str, ...]
    difficulties: tuple[Difficulty, ...]
    value: Measure


class SizeValue(BaseModel, frozen=True):
    """One height/width pair, and the variant it describes."""

    labels: tuple[str, ...]
    height: Decimal
    width: Decimal


class ArmorValue(BaseModel, frozen=True):
    """One armor figure, labelled the same way `HealthValue` is."""

    labels: tuple[str, ...]
    value: Measure


class UsableItem(BaseModel, frozen=True):
    """One item, block, or environment drop a `{{drop|...}}` template names."""

    name: str
    kind: str | None
    note: str | None


class LabelledText(BaseModel, frozen=True):
    """A field read as plain text rather than a number: `behavior`, `mobtype`

    text, `speed`, and `knockbackresistance` all read this way. `labels` comes
    from a heading above the line or a trailing `(parenthetical)` on it;
    `text` is the line itself, cleaned of markup.
    """

    labels: tuple[str, ...]
    text: str


class EntityInfobox(BaseModel, frozen=True):
    """Everything this module could read from one mob's `{{Infobox entity}}`."""

    page: str
    wiki_url: str
    health: tuple[HealthValue, ...]
    damage: tuple[DamageValue, ...]
    size: tuple[SizeValue, ...]
    usable_items: tuple[UsableItem, ...]
    armor: tuple[ArmorValue, ...]
    behavior: tuple[LabelledText, ...]
    mob_type: tuple[str, ...]
    speed: tuple[LabelledText, ...]
    knockback_resistance: tuple[LabelledText, ...]


class UnparsedField(BaseModel, frozen=True):
    """One field this module read text for and could not turn into a value.

    Reported, never raised, and never guessed at -- the module docstring
    explains why this is the single most important rule of the whole parser.
    """

    page: str
    field: str
    reason: str
    text: str


class FilteredLine(BaseModel, frozen=True):
    """One line the edition filter dropped, and which field it came from.

    Every line `pipeline.enrich.markup.scope_editions` reads as Bedrock is
    recorded here rather than only silently excluded, so the filter's work is
    inspectable rather than assumed -- the same reasoning the task plan gives
    for keeping this list in `InfoboxReport` at all.
    """

    page: str
    field: str
    edition: Edition
    line: str


class InfoboxReport(BaseModel, frozen=True):
    """What one read of a batch of mob pages produced."""

    entities: tuple[EntityInfobox, ...]
    by_page: Mapping[str, EntityInfobox]
    unparsed: tuple[UnparsedField, ...] = ()
    filtered: tuple[FilteredLine, ...] = ()

    @classmethod
    def build(
        cls,
        entities: Sequence[EntityInfobox],
        *,
        unparsed: Sequence[UnparsedField] = (),
        filtered: Sequence[FilteredLine] = (),
    ) -> "InfoboxReport":
        """Return a report over `entities`, with `by_page` computed from them."""
        by_page = {group: items[0] for group, items in group_by(entities, lambda e: e.page).items()}
        return cls(
            entities=tuple(entities),
            by_page=by_page,
            unparsed=tuple(unparsed),
            filtered=tuple(filtered),
        )

    @model_validator(mode="after")
    def _by_page_must_match_the_entities(self) -> "InfoboxReport":
        """Refuse an index that does not index its own entities."""
        grouped = group_by(self.entities, lambda e: e.page)
        expected = {group: items[0] for group, items in grouped.items()}
        if dict(self.by_page) != expected:
            raise EnrichError("the page index does not match the entities of this report.")
        return self


class _Row(BaseModel, frozen=True):
    """One content line of a field, with the label(s) active above it."""

    labels: tuple[str, ...]
    line: str


def _content_rows(
    field_text: str, *, page: str, field: str
) -> tuple[tuple[_Row, ...], tuple[FilteredLine, ...]]:
    """Split one field's raw text into kept rows and the lines the edition filter dropped.

    See the module docstring's three-pass description. `<hr>` and a `REGION`
    heading are consumed with no effect on the label a following row carries;
    a `BLOCK` or `UNMARKED` heading replaces it outright -- labels never nest,
    because nothing in the sample needs them to.
    """
    lines = split_lines(field_text)
    scopes = scope_editions(lines)
    labels: tuple[str, ...] = ()
    rows: list[_Row] = []
    filtered: list[FilteredLine] = []
    for line, scope in zip(lines, scopes, strict=True):
        if line == HORIZONTAL_RULE:
            continue
        classification = classify_heading(line)
        if classification.kind in (HeadingKind.REGION, HeadingKind.UNPARSEABLE):
            continue
        if classification.kind in (HeadingKind.BLOCK, HeadingKind.UNMARKED):
            labels = (classification.label,)
            continue
        if scope.edition is Edition.BEDROCK:
            filtered.append(
                FilteredLine(page=page, field=field, edition=Edition.BEDROCK, line=line)
            )
            continue
        rows.append(_Row(labels=labels, line=line))
    return tuple(rows), tuple(filtered)


def _value_templates(line: str, names: Sequence[str]) -> list[Decimal]:
    """Return the `Decimal` first argument of every template of `names` on `line`, in order.

    Merges every named template rather than reading one name at a time, so
    `{{hp|...}}` and `{{health|...}}` combine in document order even though no
    field in the sample actually mixes the two on one line.
    """
    found = [item for name in names for item in find_template(line, name)]
    found.sort(key=lambda item: item.start)
    values: list[Decimal] = []
    for item in found:
        parsed = split_template(item.text)
        if not parsed.positional:
            continue
        try:
            values.append(Decimal(parsed.positional[0].strip()))
        except InvalidOperation:
            continue
    return values


def _measure_of(values: Sequence[Decimal]) -> Measure | None:
    """Return the `Measure` that `values` describes, or `None` when the shape is not one this
    module recognizes.

    One value is a fixed measure. Two are a range, whichever of the three
    separators the wiki wrote between them -- the module docstring explains
    why the separator itself is never read. Any other count is a shape this
    module has not seen and will not guess about.
    """
    if len(values) == 1:
        return Measure(minimum=values[0], maximum=values[0])
    if len(values) == 2:
        return Measure(minimum=min(values), maximum=max(values))
    return None


_LEADING_LABEL = re.compile(r"\A([A-Za-z][A-Za-z /]{0,20}):\s*(?=\S)")
_TRAILING_LABEL = re.compile(r"\(([A-Za-z][A-Za-z ]{0,18})\)\s*\Z")
_DIFFICULTY_PREFIX = re.compile(
    r"\A(easy|normal|hard)((\s*,\s*|\s+and\s+)(easy|normal|hard))*\s*:", re.IGNORECASE
)
_DIFFICULTY_WORD = re.compile(r"easy|normal|hard", re.IGNORECASE)
_SIZE_LINE = re.compile(
    r"\A(height and width|height|width)\s*:\s*(\d+(?:\.\d+)?)\s*blocks?\Z", re.IGNORECASE
)
_SCALAR = r"\d+(?:\.\d+)?%?"
_SCALAR_LINE = re.compile(rf"\A({_SCALAR}(?:\s*[-–]\s*{_SCALAR})?)\Z")


def _leading_label(cleaned: str) -> str | None:
    """Return the `Label` of a `Label: value` line, or `None`.

    Applies to text already run through `strip_markup`, so `'''Large:'''
    {{hp|16}}` (Magma Cube) has already lost its bold quotes by the time this
    matches. `Height:`/`Width:` never reach this function -- `size` has its own
    parser -- so there is no need to exclude them here.
    """
    match = _LEADING_LABEL.match(cleaned)
    return match.group(1).strip() if match else None


def _trailing_label(cleaned: str) -> str | None:
    """Return the short `(word)` a line ends with, or `None`.

    Deliberately narrow -- one to nineteen letters and spaces -- so it catches
    `(baby)` and `(leaders)` and does not catch Creaking's long prose aside
    `(immune to damage when spawned using a creaking heart)`, which the module
    docstring's caller is expected to drop rather than mistake for a label.
    """
    match = _TRAILING_LABEL.search(cleaned)
    return match.group(1).strip() if match else None


def _leading_difficulty(cleaned: str) -> tuple[Difficulty, ...] | None:
    """Return the difficulty tier(s) a line opens with, or `None`.

    `Easy:`, `Hard:`, and `Easy and Normal:` all match. Applied to the same
    `strip_markup`-cleaned text `_leading_label` reads, so a bold difficulty
    label (none appear in the sample, but nothing rules one out) still matches.
    """
    match = _DIFFICULTY_PREFIX.match(cleaned)
    if match is None:
        return None
    order = {"easy": Difficulty.EASY, "normal": Difficulty.NORMAL, "hard": Difficulty.HARD}
    return tuple(order[word.casefold()] for word in _DIFFICULTY_WORD.findall(match.group(0)))


def _combine_labels(labels: tuple[str, ...], extra: str | None) -> tuple[str, ...]:
    """Return `labels` with `extra` appended, unless it is absent or already there."""
    if extra and extra not in labels:
        return (*labels, extra)
    return labels


def _parse_health(rows: Sequence[_Row]) -> tuple[HealthValue, ...]:
    """Read the `health` field: one or two `{{hp|...}}`/`{{health|...}}` per row.

    A row's label comes from an enclosing heading when there is one (Cow's
    `size` shape has an analogue for `health` too, though the sample carries
    none), and otherwise from a same-line `Label:` prefix (Magma Cube's
    `'''Large:''' {{hp|16}}`, Wolf's `'''Wild:''' {{hp|8}}`, Iron Golem's plain
    `Uncracked: {{hp|100}}`) or a trailing `(label)` (Zombie's leader health,
    `{{hp|40}} to {{hp|100}} (leaders)`). A value with a long prose qualifier
    instead of a short label -- Creaking's `{{hp|1}} (immune to damage when
    spawned using a [[creaking heart]])` -- keeps its value and drops the
    qualifier, because `_trailing_label` refuses anything longer than a label.
    """
    values: list[HealthValue] = []
    for row in rows:
        text = strip_edition_markers(row.line)
        measure = _measure_of(_value_templates(text, HEALTH_TEMPLATE_NAMES))
        if measure is None:
            continue
        cleaned = strip_markup(text)
        labels = row.labels
        if not labels:
            leading = _leading_label(cleaned)
            if leading is not None:
                labels = (leading,)
        labels = _combine_labels(labels, _trailing_label(cleaned))
        values.append(HealthValue(labels=labels, value=measure))
    return tuple(values)


def _parse_armor(rows: Sequence[_Row]) -> tuple[ArmorValue, ...]:
    """Read the `armor` field: the same labelling rules `_parse_health` uses.

    `'''Large:''' {{armor|12}}` (Magma Cube) and `Closed: {{armor|20}}`
    (Shulker) are both a same-line label; `Opened: {{armor|0}}` on the next
    line proves zero is a real value and not a missing one.
    """
    values: list[ArmorValue] = []
    for row in rows:
        text = strip_edition_markers(row.line)
        measure = _measure_of(_value_templates(text, ARMOR_TEMPLATE_NAMES))
        if measure is None:
            continue
        cleaned = strip_markup(text)
        labels = row.labels
        if not labels:
            leading = _leading_label(cleaned)
            if leading is not None:
                labels = (leading,)
        values.append(ArmorValue(labels=labels, value=measure))
    return tuple(values)


def _parse_damage(rows: Sequence[_Row]) -> tuple[DamageValue, ...]:
    """Read the `damage` field: difficulty tiers, variants, and one-or-two-template ranges.

    A difficulty label can sit on the same line as its value (`Easy:
    {{hp|2.5}}`, most pages) or on a line of its own with the value on the
    next (Hoglin's `Easy:` then ` {{hp|2.5}} to {{hp|5}}`) -- `pending` carries
    a lone difficulty label across that gap. A row with no `{{hp|...}}` at all
    -- prose, an annotation, a heading `_content_rows` did not classify as one
    -- contributes nothing and clears `pending`, because a difficulty label
    only ever governs the very next row.
    """
    values: list[DamageValue] = []
    pending: tuple[Difficulty, ...] | None = None
    for row in rows:
        text = strip_edition_markers(row.line)
        cleaned = strip_markup(text)
        difficulties = _leading_difficulty(cleaned)
        templates = _value_templates(text, ("hp",))
        if difficulties is not None and not templates:
            pending = difficulties
            continue
        measure = _measure_of(templates)
        if measure is None:
            pending = None
            continue
        if difficulties is None:
            difficulties = pending if pending is not None else ()
        pending = None
        values.append(DamageValue(labels=row.labels, difficulties=difficulties, value=measure))
    return tuple(values)


def _parse_size(rows: Sequence[_Row]) -> tuple[SizeValue, ...]:
    """Read the `size` field: `Height:`/`Width:` pairs, or a combined `Height and width:`.

    A `Height:` line is held until the matching `Width:` line of the same
    label arrives (`_SIZE_LINE`'s two forms almost always alternate directly),
    and a label change without a matching `Width:` drops the stray `Height:`
    rather than pairing it with the wrong variant.
    """
    values: list[SizeValue] = []
    pending_height: Decimal | None = None
    pending_labels: tuple[str, ...] | None = None
    for row in rows:
        cleaned = strip_markup(strip_edition_markers(row.line))
        match = _SIZE_LINE.match(cleaned)
        if match is None:
            continue
        key = match.group(1).casefold()
        value = Decimal(match.group(2))
        if key == "height and width":
            values.append(SizeValue(labels=row.labels, height=value, width=value))
            pending_height = None
            pending_labels = None
            continue
        if key == "height":
            pending_height = value
            pending_labels = row.labels
            continue
        if pending_height is not None and pending_labels == row.labels:
            values.append(SizeValue(labels=row.labels, height=pending_height, width=value))
        pending_height = None
        pending_labels = None
    return tuple(values)


_USABLE_ITEM_TEMPLATE_NAME = "drop"
_TRAILING_NOTE = re.compile(r"\(([^()]+)\)")


def _usable_item_note(line: str, after: int) -> str | None:
    """Return the parenthetical note that trails a `{{drop|...}}` call, or `None`.

    Covers both shapes the sample carries: a `<small>(note)</small>` wrapper
    (Wolf's saddle note, Happy Ghast's harness note) and a bare `(note)` with
    no wrapper at all (Cat's `(tamed only)`). `strip_markup` removes the
    `<small>` tags before the search, so both read the same way.
    """
    trailing = strip_markup(line[after:])
    match = _TRAILING_NOTE.search(trailing)
    return match.group(1).strip() if match else None


def _parse_usable_items(rows: Sequence[_Row]) -> tuple[UsableItem, ...]:
    """Read the `usableitems` field: every `{{drop|...}}`/`{{Drop|...}}` call.

    The template name's case varies (`drop`/`Drop`) and `find_template`
    already matches case-insensitively. The item name comes from a `text=`
    argument first (`{{Drop|Env|Item|text=Any item}}`, Allay), then the last
    positional argument (`{{drop|Item|id=Raw Beef|Meat}}` names `Meat`, the
    display text, not the `id=Raw Beef` override), then an `id=` argument on
    its own. A `{{drop|...}}` this module cannot name is skipped rather than
    guessed at; every other template mixed into the field, such as Ocelot's
    `{{ItemLink|Raw Salmon}}`, is never matched by `find_template` at all and
    needs no special handling.
    """
    items: list[UsableItem] = []
    for row in rows:
        for found in find_template(row.line, _USABLE_ITEM_TEMPLATE_NAME):
            parsed = split_template(found.text)
            kind = parsed.positional[0] if parsed.positional else None
            name = parsed.named.get("text")
            if name is None and len(parsed.positional) > 1:
                name = parsed.positional[-1]
            if name is None:
                name = parsed.named.get("id")
            if name is None:
                continue
            note = _usable_item_note(row.line, found.end)
            items.append(UsableItem(name=name, kind=kind, note=note))
    return tuple(items)


def _parse_labelled_text(rows: Sequence[_Row]) -> tuple[LabelledText, ...]:
    """Read `behavior` as plain text, one row per line.

    Comments and `<ref>` blocks are the two traps the sample carries here --
    Villager's `behavior` never appears alone (the field is shared with other
    prose fields structurally), but Wolf's ref citation and the two HTML
    comments in the sample both have to be gone before the text is read, and
    `strip_markup` already removes both.
    """
    values: list[LabelledText] = []
    for row in rows:
        cleaned = strip_markup(strip_edition_markers(row.line))
        if not cleaned:
            continue
        values.append(LabelledText(labels=row.labels, text=cleaned))
    return tuple(values)


_ENTITY_LINK_TEMPLATE_NAME = "EntityLink"


def _parse_mob_type(rows: Sequence[_Row]) -> tuple[str, ...]:
    """Read `mobtype`: every `{{EntityLink|...}}` target, in document order.

    Works the same way whether the wiki separates them with `<br>` (most
    pages) or a comma (Shulker's `{{EntityLink|Golem}}, {{EntityLink|Monster}}`
    sits on one line after `split_lines`), because `find_template` finds every
    occurrence on a line regardless of what sits between them.
    """
    types: list[str] = []
    for row in rows:
        for found in find_template(row.line, _ENTITY_LINK_TEMPLATE_NAME):
            parsed = split_template(found.text)
            if parsed.positional:
                types.append(parsed.positional[0])
    return tuple(types)


def _parse_scalar_field(rows: Sequence[_Row]) -> tuple[LabelledText, ...]:
    """Read `speed` or `knockbackresistance`: a bare number, percentage, or range.

    A line must reduce to *only* a scalar or a two-scalar range once its
    edition marker and trailing `(label)` are removed -- `0.23`, `100%`,
    `0%–5%`, `0.35` (from `0.35 (baby)`). Prose such as Wither Skeleton's
    `0.25 when idle and 0.3125 when attacking` fails this match and is
    dropped rather than guessed at: there are two numbers and no clean label
    to hang either one on, which is exactly the shape section 3 of the brief
    calls out as a refusal.
    """
    values: list[LabelledText] = []
    for row in rows:
        cleaned = strip_markup(strip_edition_markers(row.line))
        label = _trailing_label(cleaned)
        core = _TRAILING_LABEL.sub("", cleaned).strip() if label else cleaned
        match = _SCALAR_LINE.match(core)
        if match is None:
            continue
        labels = _combine_labels(row.labels, label)
        values.append(LabelledText(labels=labels, text=match.group(1)))
    return tuple(values)


def _read_field[T](
    field: str,
    fields: Mapping[str, str],
    parser: Callable[[Sequence[_Row]], tuple[T, ...]],
    *,
    page: str,
    unparsed: list[UnparsedField],
    filtered: list[FilteredLine],
) -> tuple[T, ...]:
    """Return the parsed values of `field`, recording a report entry when there are none.

    Generic over the field's own value type, so each call below keeps mypy's
    strict typing rather than passing through a `tuple[object, ...]` that
    would need a cast at every use. `group_by` in `pipeline.enrich` sets the
    precedent for a bare generic function in this codebase.

    `unparsed` and `filtered` are mutated in place rather than returned,
    because every one of the nine calls in `parse_infobox` shares the same two
    lists -- a report is built across the whole infobox, not one field at a
    time.
    """
    raw = fields.get(field, "")
    if not raw.strip():
        return ()
    rows, field_filtered = _content_rows(raw, page=page, field=field)
    filtered.extend(field_filtered)
    values = parser(rows)
    if not values:
        reason = (
            f"every line of this {field} field is Bedrock-only"
            if field_filtered and not rows
            else f"no {field} value could be read with confidence"
        )
        unparsed.append(UnparsedField(page=page, field=field, reason=reason, text=raw.strip()))
    return values


def _infobox_fields(page_text: str, *, page: str) -> Mapping[str, str]:
    """Return the named arguments of `page`'s own `{{Infobox entity}}` template.

    Raises `EnrichError` when the page carries none at all -- a shape this
    module no longer understands, not a field it could not read.

    Some pages carry more than one. Shulker documents `Shulker Bullet` as a
    second `{{Infobox entity}}` further down its own page, for the projectile
    rather than the mob the page is named after. The first template is always
    the page's own -- `title = Shulker` opens the first one, `title = Shulker
    Bullet` the second -- so this module reads that one and leaves the rest.
    A second entity documented on someone else's page is out of scope for the
    one-page-one-mob model Phase 2 reads by; it gets its own page and its own
    read when the pipeline asks for it by that title.
    """
    found = find_template(page_text, INFOBOX_TEMPLATE_NAME)
    if not found:
        raise EnrichError(f"{page!r} carries no {{{{{INFOBOX_TEMPLATE_NAME}}}}} template.")
    return split_template(found[0].text).named


def parse_infobox(
    page: str, page_text: str, *, wiki_url_of: Callable[[str], str] = wiki_url
) -> tuple[EntityInfobox, tuple[UnparsedField, ...], tuple[FilteredLine, ...]]:
    """Return one mob's `EntityInfobox`, its unparsed fields, and its filtered lines.

    Pure: no network, no file system. `wiki_url_of` defaults to
    `pipeline.enrich.wiki_url`, the same attribution URL every other enrich
    model carries, and is a parameter only so a test can pass a fake without
    monkeypatching the shared helper.
    """
    fields = _infobox_fields(page_text, page=page)
    unparsed: list[UnparsedField] = []
    filtered: list[FilteredLine] = []

    def read[T](field: str, parser: Callable[[Sequence[_Row]], tuple[T, ...]]) -> tuple[T, ...]:
        return _read_field(field, fields, parser, page=page, unparsed=unparsed, filtered=filtered)

    entity = EntityInfobox(
        page=page,
        wiki_url=wiki_url_of(page),
        health=read(FIELD_HEALTH, _parse_health),
        damage=read(FIELD_DAMAGE, _parse_damage),
        size=read(FIELD_SIZE, _parse_size),
        usable_items=read(FIELD_USABLE_ITEMS, _parse_usable_items),
        armor=read(FIELD_ARMOR, _parse_armor),
        behavior=read(FIELD_BEHAVIOR, _parse_labelled_text),
        mob_type=read(FIELD_MOBTYPE, _parse_mob_type),
        speed=read(FIELD_SPEED, _parse_scalar_field),
        knockback_resistance=read(FIELD_KNOCKBACK_RESISTANCE, _parse_scalar_field),
    )
    return entity, tuple(unparsed), tuple(filtered)


def select_infobox_pages(pages: Mapping[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Split `pages` into the ones that carry an entity infobox and the ones that do not.

    `parse_infoboxes` -- by way of `_infobox_fields` -- raises `EnrichError` the
    moment it meets a page with no `{{Infobox entity}}` template at all, and it
    is right to: a page this module was told is a mob page and cannot find the
    template on is a shape this module no longer understands, not a field it
    could not read. That rule only stays true, though, if the caller keeps its
    own promise not to hand `parse_infoboxes` a page that was never going to
    carry the template in the first place. This function is how a caller keeps
    that promise: it reads every page once, keeps the ones with the template,
    and returns the rest as titles rather than as a fault.

    A page with no infobox is a Tier B gap, not a shape fault -- the same
    distinction `pipeline.enrich`'s own package docstring draws for every other
    row a wiki page turns out not to carry: a half-edited or miscategorised
    page is expected here and there, and a caller reports it and carries on
    rather than stopping the whole read over one page. Filtering here, before
    `parse_infoboxes` ever sees the title, is what turns that expected gap into
    a report entry instead of a build-stopping exception.

    The measured live case naming why this function exists at all is Armor
    Stand. `pipeline.normalize.merge`'s own module docstring calls
    `minecraft:armor_stand` a mob the mcmeta signals leave "undecided, defaults
    to a mob" -- it has an entity loot table and no spawn egg, so Tier A's own
    classifier cannot rule it out. The wiki disagrees: the Armor Stand page
    documents an item, not a `{{Infobox entity}}` mob, so a selection rule
    built only on the mcmeta side of that disagreement hands `parse_infoboxes`
    a page that was never going to have the template, and the whole build dies
    on the one page where Tier A and Tier B genuinely do not agree. Filtering
    on the template's own presence is what lets that disagreement become one
    name in the second half of this function's return value instead of a
    build fault.

    Returns `(with_template, sorted_titles_without)`. `with_template` keeps
    `pages`' own text unchanged, ready for `parse_infoboxes`. The titles
    without a template come back sorted, because a caller reports them, and a
    report a person reads should not depend on dictionary iteration order.
    """
    with_template: dict[str, str] = {}
    without_template: list[str] = []
    for title, text in pages.items():
        if find_template(text, INFOBOX_TEMPLATE_NAME):
            with_template[title] = text
        else:
            without_template.append(title)
    return with_template, tuple(sorted(without_template))


def parse_infoboxes(
    pages: Mapping[str, str], *, wiki_url_of: Callable[[str], str] = wiki_url
) -> InfoboxReport:
    """Return the `InfoboxReport` of every page of `pages`, keyed by title.

    `pages` maps a page title to its raw wikitext -- the shape
    `pipeline.fetch.wikitext.WikitextReport.contents()` returns. A page whose
    infobox this module cannot even find raises `EnrichError` and stops the
    whole read, per the module docstring's rule for a shape fault.
    """
    entities: list[EntityInfobox] = []
    unparsed: list[UnparsedField] = []
    filtered: list[FilteredLine] = []
    for page, page_text in pages.items():
        entity, page_unparsed, page_filtered = parse_infobox(
            page, page_text, wiki_url_of=wiki_url_of
        )
        entities.append(entity)
        unparsed.extend(page_unparsed)
        filtered.extend(page_filtered)
    return InfoboxReport.build(entities, unparsed=unparsed, filtered=filtered)


def write_report(report: InfoboxReport, path: Path = DEFAULT_REPORT_PATH) -> None:
    """Write `report` to `path` as indented JSON, creating parent directories as needed.

    `path` defaults to `DEFAULT_REPORT_PATH` and is otherwise an explicit
    argument, so the Phase 3 emit stage can redirect it without editing this
    module -- Decision 2 of the task plan.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = report.model_dump(mode="json")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
