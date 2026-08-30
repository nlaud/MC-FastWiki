"""Wikitext primitives that know nothing about infoboxes.

`pipeline.enrich.infobox` reads nine fields of `{{Infobox entity}}`, but the
scanner underneath it is not infobox-specific: Phase 6b needs the same
brace-depth template scanner for the `Obtaining` section, and Phase 6c needs it
for the `World generation` tables. This module is that shared layer, so it
knows about `{{templates}}`, `[[links]]`, and edition markers, and it knows
nothing about `health` or `damage`.

**Why a regex cannot do this job.** Creeper's `damage` field holds nine nested
`{{hp|...}}` calls inside two `{{IN|...}}` regions, and a naive `text.split("|")`
run across the whole field shreds every one of them, because each `{{hp|22.5}}`
itself contains a `|`. Every splitter here is brace-depth aware: it counts
`{{ }}` and `[[ ]]` as it walks the text, and it treats a whole `<ref>...</ref>`
span as one atomic unit, so a `|` inside a citation does not end an argument.

## The edition filter, and why "any variant heading clears it" is a bug

Non-negotiable 1 of CLAUDE.md: a Bedrock number reaching the screen is a
correctness bug, and the filter belongs to the pipeline. Verified against the
50-page live sample captured 2026-08-30, four distinct marker forms carry
edition information, and one of them is not a template at all:

1. **Inline suffix** -- `{{only|bedrock}}`, `{{only|be|ee|short=1}}`,
   `{{only|bedrock|short=y}}`. Scopes the one line it sits on.
2. **Template heading** -- `'''{{IN|BE}}:'''`, `'''{{IN|Bedrock}}:'''`,
   bare `{{BE}}:`. Scopes until the next heading that changes the scope, or an
   `<hr>`.
3. **Plain-text heading** -- `'''Bedrock:'''`, with no template at all (the
   Bogged page). Same scope rule as a template heading.
4. **Java counterpart** -- `{{IN|Java}}`, `{{JE}}`, `{{only|JE|short=1}}`.
   Positively marks a keep, the same way its Bedrock sibling marks a drop.

A heading can *open a region* or *scope one block*, and the two behave
differently under a subordinate variant heading, which is the whole risk here.
Creeper's `damage` opens with `'''{{IN|BE}}:'''` and then nests
`'''Regular:'''` and `'''Charged:'''` underneath it. Zombie's `size` instead
writes `'''Adult {{IN|Bedrock}}:'''`, where the edition marker sits *inside* a
heading that also names a variant. Treating both the same way is a correctness
bug in either direction:

* If a subordinate variant heading always cleared the scope, `'''Regular:'''`
  under Creeper's `'''{{IN|BE}}:'''` would clear it, and Creeper's Bedrock
  explosion damage (14.75 at Easy) would publish as Java. Checked against the
  full 50-page sample: **12 page-fields** carry this shape --
  Creeper damage, Skeleton damage, Cow size, Magma Cube size, Villager damage,
  Wither Skeleton damage, Stray damage, Turtle size, Drowned damage, Piglin
  damage, Sniffer size, Bogged damage.
* If a subordinate variant heading never cleared the scope, Zombie's unmarked
  `'''Baby:'''` heading -- which follows `'''Adult {{IN|Bedrock}}:'''` -- would
  stay scoped to Bedrock, and Zombie's own Java baby height (0.98 blocks) would
  be dropped as if it were a Bedrock number. Checked against the same sample:
  **11 page-fields** carry this shape -- Zombie size, Chicken size, Villager
  size, Husk size, Drowned size, Goat size, Piglin size, Hoglin damage, Hoglin
  size, Zoglin size, Warden size.

So a heading is classified before it is allowed to change anything:

* A **standalone edition heading** -- nothing remains once the edition marker
  is removed -- opens a *region*. A subordinate heading with no edition marker
  of its own does not clear it. Only another standalone edition heading, or an
  `<hr>`, does.
* An **embedded edition marker** -- a variant name remains alongside the
  edition marker -- scopes only its own *block*. The next heading with no
  edition marker of its own clears it, which is the reset Zombie's `Baby`
  needs.

`classify_heading` does the telling-apart: remove the edition template(s),
strip markup, drop the connecting words `in`, `the`, `on`, `for`, and see what
is left. `'''{{IN|BE}}:'''` reduces to nothing (region). `'''In {{JE}}:'''`
reduces to `in`, a connecting word, so also nothing (region -- Cow's `size`).
`'''Adult {{IN|Bedrock}}:'''` leaves `Adult` (block -- Zombie's `size`).
`'''While jumping:'''{{only|java|short=1}}` leaves `While jumping` (block --
Goat's `size`). A heading this cannot place goes to the caller as
`HeadingKind.UNPARSEABLE` rather than being guessed either way.

**A difficulty label is not a heading.** `Easy:`, `Normal:`, `Hard:`, and
`Easy and Normal:` are heading-*shaped* -- bold or not, they end in a bare
colon -- but they carry no edition or variant information; the `damage` field
parser reads them as a difficulty tier, not as a scope change. Hoglin's damage
field is the case that would break without this: `'''Adult in {{JE}}:'''` is
followed by `Easy:` on its own line and the value on the next, and if `Easy:`
were read as an ordinary unmarked heading it would clear the Java block scope
that `Adult in {{JE}}:` just opened -- and the very next `'''Adult in
{{BE}}:'''` would then have its own `Easy:` do the same, letting the Bedrock
numbers under it read as unmarked and default to kept. So `classify_heading`
recognizes a difficulty word or phrase and reports it as `NOT_A_HEADING`,
leaving it as an ordinary line for the field parser to read.

**`<hr>` is not one of `split_lines`'s listed separators, and it still has to
become its own line.** Cat's `health` field writes
`'''{{JE}}:'''<br>{{hp|10}}<hr>'''{{BE}}:'''<br>...` with the rule glued
directly onto the surrounding text, no `<br>` beside it. Splitting only on
`<br>` and newline would leave `{{hp|10}}<hr>'''{{BE}}:'''` as one line, and
`scope_editions` would never see the boundary it exists to clear. So
`split_lines` also cuts on `<hr>` (and `<hr/>`, `<hr />`) and keeps a literal
`"<hr>"` line in its output, which is what `scope_editions` matches on.
"""

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel

