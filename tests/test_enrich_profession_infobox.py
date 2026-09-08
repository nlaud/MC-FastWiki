"""Tests for `pipeline.enrich.profession_infobox`."""

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.profession_infobox import (
    parse_profession_infobox,
    parse_profession_infoboxes,
)


def test_parse_profession_infobox_extracts_workstation() -> None:
    """A standard infobox with a workstation block parses cleanly."""
    wikitext = """
    {{Infobox profession
    | group1 = Plains
    | 1-1 = Plains Librarian.png
    | workstation = Lectern
    | buys = * {{ItemLink|Paper}}
    }}
    """
    box = parse_profession_infobox("Librarian", wikitext)
    assert box.page == "Librarian"
    assert box.workstation == "Lectern"


def test_parse_profession_infobox_with_linked_workstation() -> None:
    """A workstation wrapped in wiki link markup strips to plain block name."""
    wikitext = """
    {{Infobox profession
    | workstation = [[Blast Furnace]]
    }}
    """
    box = parse_profession_infobox("Armorer", wikitext)
    assert box.workstation == "Blast Furnace"


def test_parse_profession_infobox_defensive_none_guard() -> None:
    """The workstation = None guard treats 'None' as absence rather than a block named 'None'.

    Excluding the nitwit removes the only page whose infobox reads workstation = None.
    The parser still has to treat that value as absence rather than as a block named 'None',
    and this test pins it, but it now guards a defensive case no page in the active build reaches.
    """
    wikitext = """
    {{Infobox profession
    | group1 = Plains
    | 1-1 = Plains Nitwit.png
    | workstation = None
    }}
    """
    box = parse_profession_infobox("Nitwit", wikitext)
    assert box.page == "Nitwit"
    assert box.workstation is None


def test_parse_profession_infobox_missing_template_raises() -> None:
    """A page with no {{Infobox profession}} raises EnrichError."""
    wikitext = "This page is about villagers but has no infobox."
    with pytest.raises(EnrichError, match=r"carries no \{\{Infobox profession\}\} template"):
        parse_profession_infobox("Unknown", wikitext)


def test_parse_profession_infoboxes_batch() -> None:
    """parse_profession_infoboxes parses a mapping of pages."""
    pages = {
        "Librarian": "{{Infobox profession | workstation = Lectern }}",
        "Armorer": "{{Infobox profession | workstation = Blast Furnace }}",
    }
    boxes = parse_profession_infoboxes(pages)
    assert len(boxes) == 2
    assert boxes["Librarian"].workstation == "Lectern"
    assert boxes["Armorer"].workstation == "Blast Furnace"
