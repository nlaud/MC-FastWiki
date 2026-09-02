"""Parse the wiki's `Brewing` page into base, weakness, and effect ingredient recipes.

Brewing has no data-pack representation at all -- it is hardcoded in
`PotionBrewing.java`, not shipped as JSON the way a recipe or a loot table
is. Probed and rejected against the live wiki Bucket API on 2026-09-01:
`bucket('brewing')`, `bucket('brewing_recipe')`, `bucket('brewing_recipes')`,
`bucket('potion')`, and `bucket('potions')` all answer `"Bucket <name> does
not exist."` So this is the one obtain source that reads Tier B wikitext
directly, through `pipeline.fetch.wikitext.fetch_page_wikitext` and the
shared primitives of `pipeline.enrich.markup` -- reused here rather than
reimplemented, per that module's own reuse note.

**This module answers "what does one ingredient do," not "what is the exact
recipe of potion X."** The `Brewing` page states the same fact twice, in two
different shapes: a single summary table, `=== Effect ingredients ===`
(`Name | Icon | Effect | Effect when corrupted`), and then again, spread
across three long per-potion tables under `=== Effect potions ===`, each row
carrying a `{{Brewing Stand |Input=...}}` template that names the same
ingredient a second time. The summary table is read here because it states
every ingredient's effect *and* its corruption target in one row, with no
per-potion Output1/Output2/Output3 template slots to reconcile against each
other -- verified by cross-checking every row of it against the per-potion
tables' own `{{Brewing Stand}}` templates on 2026-09-01: `Potion of Harming`'s
`Output1=Potion of Healing` and `Output3=Potion of Poison` match this table's
`healing -> harming` and `poison -> harming` corruption entries exactly, and
`Potion of Slowness`'s `Output1=Potion of Swiftness` and
`Output3=Potion of Leaping` match `swiftness -> slowness` and
`leaping -> slowness` the same way. `pipeline.obtain.brewing` (this module's
caller) turns the ingredient-and-corruption facts this module reports into
potion-to-potion recipes mechanically, against the registry's own 46 IDs,
rather than this module hand-building a recipe graph that the registry check
would only have to re-verify anyway.

## The rowspan trap

`Effect when corrupted` uses `rowspan` to cover several rows with one cell:
`rowspan="2"` for Sugar and Rabbit's Foot (both corrupt to Slowness), and
`rowspan="10"` for the run from Ghast Tear through Slime Block (all corrupt
to nothing). A row with no fourth cell of its own inherits the value most
recently declared, for as many rows as that cell's `rowspan` covers minus the
row that declared it. `_parse_effect_ingredients` carries that count forward
explicitly (`_pending_corruption`) rather than assuming every row states its
own value, which would silently read every inherited row as uncorrupted.

## Java Edition only, and the one cell that actually mixes editions

Non-negotiable 1 of CLAUDE.md. Of the sixteen rows this table holds, exactly
one carries a genuinely mixed-edition cell: Blaze Powder's corrupted column
is `None{{only|java|short=1}} <br> [[Weakness]]{{only|bedrock|short=1}}` --
Java corrupts Strength into nothing, Bedrock corrupts it into Weakness. This
module reuses `pipeline.enrich.markup.split_lines` and `.scope_editions`
rather than writing a second edition filter: `split_lines` cuts the cell on
its `<br>`, and `scope_editions` reads each line's own inline `{{only|...}}`
marker exactly the way it already reads Sheep's edition-only dye drops, per
that module's own docstring.

## The name-to-registry-id gap, deliberately left open here

This module reports wiki *names*: an ingredient's display name (`"Sugar"`),
and an effect's display name (`"Speed"`). It does not resolve either to a
registry ID, on purpose. `pipeline.obtain.brewing`'s own docstring explains
why the effect-name-to-potion-id translation belongs one layer up, where the
46-entry registry list actually lives; this module has no registry to check
against and would otherwise have to invent the "Speed is swiftness" mapping
without any way to verify it against the one list that matters.

## Two failure guards

An empty or too-short parse raises `EnrichError` -- this is `TODO.md`'s
Phase 6b rule (an empty scrape is a failure to report, not "brewing has no
recipes"), applied one phase early because brewing genuinely has no other
source to fall back on. The 46-potion coverage assertion against the potion
registry is not this module's job; it lives in
`tests/test_obtain_brewing.py`, against `pipeline.obtain.brewing`'s output,
because only that layer has the registry list to check coverage against.
"""

