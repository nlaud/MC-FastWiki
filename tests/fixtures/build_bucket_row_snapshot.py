"""Rebuild the wiki Bucket row snapshot that pins the enrich stage.

A person runs this module by hand. It is not a test, and pytest does not collect
it, because the name does not start with `test_`. It follows the precedent of
`tests/fixtures/build_block_tag_snapshot.py`, which does the same job for the
mcmeta side.

`tests/test_enrich_snapshot.py` reads the file this writes. Every other test of
the enrich stage builds its rows in memory, one trap per test, so a parser that
is wrong about the real table still passes them. This snapshot is the only test
that reads what the wiki actually sends.

Run it from the repository root:

    python -m tests.fixtures.build_bucket_row_snapshot

The module opens the network. It reads through `pipeline.fetch.bucket`, so it
takes the path a build takes, obeys the same rate limit, and writes the same
content cache.

**The subset is chosen, not sampled.** Each entry of `QUERIES` below names one
page, or a small slice of one, that carries a trap the parsers have to survive:
a Bedrock-only drop, a mob whose spawn variant differs from its page, a recipe
row that packs two variants into one set of slots, a translation page that must
be filtered out by namespace. Fetching whole buckets would make a fixture too
large to review and would still not guarantee those cases stayed in it.

**There is no version to pin to.** mcmeta publishes a tag per Minecraft release;
the wiki is edited continuously. So the header carries the date the rows were
captured, and the snapshot test checks the shape and the facts rather than
byte-equality with a live re-fetch. When an assertion in that test starts to
fail, the question to ask is whether the wiki changed or the parser did.

To refresh it: run the module, read the diff, and check that any changed number
is a wiki edit you agree with before committing it.
"""

import datetime
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pipeline.enrich import advancement, crafting_recipe, droptable, resource_location
from pipeline.enrich import spawn_table as spawn
from pipeline.enrich import trade as trading
from pipeline.fetch.bucket import BUCKET_API_URL, fetch_bucket_rows

FIXTURE = Path(__file__).resolve().parent / "wiki_bucket_rows.json"

# The cache generation this module reads under. It is a date rather than a
# Minecraft version because the wiki has no version; `pipeline.fetch.bucket`
# explains why a Bucket cache key needs one at all.
REVISION = datetime.date.today().isoformat()

