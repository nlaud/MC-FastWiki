"""Rebuild the wiki infobox wikitext snapshot that pins the infobox parser.

A person runs this module by hand. It is not a test, and pytest does not
collect it, because the name does not start with `test_`. It follows the
precedent of `tests/fixtures/build_bucket_row_snapshot.py`, which does the
same job for the Bucket side of Tier B.

`tests/test_infobox_snapshot.py` reads the file this writes.
`tests/test_enrich_infobox.py` builds its infobox text in memory, one trap per
test, so a parser that is wrong about a real page still passes it. This
snapshot is the only test that reads what the wiki actually sent.

Run it from the repository root:

    python -m tests.fixtures.build_infobox_snapshot

The module opens the network. It reads through `pipeline.fetch.wikitext`, so
it takes the path a build takes, obeys the shared `WIKI_TRANSPORT` rate limit,
and writes the same content cache the rest of the pipeline uses.

**The subset is chosen, not sampled.** `TITLES` below names eighteen pages,
one per trap the implementation brief's live survey found -- the twelve
region page-fields and eleven block page-fields overlap on several titles, so
eighteen pages cover both lists in full, plus the long-tail shapes (a range,
a combined difficulty tier, a same-line label, a prose refusal) that section 3
of the brief records. Fetching every mob page would make a fixture too large
to review and would still not guarantee any one trap stayed in it.

**There is no version to pin to.** mcmeta publishes a tag per Minecraft
release; the wiki is edited continuously. So the header carries the date the
page source was captured, and `tests/test_infobox_snapshot.py` checks facts a
person can verify against the game rather than byte-equality with a live
re-fetch. When an assertion in that test starts to fail, the question to ask
is whether the wiki changed or the parser did.

To refresh it: run the module, read the diff, and check that any changed
number is a wiki edit you agree with before committing it.
"""

import datetime
import json
from pathlib import Path

from pipeline.enrich.infobox import INFOBOX_TEMPLATE_NAME
from pipeline.enrich.markup import find_template
from pipeline.fetch.wikitext import fetch_page_wikitext

FIXTURE = Path(__file__).resolve().parent / "wiki_infobox_pages.json"

# The cache generation this module reads under. A date, not a Minecraft
# version, for the same reason `tests/fixtures/build_bucket_row_snapshot.py`
# uses one: the wiki has no version.
REVISION = datetime.date.today().isoformat()

# One title per trap. Every comment names the shape it pins; several pages
# cover more than one.
TITLES: tuple[str, ...] = (
    # The region rule (12 page-fields that must not leak): Creeper's damage
    # is the canonical case -- a standalone `{{IN|BE}}:` region nesting
    # `Regular`/`Charged` subheadings that must not clear it.
    "Creeper",
    # Skeleton damage carries the `{{Needs testing}}` placeholder glued onto
    # its Bedrock region heading, and its size is a second region case.
    "Skeleton",
    # Cow's size is a region opened by `'''In {{JE}}:'''`, which reduces to
    # nothing only once the connecting word `in` is dropped.
    "Cow",
    # Magma Cube pins the region rule for size, and labelled Large/Medium/
    # Small variants for health, damage, size, and armor all at once.
    "Magma Cube",
    # Bogged's size and damage use a plain-text `'''Bedrock:'''` heading with
    # no template at all -- the one marker form that is not a template.
    "Bogged",
    # The block rule (11 page-fields that must keep the reset): Zombie's size
    # is the canonical case -- the unmarked `'''Baby:'''` heading must clear
    # the embedded `{{IN|Bedrock}}` block that precedes it.
    "Zombie",
    # Chicken's size uses `'''Adult in {{JE}}:'''`, the connecting-word block
    # form, alongside the same unmarked `Baby` reset.
    "Chicken",
    # Goat's size carries a heading with a glued `{{only|java|short=1}}`
    # suffix, `'''While jumping:'''{{only|java|short=1}}`.
    "Goat",
    # Warden's size carries an embedded marker before the colon,
    # `'''While digging/emerging{{only|JE|short=1}}:'''`, and its damage
    # field has a heading with a trailing parenthetical aside.
    "Warden",
    # Iron Golem's health uses same-line, non-bold labels
    # (`Uncracked: {{hp|100}}`), and its damage is an en dash range.
    "Iron Golem",
    # Sheep's usable items carry four Bedrock-only dyes marked with a
    # trailing `{{only|be|ee|short=1}}` inline suffix on an ordinary line.
    "Sheep",
    # Wolf's health is same-line bold labels (`'''Wild:'''`/`'''Tamed:'''`),
    # and its usable items carry an `id=` override.
    "Wolf",
    # Ocelot mixes a `{{drop|...}}` call with a different template,
    # `{{ItemLink|Raw Salmon}}`, in the same field.
    "Ocelot",
    # Frog's damage is prose with no `{{hp}}` template at all -- the
    # refusal case that must go to the unparsed report, not a guess.
    "Frog",
    # Phantom's damage is a bold, non-template `'''Height:'''`/`'''Width:'''`
    # pair for size, and its damage carries a `<ref>` inside an edition
    # heading.
    "Phantom",
    # Happy Ghast's size is the combined `Height and width:` form.
    "Happy Ghast",
    # Shulker documents a second `{{Infobox entity}}` further down its own
    # page (`Shulker Bullet`), and its size carries three variant labels
    # (Closed/Peeking/Open).
    "Shulker",
    # Cat's health is two full edition regions separated by `<hr>` with no
    # `<br>` beside it, and its speed hides two numbers inside an HTML
    # comment that itself contains a `<br>`.
    "Cat",
)