import re
from collections.abc import Mapping

from pydantic import BaseModel, model_validator

from pipeline.enrich import EnrichError
from pipeline.enrich.markup import (
    Edition,
    find_template,
    scope_editions,
    split_lines,
    split_template,
    strip_edition_markers,
    strip_markup,
)
from pipeline.fetch import Transport
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.wikitext import fetch_page_wikitext

__all__ = [
    "BASE_POTION_HEADERS",
    "DRAGON_BREATH_ITEM",
    "EFFECT_INGREDIENTS_HEADING",
    "GUNPOWDER_ITEM",
    "PAGE_TITLE",
    "SPLASH_LINGERING_HEADING",
    "UNBREWABLE_HEADING",
    "WIKI_NAME_TO_ITEM_ID",
    "BaseRecipe",
    "BrewingIndex",
    "EffectRecipe",
    "fetch_brewing",
    "parse_brewing",
]

PAGE_TITLE = "Brewing"

EFFECT_INGREDIENTS_HEADING = "=== Effect ingredients ==="
BASE_POTIONS_HEADING = "=== Base potions ==="
SPLASH_LINGERING_HEADING = "==== Splash and lingering potions ===="
UNBREWABLE_HEADING = "=== Un-brewable potions ==="

GUNPOWDER_ITEM = "minecraft:gunpowder"
DRAGON_BREATH_ITEM = "minecraft:dragon_breath"

# Every ingredient name the `Brewing` page uses, mapped to its registry item
# ID. Explicit rather than derived, because two of these are irregular and a
# casefold-and-underscore derivation would get them wrong silently: "Redstone
# Dust" is `minecraft:redstone`, not `minecraft:redstone_dust`, and "Turtle
# Shell" is `minecraft:turtle_helmet` -- the wiki keeps the item's older name
# for this table, the game does not.
WIKI_NAME_TO_ITEM_ID: Mapping[str, str] = {
    "Nether Wart": "minecraft:nether_wart",
    "Glowstone Dust": "minecraft:glowstone_dust",
    "Redstone Dust": "minecraft:redstone",
    "Sugar": "minecraft:sugar",
    "Rabbit's Foot": "minecraft:rabbit_foot",
    "Glistering Melon Slice": "minecraft:glistering_melon_slice",
    "Spider Eye": "minecraft:spider_eye",
    "Magma Cream": "minecraft:magma_cream",
    "Blaze Powder": "minecraft:blaze_powder",
    "Ghast Tear": "minecraft:ghast_tear",
    "Breeze Rod": "minecraft:breeze_rod",
    "Stone": "minecraft:stone",
    "Cobweb": "minecraft:cobweb",
    "Slime Block": "minecraft:slime_block",
    "Fermented Spider Eye": "minecraft:fermented_spider_eye",
    "Golden Carrot": "minecraft:golden_carrot",
    "Pufferfish": "minecraft:pufferfish",
    "Turtle Shell": "minecraft:turtle_helmet",
    "Phantom Membrane": "minecraft:phantom_membrane",
    "Gunpowder": GUNPOWDER_ITEM,
    "Dragon's Breath": DRAGON_BREATH_ITEM,
}

# The row header text of the three base potions, mapped to the registry
# potion path each names. Explicit for the same reason as the table above:
# three known values, never derived.
BASE_POTION_HEADERS: Mapping[str, str] = {
    "Awkward potion": "awkward",
    "Mundane potion": "mundane",
    "Thick potion": "thick",
}