# One entry per fetch: the bucket, the columns the enrich module selects, and
# the `where` clause that narrows the table to the rows worth committing. Every
# comment below names the trap the rows carry.
QUERIES: tuple[tuple[str, str, Sequence[str], Sequence[Sequence[str]], int | None], ...] = (
    # `Stone` is the plain case, written on 14 pages, so it also pins the
    # deduplication. `Eye of Ender` is the ambiguity that `kind` resolves.
    # `Bottle o' Enchanting` arrives HTML-escaped. The meme page proves the
    # namespace filter drops a well-formed row that is not about Minecraft.
    ("resource_location", "stone", resource_location.COLUMNS, (("page_name", "Stone"),), None),
    (
        "resource_location",
        "eye_of_ender",
        resource_location.COLUMNS,
        (("page_name", "Eye of Ender"),),
        None,
    ),
    (
        "resource_location",
        "bottle_o_enchanting",
        resource_location.COLUMNS,
        (("page_name", "Bottle o' Enchanting"),),
        None,
    ),
    (
        "resource_location",
        "user_page",
        resource_location.COLUMNS,
        (("page_name", "User:Hipposgrumm/Memes/Bucketolotl"),),
        None,
    ),
    # Zombie carries the conditional iron ingot, so it pins the notes. Skeleton
    # carries the four looting levels of the arrow. Spider's spider eye is
    # Bedrock-only, so it pins the edition filter.
    ("droptable", "zombie", droptable.COLUMNS, (("page_name", "Zombie"),), None),
    ("droptable", "skeleton", droptable.COLUMNS, (("page_name", "Skeleton"),), None),
    ("droptable", "spider", droptable.COLUMNS, (("page_name", "Spider"),), None),
    # Desert holds both editions of the same biome. Taiga is where the `mob`
    # column and the blob's `Spawned mob` disagree: `Chicken` against `Cold
    # Chicken`.
    ("spawn_table", "desert", spawn.COLUMNS, (("page_name", "Desert"),), None),
    ("spawn_table", "taiga", spawn.COLUMNS, (("page_name", "Taiga"),), None),
    # Torch packs two variants into one row. Wooden Pickaxe pins the grid
    # orientation. Wooden Fence is a collapsed `Matching` group. Glow Stick is
    # Bedrock and Education only. Map is the row whose variants do not line up.
    ("crafting_recipe", "torch", crafting_recipe.COLUMNS, (("page_name", "Torch"),), None),
    (
        "crafting_recipe",
        "wooden_pickaxe",
        crafting_recipe.COLUMNS,
        (("page_name", "Wooden Pickaxe"),),
        None,
    ),
    (
        "crafting_recipe",
        "wooden_fence",
        crafting_recipe.COLUMNS,
        (("page_name", "Wooden Fence"),),
        None,
    ),
    (
        "crafting_recipe",
        "glow_stick",
        crafting_recipe.COLUMNS,
        (("page_name", "Glow Stick"),),
        None,
    ),
    ("crafting_recipe", "map", crafting_recipe.COLUMNS, (("page_name", "Map"),), None),
    # The whole live advancement list, which is the table the pipeline uses, and
    # three rows from a 2017 snapshot page whose internal IDs collide with it.
    (
        "advancement",
        "current",
        advancement.COLUMNS,
        (("page_name", advancement.ADVANCEMENT_PAGE),),
        None,
    ),
    (
        "advancement",
        "snapshot_page",
        advancement.COLUMNS,
        (("page_name", "Java Edition 17w13a"),),
        3,
    ),
    # Librarian holds the enchanted-book trade, which is the one with a second
    # wanted item and a `5-64` price range. Wandering Trader holds the levels
    # that are not the villager ladder.
    ("trade", "librarian", trading.COLUMNS, (("page_name", "Librarian"),), None),
    (
        "trade",
        "wandering_trader",
        trading.COLUMNS,
        (("page_name", "Wandering Trader"),),
        6,
    ),
)


def fetch_slice(
    bucket: str,
    columns: Sequence[str],
    where: Sequence[Sequence[str]],
    keep: int | None,
) -> list[dict[str, object]]:
    """Return the rows of one entry of `QUERIES`, capped at `keep`.

    The cap is applied here rather than as a `limit()` on the query.
    `fetch_bucket_rows` paginates to the end of a table on purpose and chooses
    its own page size, for the reason its module docstring gives: the server
    truncates an oversized limit without saying so, and a loop that trusts its
    own limit stops early. Taking the whole slice and keeping the first few rows
    of it costs one request more than nothing and leaves that guarantee alone.
    """
    rows = fetch_bucket_rows(bucket, columns, revision=REVISION, where=where)
    return rows if keep is None else rows[:keep]


def write_fixture(path: Path, document: Mapping[str, object]) -> None:
    """Write the fixture, indented, with a final newline and LF endings."""
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    """Fetch every slice and write the snapshot."""
    buckets: dict[str, dict[str, list[dict[str, object]]]] = {}
    for bucket, name, columns, where, keep in QUERIES:
        rows = fetch_slice(bucket, columns, where, keep)
        buckets.setdefault(bucket, {})[name] = rows
        print(f"{bucket}/{name}: {len(rows)} rows")
    write_fixture(
        FIXTURE,
        {
            "captured": REVISION,
            "api_url": BUCKET_API_URL,
            "note": (
                "Chosen slices of the Minecraft Wiki Bucket API, one per trap the enrich "
                "stage has to survive. Rebuilt by "
                "tests/fixtures/build_bucket_row_snapshot.py. Content is CC BY-NC-SA 3.0."
            ),
            "buckets": buckets,
        },
    )
    print(f"{FIXTURE.name}: {sum(len(s) for b in buckets.values() for s in b.values())} rows")


if __name__ == "__main__":
    main()
