"""Advancements: the page filter, the parent-by-title link, and the Tier A join.

`pipeline.enrich.advancement` reads a bucket where 615 rows describe 126
advancements. The extra 489 are the same advancements written down again on
April Fools' pages and on version pages going back to 2017, with internal IDs
that collide exactly with the live ones. Read without the page filter, whichever
row arrives last wins.

`parse_advancements` is pure, so nothing here opens a socket.
"""

import json
from typing import Any

import pytest

from pipeline.enrich import EnrichError
from pipeline.enrich.advancement import (
    ADVANCEMENT_PAGE,
    AdvancementTree,
    parse_advancements,
    parse_experience,
)

# The wiki's rendered reward HTML, with the sprite class that a careless regex
# would read as the reward.
XP_REWARD = (
    '<span class="animated"><span class="pixel-image animated-active xp-148" '
    'style="background-position:left center"></span></span>100'
    '<span class="hidden-alt-text">XP</span> [[experience]]'
)


def row(
    internal_id: str,
    title: str,
    *,
    parent: str = "—",
    page: str = ADVANCEMENT_PAGE,
    description: str = "Do the thing.",
    game_description: str = "—",
    reward: str = "—",
    image: str = "Grass Block",
) -> dict[str, Any]:
    """Return one `advancement` row, shaped the way the live API sends it."""
    document = {
        "internal_id": internal_id,
        "title": title,
        "parent": parent,
        "wiki_description": description,
        "game_description": game_description,
        "background": "plain",
        "image": image,
        "reward": reward,
    }
    return {"page_name": page, "title": title.lower(), "json": json.dumps(document)}


def test_the_tree_is_keyed_on_the_tier_a_internal_id() -> None:
    """The join to the vanilla data is a dictionary lookup, not a name match."""
    tree = parse_advancements([row("story/root", "Minecraft")])

    assert tree.by_id["story/root"].title == "Minecraft"
    assert tree.by_id["story/root"].tab == "story"


def test_a_row_from_another_page_is_skipped_and_reported() -> None:
    """A 2017 snapshot page carries a `story/root` too, with a stale description.

    This is the filter the whole module turns on. Without it the ID collides and
    the build shows a nine-year-old description without saying so.
    """
    tree = parse_advancements(
        [
            row("story/root", "Minecraft", description="Have a [[crafting table]]."),
            row(
                "story/root",
                "Minecraft",
                page="Java Edition 17w13a",
                description="Descriptions were not added yet.",
            ),
        ]
    )

    assert tree.by_id["story/root"].description == "Have a [[crafting table]]."
    assert "not on Advancement" in tree.skipped[0].reason


def test_a_parent_is_named_by_title_and_resolved_to_an_id() -> None:
    """`story/mine_stone` says its parent is `Minecraft`, not `story/root`."""
    tree = parse_advancements(
        [
            row("story/root", "Minecraft"),
            row("story/mine_stone", "Stone Age", parent="Minecraft"),
        ]
    )

    assert tree.by_id["story/mine_stone"].parent_id == "story/root"
    assert tree.by_id["story/mine_stone"].parent_title == "Minecraft"
    assert tree.roots == ("story/root",)
    assert tree.children["story/root"] == ("story/mine_stone",)


def test_a_parent_title_that_resolves_to_nothing_is_reported_not_dropped() -> None:
    """A broken link on the wiki should be visible, not a reason to lose an advancement."""
    tree = parse_advancements([row("story/mine_stone", "Stone Age", parent="Nowhere")])

    assert tree.by_id["story/mine_stone"].parent_id is None
    assert "is not an advancement on this page" in tree.skipped[0].reason


def test_the_ancestry_runs_from_the_root_down() -> None:
    """The parent chain a renderer shows above an advancement."""
    tree = parse_advancements(
        [
            row("story/root", "Minecraft"),
            row("story/mine_stone", "Stone Age", parent="Minecraft"),
            row("story/upgrade_tools", "Getting an Upgrade", parent="Stone Age"),
        ]
    )

    assert [entry.title for entry in tree.ancestry("story/upgrade_tools")] == [
        "Minecraft",
        "Stone Age",
        "Getting an Upgrade",
    ]


def test_a_parent_cycle_raises_rather_than_hanging() -> None:
    """Nothing upstream forbids a wiki editor from writing one."""
    tree = parse_advancements(
        [
            row("story/a", "A", parent="B"),
            row("story/b", "B", parent="A"),
        ]
    )

    with pytest.raises(EnrichError, match="cycle"):
        tree.ancestry("story/a")


def test_a_duplicate_internal_id_is_refused_by_the_tree() -> None:
    """Every way of reading this bucket wrongly ends in two rows sharing an ID."""
    first, second = row("story/root", "Minecraft"), row("story/root", "Minecraft")
    advancements = parse_advancements([first]).advancements
    parsed = parse_advancements([second]).advancements

    with pytest.raises(EnrichError, match="more than once"):
        AdvancementTree.build([*advancements, *parsed])


def test_the_experience_reward_is_read_out_of_the_html() -> None:
    """The number is buried between a sprite span and a hidden `XP` label.

    The sprite's own class is `xp-148`, so a regex anchored on `xp` rather than
    on the label would report 148 experience for a 100-experience advancement.
    """
    assert parse_experience(XP_REWARD) == 100


def test_a_reward_that_is_not_experience_reads_as_none() -> None:
    """`None` means the reward is not experience, not that it is zero."""
    assert parse_experience("a [[map]]") is None


def test_the_em_dash_the_wiki_writes_for_no_value_is_not_content() -> None:
    """A root has no parent, an undocumented advancement has no description.

    Both arrive as an em dash. Rendered as text they would print as the parent
    and as the instructions.
    """
    tree = parse_advancements([row("nether/find_bastion", "Those Were the Days", description="—")])

    entry = tree.by_id["nether/find_bastion"]
    assert entry.description is None
    assert entry.parent_title is None
    assert entry.is_root
    assert entry.reward is None


def test_a_row_whose_internal_id_is_not_one_is_skipped() -> None:
    """A malformed ID cannot join to anything, so keeping it would be noise."""
    tree = parse_advancements([row("Story Root", "Minecraft")])

    assert tree.advancements == ()
    assert "not an advancement internal ID" in tree.skipped[0].reason


def test_reconciling_reports_both_directions_of_the_join() -> None:
    """The two gaps mean different things, so they are reported separately.

    An ID the game has and the wiki has not is a page that renders without a
    description. An ID the wiki has and the game has not is either a page
    written ahead of a release or a snapshot row that got past the page filter.
    """
    tree = parse_advancements(
        [row("story/root", "Minecraft"), row("story/mine_stone", "Stone Age")]
    )

    report = tree.reconcile(["story/root", "nether/root"])

    assert report.matched == ("story/root",)
    assert report.missing_from_wiki == ("nether/root",)
    assert report.missing_from_tier_a == ("story/mine_stone",)