# The one ingredient the effect-ingredients table maps directly to a
# *potion*, not an *effect* of the awkward base: adding a fermented spider
# eye straight to a water bottle gives Potion of Weakness, and the page says
# outright that it "is the only potion that can be brewed without nether
# wart." Every other row of the table describes an effect brewed from the
# *awkward* base; this row is the exception, handled as a base-level recipe
# rather than folded into `effect_recipes`.
_WEAKNESS_ROW = "Fermented Spider Eye"

# A row separator line, matched only at the start of its own line so a `|-`
# that happens to appear inside a cell's own content (a negative number, say)
# can never be mistaken for one.
_ROW_SEPARATOR = re.compile(r"(?m)^\|-\s*$")
_ANCHOR_TEMPLATE = re.compile(r"\{\{anchor\|[^}]*\}\}")
_CELL_ATTRS = re.compile(r'^\s*(?P<attrs>(?:[A-Za-z-]+="[^"]*"\s*)+)\|(?P<content>.*)$', re.DOTALL)
_ROWSPAN = re.compile(r'rowspan="(\d+)"')
_UNBREWABLE_LINK = re.compile(
    r"\[\[(?:[^\]|]*\|)?(?P<label>[^\]]+)\]\](?:\{\{only\|(?P<edition>[^}]+)\}\})?"
)
# One wikitext heading line, opening and closing marker held equal by a
# backreference so a level-3 heading (`===`) never matches on a level-4
# closer or vice versa.
_HEADING = re.compile(r"^(?P<level>=+)[^=\n].*?(?P=level)\s*$", re.MULTILINE)


class BaseRecipe(BaseModel, frozen=True):
    """One `water bottle + ingredient -> result` recipe, where `result` names a potion path."""

    ingredient_item: str
    result_path: str


class EffectRecipe(BaseModel, frozen=True):
    """One `awkward potion + ingredient -> effect` recipe.

    `effect_name` is the wiki's own name for the effect (`"Speed"`, `"Slowness
    + Resistance"`), not yet resolved to a potion registry path -- see the
    module docstring's name-to-registry-id section for why that translation
    happens one layer up, in `pipeline.obtain.brewing`.
    """

    ingredient_item: str
    effect_name: str


class BrewingIndex(BaseModel, frozen=True):
    """Every brewing fact the `Brewing` page states, parsed but not yet resolved to potion IDs.

    `corruption_map` is keyed and valued by wiki effect name, read from the
    `Effect when corrupted` column: `swiftness`'s row maps `"Speed"` to
    `"Slowness"`. An effect whose corrupted cell reads `"None"` has no entry
    here at all, rather than an entry mapping to `None` -- see `parse_brewing`
    for where that filtering happens.
    """

    base_recipes: tuple[BaseRecipe, ...]
    weakness_recipe: BaseRecipe
    effect_recipes: tuple[EffectRecipe, ...]
    corruption_map: Mapping[str, str]
    gunpowder_item: str
    dragon_breath_item: str
    unbrewable_names: tuple[str, ...]

    @model_validator(mode="after")
    def _the_parse_is_not_too_short(self) -> "BrewingIndex":
        """Refuse a parse thin enough to be a broken scrape rather than a small table.

        The live table holds sixteen ingredient rows (fifteen effects plus the
        weakness row) and three base potions. A floor well under that, rather
        than an exact count, is what keeps this check from breaking on the
        next ingredient the game adds -- `tests/test_obtain_brewing.py` is
        where the 46-potion coverage is actually pinned, against the registry.
        """
        if len(self.base_recipes) < 3 or len(self.effect_recipes) < 10:
            raise EnrichError(
                f"the Brewing page parsed to {len(self.base_recipes)} base recipes and "
                f"{len(self.effect_recipes)} effect recipes, which is too few to be a real "
                f"parse of that page. An empty or short scrape is a failure to report, not "
                f"a version of the game with fewer brewing recipes."
            )
        return self