from pipeline.enrich import clean_text

__all__ = [
    "CONNECTING_WORDS",
    "DIFFICULTY_WORDS",
    "HORIZONTAL_RULE",
    "REACHED_DEFAULT",
    "REACHED_INHERITED_BLOCK",
    "REACHED_INHERITED_REGION",
    "REACHED_OWN_MARKER",
    "REACHED_UNPARSEABLE",
    "Edition",
    "FoundTemplate",
    "HeadingClassification",
    "HeadingKind",
    "LineScope",
    "ParsedTemplate",
    "classify_heading",
    "find_template",
    "scope_editions",
    "split_lines",
    "split_template",
    "strip_edition_markers",
    "strip_markup",
]

# The literal line `split_lines` emits for a horizontal rule. `scope_editions`
# matches on this exact string, so nothing else may produce it.
HORIZONTAL_RULE = "<hr>"

# The connecting words `classify_heading` drops before deciding whether a
# heading names a variant. Checked against the sample: `'''In {{JE}}:'''`
# (Cow) and `'''Adult in {{JE}}:'''` (Chicken) are the two real shapes.
CONNECTING_WORDS = frozenset({"in", "the", "on", "for"})

# The words a difficulty-tier line reduces to. `classify_heading` reads a line
# that is *only* these words (plus `and`/commas) as a value label, never as a
# heading that can change the edition scope -- see the module docstring's
# Hoglin example for why that distinction is load-bearing.
DIFFICULTY_WORDS = frozenset({"easy", "normal", "hard"})
_DIFFICULTY_FILLER = frozenset({"and", ","})


class Edition(StrEnum):
    """The two editions this project's markup ever has to tell apart.

    CLAUDE.md scopes this project to Java Edition alone, so `BEDROCK` is a
    value this module has to recognize only well enough to drop it -- Education
    Edition markers (`{{only|ee}}`) fold into `BEDROCK` for that reason: this
    project has no Education Edition page to keep them for.
    """

    JAVA = "java"
    BEDROCK = "bedrock"