def write_fixture(path: Path, document: dict[str, object]) -> None:
    """Write the fixture, indented, with a final newline and LF endings."""
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def trimmed_infobox_text(page_title: str, page_text: str) -> str:
    """Return just the `{{Infobox entity}}` template(s) of `page_text`, joined.

    A mob page's full source runs 20-100 KB and `parse_infobox` reads none of
    it beyond the infobox template -- the rest is Obtaining, History, and
    Trivia sections no test here needs. Trimming to the template(s) keeps the
    fixture reviewable the way `tests/fixtures/wiki_bucket_rows.json` is,
    without losing anything `parse_infobox` would read.

    Every match is kept, joined by a blank line, rather than only the first.
    Shulker carries two `{{Infobox entity}}` templates on its own page -- the
    second documents `Shulker Bullet` -- and that is one of the traps this
    fixture exists to pin: `parse_infobox` must read the first and ignore the
    rest.
    """
    found = find_template(page_text, INFOBOX_TEMPLATE_NAME)
    if not found:
        raise ValueError(f"{page_title!r} answered no {{{{{INFOBOX_TEMPLATE_NAME}}}}} template.")
    return "\n\n".join(item.text for item in found)


def main() -> None:
    """Fetch every title and write the snapshot."""
    report = fetch_page_wikitext(TITLES, revision=REVISION)
    full_pages = {entry.requested_title: entry.content for entry in report.pages}
    pages = {
        title: trimmed_infobox_text(title, text) for title, text in full_pages.items()
    }
    for title in TITLES:
        if title not in pages:
            miss = next(m for m in report.misses if m.requested_title == title)
            print(f"MISS {title}: {miss.reason}")
        else:
            print(f"{title}: {len(full_pages[title])} bytes -> {len(pages[title])} trimmed")
    write_fixture(
        FIXTURE,
        {
            "captured": REVISION,
            "note": (
                "Chosen mob pages, trimmed to their {{Infobox entity}} template(s), one "
                "page per trap the infobox parser has to survive. Rebuilt by "
                "tests/fixtures/build_infobox_snapshot.py. Content is CC BY-NC-SA 3.0."
            ),
            "titles": list(TITLES),
            "pages": pages,
            "misses": [
                {"requested_title": m.requested_title, "reason": m.reason}
                for m in report.misses
            ],
        },
    )
    print(f"{FIXTURE.name}: {len(pages)} pages, {len(report.misses)} misses")


if __name__ == "__main__":
    main()