def _java_text(raw: str) -> str:
    """Return `raw`'s Java-only text, `<br>`-separated lines dropped or kept per edition.

    Reuses `pipeline.enrich.markup.split_lines` and `.scope_editions` rather
    than writing a second edition filter -- see the module docstring's
    edition section.
    """
    lines = split_lines(raw)
    scopes = scope_editions(lines)
    kept = [scope.line for scope in scopes if scope.edition in (None, Edition.JAVA)]
    # `scope_editions` reads the marker in place; it does not remove it. A
    # kept line still carries its own `{{only|java|short=1}}` suffix, and
    # `strip_markup` leaves templates alone on purpose (its own docstring is
    # explicit about that), so the marker has to come off separately, before
    # the line is otherwise cleaned -- see `pipeline.enrich.markup.strip_
    # edition_markers`'s own docstring for the same two-step order.
    cleaned = [strip_markup(strip_edition_markers(line)) for line in kept]
    return "; ".join(part for part in cleaned if part)


def _section(text: str, heading: str, *, source: str) -> str:
    """Return the text between `heading` and the next heading of the same or higher level.

    "Higher level" means fewer `=` characters: a `===` (level 3) section ends
    at the next `==` (level 2) or `===` heading, but a `====` (level 4)
    subheading nested inside it does not end it.
    """
    start = text.find(heading)
    if start == -1:
        raise EnrichError(f"{source} carries no {heading!r} section.")
    body_start = start + len(heading)
    level = len(heading) - len(heading.lstrip("="))
    for match in _HEADING.finditer(text, body_start):
        if len(match.group("level")) <= level:
            return text[body_start : match.start()]
    return text[body_start:]


def _table_body(section_text: str, *, source: str) -> str:
    """Return the wikitext between the first `{|` and its matching `|}` of `section_text`."""
    start = section_text.find("{|")
    if start == -1:
        raise EnrichError(f"{source} carries no table.")
    end = section_text.find("|}", start)
    if end == -1:
        raise EnrichError(f"{source} carries an unterminated table.")
    return section_text[start:end]


def _row_blocks(table_text: str) -> list[str]:
    """Split a table's wikitext into row blocks, dropping the preamble and header row.

    The preamble (the `{| ...` opener and `|+Caption` line, before the first
    `|-`) is dropped by testing for `{|` directly rather than by position,
    so an empty or whitespace-only preamble never shifts every later index
    and silently drops the first real row instead.
    """
    parts = _ROW_SEPARATOR.split(table_text)
    return [
        part
        for part in parts
        if part.strip() and not part.strip().startswith("! Name") and "{|" not in part
    ]


def _cell_lines(block: str) -> list[str]:
    """Return the `!`/`|`-prefixed cell lines of one row block, each with its marker stripped."""
    lines = []
    for raw_line in block.split("\n"):
        line = raw_line.strip()
        if line.startswith("!") or line.startswith("|"):
            lines.append(line[1:].strip())
    return lines


def _cell_content(cell: str) -> tuple[str, int]:
    """Return `(content, rowspan)` of one cell, splitting off a leading `rowspan="N"` attribute."""
    match = _CELL_ATTRS.match(cell)
    if match is None:
        return cell, 1
    rowspan_match = _ROWSPAN.search(match.group("attrs"))
    rowspan = int(rowspan_match.group(1)) if rowspan_match else 1
    return match.group("content"), rowspan


def _row_name(cell: str) -> str:
    """Return the ingredient name of a `Name` cell, such as `!{{anchor|Sugar}}[[Sugar]]`."""
    return strip_markup(_ANCHOR_TEMPLATE.sub("", cell))