class HeadingKind(StrEnum):
    """What kind of line `classify_heading` read, and what it may do to scope."""

    # An ordinary line: not heading-shaped, or heading-shaped but a difficulty
    # label. Carries no scope information of its own.
    NOT_A_HEADING = "not_a_heading"
    # Heading-shaped, no edition marker, and not a difficulty label -- a
    # variant name on its own, such as `'''Baby:'''` or `'''Melee:'''`.
    UNMARKED = "unmarked"
    # A standalone edition heading. Opens a region that only another
    # standalone edition heading or `<hr>` can clear.
    REGION = "region"
    # An embedded edition marker: the heading names a variant and an edition
    # together. Scopes only its own block.
    BLOCK = "block"
    # Heading-shaped, and it names more than one edition at once, or some
    # other shape `classify_heading` cannot place. Reported, never guessed.
    UNPARSEABLE = "unparseable"


class FoundTemplate(BaseModel, frozen=True):
    """One `{{name|...}}` call, and where it sits in the text it was found in."""

    start: int
    end: int
    # The whole call, verbatim, braces included.
    text: str


class ParsedTemplate(BaseModel, frozen=True):
    """One template split into its name and its arguments."""

    name: str
    positional: tuple[str, ...]
    named: Mapping[str, str]


class HeadingClassification(BaseModel, frozen=True):
    """What `classify_heading` decided about one line."""

    kind: HeadingKind
    # The edition the heading names, for `REGION` and `BLOCK`. `None` for every
    # other kind.
    edition: Edition | None
    # What remained after the edition template(s), markup, and connecting
    # words were removed. Empty for `REGION`, `NOT_A_HEADING`, and
    # `UNPARSEABLE`.
    label: str


# The reasons a `LineScope` gives for the edition it settled on.
REACHED_OWN_MARKER = "own marker"
REACHED_INHERITED_REGION = "inherited region"
REACHED_INHERITED_BLOCK = "inherited block"
REACHED_DEFAULT = "no scope"
REACHED_UNPARSEABLE = "unparseable heading"


