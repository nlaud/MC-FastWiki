"""Parse `{{Infobox profession}}` for workstation block.

`{{Infobox profession}}` carries the `workstation` field on all 13 profession pages.
Excluding the nitwit removes the only page whose infobox reads `workstation = None`.
The parser defensively treats that value as absence (None) rather than as a block
named "None", guarding a case no page in the current build reaches.
"""

from collections.abc import Mapping

from pydantic import BaseModel

from pipeline.enrich import EnrichError
from pipeline.enrich.markup import find_template, split_template, strip_markup

__all__ = [
    "INFOBOX_PROFESSION_TEMPLATE",
    "ProfessionInfobox",
    "parse_profession_infobox",
    "parse_profession_infoboxes",
]

INFOBOX_PROFESSION_TEMPLATE = "Infobox profession"


class ProfessionInfobox(BaseModel, frozen=True):
    """The extracted workstation of one profession's `{{Infobox profession}}`."""

    page: str
    workstation: str | None = None


def parse_profession_infobox(page: str, wikitext: str) -> ProfessionInfobox:
    """Parse `{{Infobox profession}}` from `wikitext`, returning `ProfessionInfobox`.

    Raises `EnrichError` if the page carries no `{{Infobox profession}}` template.
    Defensively treats `workstation = None` (or empty) as `None` rather than a block named "None".
    """
    boxes = find_template(wikitext, INFOBOX_PROFESSION_TEMPLATE)
    if not boxes:
        raise EnrichError(f"{page!r} carries no {{{{{INFOBOX_PROFESSION_TEMPLATE}}}}} template.")

    named = split_template(boxes[0].text).named
    raw_workstation = named.get("workstation")
    workstation: str | None = None
    if raw_workstation is not None:
        cleaned = strip_markup(raw_workstation).strip()
        # Defensive guard: "None" indicates absence of a workstation (as on the nitwit page)
        if cleaned and cleaned.casefold() != "none":
            workstation = cleaned

    return ProfessionInfobox(page=page, workstation=workstation)


def parse_profession_infoboxes(
    pages_wikitext: Mapping[str, str],
) -> dict[str, ProfessionInfobox]:
    """Parse all profession infoboxes from a mapping of page title to wikitext."""
    return {
        page: parse_profession_infobox(page, text)
        for page, text in pages_wikitext.items()
    }