def _parse_effect_ingredients(
    text: str, *, source: str
) -> tuple[tuple[EffectRecipe, ...], BaseRecipe | None, dict[str, str]]:
    """Return the effect recipes, the weakness base recipe, and the corruption map.

    Walks the `Effect ingredients` table row by row, carrying the corrupted
    column's `rowspan` forward across rows that declare no cell of their own
    -- see the module docstring's rowspan section.
    """
    table = _table_body(text, source=source)
    effect_recipes: list[EffectRecipe] = []
    weakness_recipe: BaseRecipe | None = None
    corruption_map: dict[str, str] = {}

    pending_corrupted: str | None = None
    pending_remaining = 0

    for block in _row_blocks(table):
        cells = _cell_lines(block)
        if not cells:
            continue
        ingredient = _row_name(cells[0])
        if len(cells) < 3:
            raise EnrichError(f"{source} carries an ingredient row with fewer than 3 cells.")
        effect_name = strip_markup(cells[2])

        if len(cells) >= 4:
            content, rowspan = _cell_content(cells[3])
            corrupted = _java_text(content)
            pending_corrupted = corrupted
            pending_remaining = rowspan - 1
        else:
            if pending_remaining <= 0:
                raise EnrichError(
                    f"{source} carries the row {ingredient!r} with no corrupted-column cell "
                    f"and no rowspan left to inherit one from."
                )
            corrupted = pending_corrupted or ""
            pending_remaining -= 1

        if corrupted and corrupted.casefold() != "none":
            corruption_map[effect_name] = corrupted

        item_id = WIKI_NAME_TO_ITEM_ID.get(ingredient)
        if item_id is None:
            raise EnrichError(f"{source} names the ingredient {ingredient!r}, which is unknown.")

        if ingredient == _WEAKNESS_ROW:
            weakness_recipe = BaseRecipe(ingredient_item=item_id, result_path="weakness")
        else:
            effect_recipes.append(EffectRecipe(ingredient_item=item_id, effect_name=effect_name))

    return tuple(effect_recipes), weakness_recipe, corruption_map


_HEADER_CELL = re.compile(r"^!\s*(?P<content>.*)$", re.MULTILINE)


def _row_header(block: str) -> str | None:
    """Return the display text of one row's `!`-marked header cell, or `None`.

    Reads the header cell as a whole rather than through `_cell_lines`,
    because a row of the `Base potions` table carries a multi-line
    `{{Brewing Stand}}` template in its second cell, and that template's own
    `|Input=`-style argument lines would otherwise be misread as further
    top-level table cells. The header itself is always
    `{{Inventory slot|X}}<br>Display Name` on one line, so the display name
    is everything after the last `<br>`.
    """
    match = _HEADER_CELL.search(block)
    if match is None:
        return None
    return strip_markup(match.group("content").rsplit("<br>", 1)[-1])


def _parse_base_potions(text: str, *, source: str) -> tuple[BaseRecipe, ...]:
    """Return the base recipes of the `Base potions` table."""
    table = _table_body(text, source=source)
    recipes: list[BaseRecipe] = []
    for block in _row_blocks(table):
        header = _row_header(block)
        if header is None:
            continue
        result_path = BASE_POTION_HEADERS.get(header)
        if result_path is None:
            continue
        templates = find_template(block, "Brewing Stand")
        if not templates:
            raise EnrichError(f"{source} carries a {header!r} row with no Brewing Stand template.")
        parsed = split_template(templates[0].text)
        raw_input = parsed.named.get("Input")
        if raw_input is None:
            raise EnrichError(f"{source} carries a {header!r} recipe with no Input.")
        for name in (part.strip() for part in raw_input.split(";")):
            if not name:
                continue
            item_id = WIKI_NAME_TO_ITEM_ID.get(name)
            if item_id is None:
                raise EnrichError(f"{source} names the base ingredient {name!r}, which is unknown.")
            recipes.append(BaseRecipe(ingredient_item=item_id, result_path=result_path))
    return tuple(recipes)