class LineScope(BaseModel, frozen=True):
    """The edition verdict of one line, and how `scope_editions` reached it."""

    line: str
    # `None` means unmarked: nothing here says the line is Bedrock, so a
    # caller keeps it. `Edition.BEDROCK` means drop it. `Edition.JAVA` means it
    # was positively marked Java, which is also a keep.
    edition: Edition | None
    reached: str


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HR = re.compile(r"<hr\s*/?>", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# An opener with no closer. MediaWiki comments out the rest of the text when it
# meets one, so `split_template` does the same rather than letting a
# half-written comment leak the `|` characters after it into the argument list.
_UNCLOSED_COMMENT = re.compile(r"<!--.*\Z", re.DOTALL)
_REF_BLOCK = re.compile(r"<ref\b[^>]*>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
_REF_SELF_CLOSING = re.compile(r"<ref\b[^>]*/>", re.IGNORECASE)
_REF_OPEN = re.compile(r"<ref\b[^>]*>", re.IGNORECASE)
_REF_CLOSE = re.compile(r"</ref\s*>", re.IGNORECASE)
_FILE_LINK = re.compile(r"\[\[\s*[Ff]ile\s*:.*?\]\]", re.DOTALL)
_SMALL_TAG = re.compile(r"</?small>", re.IGNORECASE)
_GENERIC_TAG = re.compile(r"<[^>]+>")
_PIPED_LINK = re.compile(r"\[\[([^\]|]*)\|([^\]]*)\]\]")
_BARE_LINK = re.compile(r"\[\[([^\]|]*)\]\]")
_WHITESPACE = re.compile(r"\s+")
_NAMED_ARG = re.compile(r"\A([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)\Z", re.DOTALL)

_JAVA_TOKENS = frozenset({"java", "je", "java edition"})
_BEDROCK_TOKENS = frozenset(
    {"bedrock", "be", "bedrock edition", "ee", "education", "education edition"}
)


def _top_level_template_spans(text: str) -> list[tuple[int, int]]:
    """Return the `(start, end)` of every top-level `{{...}}` call in `text`.

    Brace-depth aware, so a `{{hp|{{x}}}}` call (none appear in the sample, but
    nothing rules one out) is one span rather than two. `end` is exclusive, one
    past the closing `}}`. A `{{` with no matching `}}` runs to the end of the
    text rather than being dropped, because a truncated field is still a field
    a caller should see, not one that silently loses its last template.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            start = index
            depth = 1
            cursor = index + 2
            while cursor < length and depth > 0:
                if text.startswith("{{", cursor):
                    depth += 1
                    cursor += 2
                elif text.startswith("}}", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            spans.append((start, cursor))
            index = cursor
        else:
            index += 1
    return spans


def find_template(text: str, name: str) -> tuple[FoundTemplate, ...]:
    """Return every top-level `{{name|...}}` call in `text`, in order.

    The name comparison is case-insensitive, because the wiki writes both
    `{{drop|...}}` and `{{Drop|...}}` for the same template (Zoglin, Allay,
    Copper Golem all use the capitalized form). A regex cannot do this scan on
    its own: a nested `{{ }}` would close the match early or not at all, so the
    span of each call comes from `_top_level_template_spans`, which counts
    depth as it walks.
    """
    target = name.casefold()
    found: list[FoundTemplate] = []
    for start, end in _top_level_template_spans(text):
        body = text[start:end]
        inner_name = body[2:-2].split("|", 1)[0].strip()
        if inner_name.casefold() == target:
            found.append(FoundTemplate(start=start, end=end, text=body))
    return tuple(found)


def _split_at_depth(text: str, separator: str) -> list[str]:
    """Split `text` on `separator` at depth 0, counting `{{ }}`, `[[ ]]`, and `<ref>`.

    A `<ref>...</ref>` span is treated as one atomic unit: a citation can hold
    a bare `|` in its own wikitext (a URL, a template argument), and that `|`
    must not end an argument of the template the ref sits inside.
    """
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        if text.startswith("{{", index):
            depth += 1
            buffer.append("{{")
            index += 2
            continue
        if text.startswith("}}", index) and depth > 0:
            depth -= 1
            buffer.append("}}")
            index += 2
            continue
        if text.startswith("[[", index):
            depth += 1
            buffer.append("[[")
            index += 2
            continue
        if text.startswith("]]", index) and depth > 0:
            depth -= 1
            buffer.append("]]")
            index += 2
            continue
        ref_open = _REF_OPEN.match(text, index)
        if ref_open is not None:
            ref_close = _REF_CLOSE.search(text, ref_open.end())
            end = ref_close.end() if ref_close is not None else length
            buffer.append(text[index:end])
            index = end
            continue
        character = text[index]
        if character == separator and depth == 0:
            parts.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(character)
        index += 1
    parts.append("".join(buffer))
    return parts


def split_template(body: str) -> ParsedTemplate:
    """Return the name, positional arguments, and named arguments of one template call.

    `body` may carry the outer `{{` `}}` or not; either is accepted, so a
    caller can pass a `FoundTemplate.text` straight through. Splits on `|` at
    depth 0 -- Creeper's `damage` field holds nine `{{hp|...}}` calls, and a
    plain `str.split("|")` over any one of their bodies would shred a named
    argument like `{{hp|5|withered=1}}` into three unrelated fields instead of
    one value and one flag.

    A named argument is told from a positional one by its key: `id=Raw Beef`
    (Wolf's meat drop) and `withered=1` both start with a bare identifier
    followed by `=`, so they are named. A positional argument that happens to
    contain `=` without that shape -- none appear in the sample -- stays
    positional, because guessing it apart would risk splitting real content.

    **An HTML comment is removed before the split, and that is a correctness
    guard rather than tidying.** A comment can hold a `|`, and MediaWiki strips
    comments before it expands a template, so a pipe inside one never begins an
    argument. The live Evoker page is the proof: it carries

        | size = ... Width: 0.6 blocks
        <!-- | speed = 0.5 -->
        | spawn = ...

    which is a page whose `speed` field has been commented out and therefore
    does not exist. Splitting before the removal invents it, with the value
    `0.5 -->`. Worse, the invented argument is a real argument as far as the
    caller is concerned, so a commented-out field silently overrides the live
    one above it: a page carrying `| health = {{hp|20}}` and a stale
    `<!-- | health = {{hp|999}} -->` below it answers 999. That is a wrong
    number reaching the screen from text an editor had already deleted, which
    is the exact failure non-negotiable 1 of this project exists to prevent.

    An unterminated `<!--` is removed to the end of the text, which is what
    MediaWiki does with one, so a half-written comment cannot leak pipes either.
    """
    text = body.strip()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[2:-2]
    text = _UNCLOSED_COMMENT.sub("", _COMMENT.sub("", text))
    parts = _split_at_depth(text, "|")
    name = parts[0].strip()
    positional: list[str] = []
    named: dict[str, str] = {}
    for part in parts[1:]:
        match = _NAMED_ARG.match(part.strip())
        if match is not None:
            named[match.group(1)] = match.group(2).strip()
        else:
            positional.append(part.strip())
    return ParsedTemplate(name=name, positional=tuple(positional), named=named)


def split_lines(text: str) -> tuple[str, ...]:
    """Split `text` into its display lines.

    Splits on `<br>`, `<br/>`, `<br />`, a newline, and a leading `*` (a list
    marker -- `usableitems` fields mix `<br>`, newline, and `* ` separators in
    the same field, all three seen in the sample). Also splits on `<hr>` and
    its variants, which is not one of the separators a caller might expect from
    the name alone: the module docstring explains why `scope_editions` needs
    `<hr>` to survive as its own line rather than being swallowed like a `<br>`
    is. Blank lines are dropped; nothing downstream wants an empty one.

    HTML comments and `<ref>` blocks are removed first, before any splitting
    happens, because either one can hold its own `<br>` or newline. Cat's
    `speed` field is exactly this trap: `0.3<!--Walking: 0.24<br>Sprinting:
    0.399-->` holds a `<br>` inside the comment, and splitting on it before the
    comment is gone would cut the comment in half -- `0.3<!--Walking: 0.24` and
    `Sprinting: 0.399-->` -- leaving an opened-but-never-closed comment marker
    on the first half that nothing downstream would then remove.
    """
    without_comments = _strip_comments_and_refs(text)
    normalized = _BR.sub("\n", without_comments)
    normalized = _HR.sub(f"\n{HORIZONTAL_RULE}\n", normalized)
    lines: list[str] = []
    for raw in normalized.split("\n"):
        line = raw.strip()
        if line.startswith("*") and line != HORIZONTAL_RULE:
            line = line[1:].strip()
        if line:
            lines.append(line)
    return tuple(lines)


def strip_markup(text: str) -> str:
    """Return `text` with wiki and HTML markup removed, as plain display text.

    Removes HTML comments and `<ref>...</ref>` blocks entirely (Cat's `speed`
    field hides two of its three numbers in a comment; Wolf's `behavior` field
    holds a `<ref>` citation -- both must be gone before anything reads the
    text as a value). Removes `[[File:...]]` embeds outright, since an image is
    not text. Removes the `<small>` and `</small>` tags but keeps their
    content, because `<small>(baby only)</small>` is a note a caller wants, not
    markup to discard. Resolves `[[Page|label]]` to `label` and a bare
    `[[Page]]` to `Page`. Strips any other HTML tag and the `'''`/`''` wiki
    markers. Unescapes HTML entities through `clean_text` rather than a second
    unescaper -- see `pipeline.enrich` for why one unescaper is the rule.
    Collapses whitespace last, so every removal above can leave a gap without
    leaving double spaces in the result.

    Templates are left alone. A `{{ItemLink|Bow}}` or `{{EntityLink|Monster}}`
    is not markup to this function; `find_template` and `split_template` read
    those, and a caller that wants a template's own argument resolved reads it
    before or after calling this, not by asking `strip_markup` to guess.
    """
    cleaned = _COMMENT.sub("", text)
    cleaned = _REF_BLOCK.sub("", cleaned)
    cleaned = _REF_SELF_CLOSING.sub("", cleaned)
    cleaned = _FILE_LINK.sub("", cleaned)
    cleaned = _SMALL_TAG.sub("", cleaned)
    cleaned = _PIPED_LINK.sub(lambda match: match.group(2), cleaned)
    cleaned = _BARE_LINK.sub(lambda match: match.group(1), cleaned)
    cleaned = _GENERIC_TAG.sub("", cleaned)
    cleaned = cleaned.replace("'''", "").replace("''", "")
    cleaned = clean_text(cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def _strip_comments_and_refs(line: str) -> str:
    """Return `line` with HTML comments and `<ref>` blocks removed.

    A narrower pass than `strip_markup`: `classify_heading` needs comments and
    refs gone before it can tell whether a line is heading-shaped at all --
    Phantom's `'''{{IN|Bedrock}}<ref>{{bug|...}}</ref>:'''` would otherwise
    look like it ends inside a citation rather than at the bold close -- but it
    must not yet touch the bold markers or templates that the classifier still
    needs to read.
    """
    cleaned = _COMMENT.sub("", line)
    cleaned = _REF_BLOCK.sub("", cleaned)
    return _REF_SELF_CLOSING.sub("", cleaned)


# A template name that never carries a value. Stray, Bogged, and Piglin all
# write their Bedrock damage heading as `'''{{IN|Bedrock}}:''' {{needs
# testing}}` -- a space, not a glue, sits between the heading and the
# placeholder, unlike the marker suffixes `_strip_trailing_templates` otherwise
# requires to be glued. It is named explicitly here, rather than folded into
# the glue rule generally, because a general "strip any spaced trailing
# template" rule is what let `Easy and Normal: {{hp|0.5}}` (Hoglin) misread as
# a heading in the first place -- see that function's docstring.
_PLACEHOLDER_TEMPLATE_NAMES = frozenset({"needs testing"})


_TRAILING_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*\Z")


def _heading_core(text: str) -> tuple[str, tuple[str, ...]] | None:
    """Return `(core, stripped)` for a heading-shaped `text`, or `None`.

    `core` is `text` with a trailing parenthetical aside dropped -- Warden's
    `'''Ranged:''' (ignores [[armor]] and [[Protection]])` would otherwise
    never look heading-shaped at all, since the line ends at the closing paren
    of an explanation rather than at the colon -- and with any template(s)
    glued onto the very end removed, repeatedly. "Glued" means no whitespace
    sits between the template and what precedes it: `'''While
    jumping:'''{{only|java|short=1}}` (Goat) glues its marker straight onto
    the bold close, and stripping it is what lets the colon just inside that
    close become visible. A known placeholder template
    (`_PLACEHOLDER_TEMPLATE_NAMES`) is stripped even when a space precedes it,
    because it is never a value -- Stray, Bogged, and Piglin all write
    `'''{{IN|Bedrock}}:''' {{needs testing}}`.

    `stripped` holds the verbatim text of every template `core` lost this way,
    in the order they were removed, so `classify_heading` can still read an
    edition signal out of a glued marker suffix even though the template
    itself is no longer part of `core`.

    Returns `None` when the reduction does not end in a colon at all, which is
    what tells a heading from an ordinary content line. `Easy: {{hp|5}}` is
    the case this guards: a space separates the label from its trailing
    template, so nothing is stripped, and `Easy: {{hp|5}}` does not end in a
    colon. Stripping it anyway -- treating any spaced trailing template the
    way a glued one is treated -- is exactly the mistake that would let
    `Easy and Normal: {{hp|0.5}}` (Hoglin's baby damage) misread as a heading,
    clear whatever block scope was active, and let a Bedrock number default to
    kept.
    """
    core = _TRAILING_PARENTHETICAL.sub("", text)
    stripped: list[str] = []
    while True:
        spans = _top_level_template_spans(core)
        if not spans or spans[-1][1] != len(core):
            break
        start, end = spans[-1]
        glued = start == 0 or not core[start - 1].isspace()
        name = core[start + 2 : end - 2].split("|", 1)[0].strip().casefold()
        if not glued and name not in _PLACEHOLDER_TEMPLATE_NAMES:
            break
        stripped.append(core[start:end])
        core = core[:start].rstrip()
    if core.endswith("'''"):
        core = core[:-3].rstrip()
    if not core.endswith(":"):
        return None
    return core, tuple(stripped)


def _heading_shape(text: str) -> bool:
    """Return whether `text` (comments and refs already stripped) is heading-shaped.

    See `_heading_core` for what "heading-shaped" means and why. This is the
    boolean half of it, for a caller that does not need the reduced text.
    """
    return _heading_core(text) is not None


def _edition_of_template(span_text: str) -> Edition | None:
    """Return the edition `span_text` (one `{{...}}` call) names, or `None`.

    Recognizes `{{JE}}` and `{{BE}}` bare, `{{IN|<edition>}}` with the edition
    as the template's own argument, and `{{only|<editions...>}}` with one or
    more edition names among its positional arguments (the named `short=`
    argument is never one of them, because `split_template` already separates
    it out). `{{only|be|ee|short=1}}` folds Education Edition into `BEDROCK`
    -- see `Edition`'s docstring for why.
    """
    parsed = split_template(span_text)
    name = parsed.name.casefold()
    if name == "je":
        return Edition.JAVA
    if name == "be":
        return Edition.BEDROCK
    if name == "in":
        if not parsed.positional:
            return None
        token = parsed.positional[-1].strip().casefold()
        if token in _JAVA_TOKENS:
            return Edition.JAVA
        if token in _BEDROCK_TOKENS:
            return Edition.BEDROCK
        return None
    if name == "only":
        tokens = {argument.strip().casefold() for argument in parsed.positional}
        if tokens & _JAVA_TOKENS:
            return Edition.JAVA
        if tokens & _BEDROCK_TOKENS:
            return Edition.BEDROCK
        return None
    return None


def _is_difficulty_label(label: str) -> bool:
    """Return whether `label` reduces entirely to difficulty words.

    `Easy`, `Easy and Normal`, and `Easy, Normal, and Hard` all qualify. See
    the module docstring's Hoglin example for why this line must not be read
    as a heading that can change the edition scope.
    """
    tokens = [token.strip(",").casefold() for token in label.split() if token.strip(",")]
    if not tokens:
        return False
    return all(token in DIFFICULTY_WORDS or token in _DIFFICULTY_FILLER for token in tokens)


def classify_heading(line: str) -> HeadingClassification:
    """Classify one line as an edition heading, a plain heading, or neither.

    See the module docstring for the region-versus-block rule this implements,
    and for why a difficulty label such as `Easy:` is read as `NOT_A_HEADING`
    rather than as an unmarked heading that would clear a block scope.

    The classification removes every edition template found anywhere in the
    line (there is at most one in every line the sample carries; a line naming
    two different editions at once is `UNPARSEABLE` rather than a guess about
    which one wins), strips the remaining markup, strips a trailing colon, and
    drops the connecting words. What is left, if anything, is the label.

    A template `_heading_core` already stripped -- a glued marker suffix, or a
    placeholder like `{{needs testing}}` -- is checked for an edition signal
    too, even though it is gone from the text this function goes on to build
    the label from. Skipping that check is the bug this function used to
    carry: `'''{{IN|Bedrock}}:''' {{needs testing}}` (Stray, Bogged, Piglin)
    would strip `{{needs testing}}` for shape purposes and then never notice
    that `{{IN|Bedrock}}` was the only template left to search, because the
    search ran over the original, unreduced text instead.
    """
    text = _strip_comments_and_refs(line).strip()
    reduced = _heading_core(text) if text else None
    if reduced is None:
        return HeadingClassification(kind=HeadingKind.NOT_A_HEADING, edition=None, label="")
    core, already_stripped = reduced

    editions_found: set[Edition] = {
        edition
        for template_text in already_stripped
        if (edition := _edition_of_template(template_text)) is not None
    }
    remainder = core
    for start, end in reversed(_top_level_template_spans(core)):
        edition = _edition_of_template(core[start:end])
        if edition is not None:
            editions_found.add(edition)
            remainder = remainder[:start] + remainder[end:]

    cleaned = strip_markup(remainder)
    if cleaned.endswith(":"):
        cleaned = cleaned[:-1].strip()
    words = [word for word in cleaned.split() if word.casefold() not in CONNECTING_WORDS]
    label = " ".join(words)

    if len(editions_found) > 1:
        return HeadingClassification(kind=HeadingKind.UNPARSEABLE, edition=None, label=label)
    edition = next(iter(editions_found), None)

    # The Bogged page writes a heading with no template at all: `'''Bedrock:'''`.
    # Every other form in the module docstring's table names its edition
    # through a template, so this is the one place a bare word has to be read
    # as a marker. Narrow on purpose -- only when the whole label reduces to
    # exactly this one word -- so a heading that merely mentions "Java" or
    # "Bedrock" alongside a real variant name is not misread as a region.
    if edition is None and len(words) == 1 and words[0].casefold() in ("java", "bedrock"):
        edition = Edition.JAVA if words[0].casefold() == "java" else Edition.BEDROCK
        return HeadingClassification(kind=HeadingKind.REGION, edition=edition, label="")

    if edition is None:
        if not label or _is_difficulty_label(label):
            return HeadingClassification(kind=HeadingKind.NOT_A_HEADING, edition=None, label="")
        return HeadingClassification(kind=HeadingKind.UNMARKED, edition=None, label=label)

    if not label:
        return HeadingClassification(kind=HeadingKind.REGION, edition=edition, label="")
    return HeadingClassification(kind=HeadingKind.BLOCK, edition=edition, label=label)


def _inline_edition_marker(line: str) -> Edition | None:
    """Return the edition an inline suffix marks on `line` alone, or `None`.

    This is the "inline suffix" marker form of the module docstring's table:
    `{{only|be|ee|short=1}}` glued onto the end of an ordinary content line,
    such as Sheep's `{{drop|item|Bone Meal}}{{only|be|ee|short=1}}` or a
    knockback-resistance line like `75%{{only|bedrock|short=1}}`. Neither line
    is heading-shaped -- there is no colon to close a label on -- so
    `classify_heading` never sees them, and this is the second, independent
    place an edition marker can appear. `None` when the line names no edition
    or names more than one; a line that contradicts itself is not a marker this
    function will guess about.
    """
    text = _strip_comments_and_refs(line)
    editions = {
        edition
        for start, end in _top_level_template_spans(text)
        if (edition := _edition_of_template(text[start:end])) is not None
    }
    return next(iter(editions)) if len(editions) == 1 else None


def strip_edition_markers(text: str) -> str:
    """Return `text` with every edition-marking template removed.

    A kept line can still carry the very template that marked its scope --
    Zombie's `health` field keeps its trailing `{{only|JE|short=1}}` even once
    `scope_editions` has already read it, in `{{hp|40}} to {{hp|100}}
    (leaders){{only|JE|short=1}}`. A caller reading that line's own display
    text afterwards -- a trailing `(label)`, a leading `Label:` prefix -- needs
    the marker gone first, or it sits exactly where the caller expects the
    line to end. `scope_editions` itself does not need this function: it reads
    the template in place rather than the text around it.
    """
    remainder = text
    for start, end in reversed(_top_level_template_spans(text)):
        if _edition_of_template(text[start:end]) is not None:
            remainder = remainder[:start] + remainder[end:]
    return remainder


def scope_editions(lines: Sequence[str]) -> tuple[LineScope, ...]:
    """Return the edition verdict of every line of `lines`, in order.

    One entry per input line, so a caller can zip this against `lines` (or
    against whatever per-line label bookkeeping it keeps of its own) without
    losing alignment. `edition` is `None` for a line nothing marks as Bedrock
    -- the ordinary case for the large majority of fields, which carry no
    edition markers at all -- and `Edition.BEDROCK` for a line a caller should
    drop. `reached` says why, so a caller can report the filtering rather than
    only apply it silently.

    Implements the region-versus-block rule of the module docstring as a
    two-slot state machine: `region` is set only by a standalone edition
    heading and cleared only by another one or by `<hr>`; `block` is set by an
    embedded edition marker and cleared by *any* subsequent heading, marked or
    not, because a block's whole point is that it lasts until the next
    heading. The effective edition of a line is `block` if one is active, else
    `region`, else unmarked.
    """
    region: Edition | None = None
    block: Edition | None = None
    results: list[LineScope] = []
    for line in lines:
        if line == HORIZONTAL_RULE:
            region = None
            block = None
            results.append(LineScope(line=line, edition=None, reached=REACHED_DEFAULT))
            continue

        classification = classify_heading(line)

        if classification.kind is HeadingKind.REGION:
            region = classification.edition
            block = None
            results.append(
                LineScope(line=line, edition=classification.edition, reached=REACHED_OWN_MARKER)
            )
            continue

        if classification.kind is HeadingKind.BLOCK:
            block = classification.edition
            results.append(
                LineScope(line=line, edition=classification.edition, reached=REACHED_OWN_MARKER)
            )
            continue

        if classification.kind is HeadingKind.UNPARSEABLE:
            results.append(LineScope(line=line, edition=None, reached=REACHED_UNPARSEABLE))
            continue

        if classification.kind is HeadingKind.UNMARKED:
            # A heading with no marker of its own always clears a block scope
            # -- that is the reset Zombie's `Baby` needs -- but it leaves a
            # region alone, which is what keeps Creeper's `Regular`/`Charged`
            # subheadings from clearing the Bedrock region they sit in.
            block = None
        elif classification.kind is HeadingKind.NOT_A_HEADING:
            # An ordinary line can still carry its own inline suffix, scoped to
            # itself alone and independent of the region/block state -- Sheep's
            # four Bedrock-only dye drops are exactly this shape, and none of
            # them are heading-shaped at all.
            inline_edition = _inline_edition_marker(line)
            if inline_edition is not None:
                results.append(
                    LineScope(line=line, edition=inline_edition, reached=REACHED_OWN_MARKER)
                )
                continue

        effective = block if block is not None else region
        if effective is None:
            reached = REACHED_DEFAULT
        elif block is not None:
            reached = REACHED_INHERITED_BLOCK
        else:
            reached = REACHED_INHERITED_REGION
        results.append(LineScope(line=line, edition=effective, reached=reached))
    return tuple(results)