def _parse_container_steps(text: str, *, source: str) -> None:
    """Verify the `Splash and lingering potions` section still names its two ingredients.

    Both container steps are mechanical -- `pipeline.obtain.brewing` applies
    them to every brewable potion unconditionally, per `TODO.md`'s reading of
    the mechanic -- so there is no recipe shape to extract here. What matters
    is that the page still describes the mechanic in the terms this module
    assumes; a page that stopped mentioning either ingredient is a sign the
    mechanic changed, and that must raise rather than pass silently.
    """
    section = _section(text, SPLASH_LINGERING_HEADING, source=source)
    if "gunpowder" not in section.casefold():
        raise EnrichError(f"{source}'s splash/lingering section no longer mentions gunpowder.")
    if "dragon" not in section.casefold():
        raise EnrichError(
            f"{source}'s splash/lingering section no longer mentions dragon's breath."
        )


def _parse_unbrewable(text: str, *, source: str) -> tuple[str, ...]:
    """Return the wiki names of every potion the `Un-brewable potions` section lists.

    A name marked `{{only|bedrock...}}` or `{{only|be...}}` is dropped, per
    non-negotiable 1 of CLAUDE.md: `potion of Decay` is Bedrock's own
    unbrewable potion, not Java's.
    """
    section = _section(text, UNBREWABLE_HEADING, source=source)
    names = []
    for match in _UNBREWABLE_LINK.finditer(section):
        edition = match.group("edition")
        if edition is not None and edition.split("|")[0].strip().casefold() in {"bedrock", "be"}:
            continue
        label = strip_markup(match.group("label"))
        if label:
            names.append(label)
    if not names:
        raise EnrichError(f"{source} carries an Un-brewable potions section that names nothing.")
    return tuple(names)


def parse_brewing(text: str, *, source: str = PAGE_TITLE) -> BrewingIndex:
    """Return the `BrewingIndex` that `text` (the `Brewing` page's wikitext) describes.

    Pure: builds no request, opens no socket. Raises `EnrichError` on a
    section this module cannot find, a row shape it does not recognize, an
    ingredient name it does not know, or a parse too short to be real --
    see `BrewingIndex._the_parse_is_not_too_short`.
    """
    effect_ingredients_text = _section(text, EFFECT_INGREDIENTS_HEADING, source=source)
    effect_recipes, weakness_recipe, corruption_map = _parse_effect_ingredients(
        effect_ingredients_text, source=source
    )
    if weakness_recipe is None:
        raise EnrichError(f"{source} names no {_WEAKNESS_ROW!r} row, so weakness has no recipe.")

    base_potions_text = _section(text, BASE_POTIONS_HEADING, source=source)
    base_recipes = _parse_base_potions(base_potions_text, source=source)

    _parse_container_steps(text, source=source)
    unbrewable_names = _parse_unbrewable(text, source=source)

    return BrewingIndex(
        base_recipes=base_recipes,
        weakness_recipe=weakness_recipe,
        effect_recipes=effect_recipes,
        corruption_map=corruption_map,
        gunpowder_item=GUNPOWDER_ITEM,
        dragon_breath_item=DRAGON_BREATH_ITEM,
        unbrewable_names=unbrewable_names,
    )


def fetch_brewing(
    *,
    revision: str,
    cache: ContentCache | None = None,
    transport: Transport | None = None,
) -> BrewingIndex:
    """Fetch the `Brewing` page's wikitext and return its `BrewingIndex`.

    `revision` names the cache generation, matching every other wiki reader
    of this package -- pass the Minecraft version for a build.
    """
    report = fetch_page_wikitext([PAGE_TITLE], revision=revision, cache=cache, transport=transport)
    contents = report.contents()
    text = contents.get(PAGE_TITLE)
    if text is None:
        raise EnrichError(
            f"the wiki answered no wikitext for {PAGE_TITLE!r}. An empty scrape is a failure "
            f"to report, not a wiki with no Brewing page."
        )
    return parse_brewing(text, source=PAGE_TITLE)
