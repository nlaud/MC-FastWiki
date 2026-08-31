"""Rebuild the wiki `spritefile` snapshot that pins `pipeline.enrich.sprite`.

A person runs this module by hand. It is not a test, and pytest does not
collect it, because the name does not start with `test_`. It follows the
precedent of `tests/fixtures/build_bucket_row_snapshot.py`, which does the same
job for the other Bucket-backed enrich modules.

`tests/test_sprite_snapshot.py` reads the file this writes. Every other test of
`pipeline.enrich.sprite` builds its rows in memory, one trap per test, so a
parser that is wrong about the real table still passes them. This snapshot is
the only test that reads what the wiki actually sends.

Run it from the repository root:

    python -m tests.fixtures.build_sprite_snapshot

The module opens the network. It reads through `pipeline.fetch.bucket`, so it
takes the path a build takes, obeys the same rate limit, and writes the same
content cache.

**The subset is chosen, not sampled.** Each entry of `ROWS` below names one
`(family, sprite_id)` pair that carries a trap the parser has to survive, and
`FAMILY_SAMPLES` names a small slice of a family that is not in
`VANILLA_FAMILIES`, to pin the family filter against a real answer rather than
only a fixture built in memory. Fetching the whole 20,013-row table would make
a fixture too large to review and would still not guarantee any one trap
stayed in it -- the exact risk `tests/fixtures/build_bucket_row_snapshot.py`'s
own docstring names for the buckets it slices.

**There is no version to pin to.** mcmeta publishes a tag per Minecraft
release; the wiki is edited continuously. So the header carries the date the
rows were captured, and `tests/test_sprite_snapshot.py` checks facts a person
can verify against the live bucket rather than byte-equality with a fresh
fetch. When an assertion in that test starts to fail, the question to ask is
whether the wiki changed or the parser did.

To refresh it: run the module, read the diff, and check that any changed row
is a wiki edit you agree with before committing it.
"""

import datetime
import json
from pathlib import Path

from pipeline.enrich.sprite import BUCKET, COLUMNS
from pipeline.fetch.bucket import BUCKET_API_URL, fetch_bucket_rows

FIXTURE = Path(__file__).resolve().parent / "wiki_sprite_rows.json"

# The cache generation this module reads under. A date, not a Minecraft
# version, for the reason `tests/fixtures/build_bucket_row_snapshot.py` gives:
# the wiki has no version.
REVISION = datetime.date.today().isoformat()

# One `(family, sprite_id)` pair per trap. Every comment names the shape it
# pins.
ROWS: tuple[tuple[str, str], ...] = (
    # `Raw Iron` is the ordinary `Invicon <Name>.png` shape.
    ("InvSprite", "Raw Iron"),
    # `Pancake Stack` is one of the 115 `InvSprite` rows that does not follow
    # the `Invicon <Name>.png` pattern -- it names `PancakeInvSprite.png`. This
    # is why `parse_sprite_files` never builds a filename from an id.
    ("InvSprite", "Pancake Stack"),
    # `Sculk Block` names a `.gif`, not a `.png`, and also carries the
    # `deprecated` field -- present as an empty string, which is falsy, so
    # this pins that the file extension is read as-is and that a falsy
    # `deprecated` value is not mistaken for a set one.
    ("InvSprite", "Sculk Block"),
    # `Acacia Wood Button` and `Acacia Button` both name
    # `File:Invicon Acacia Button.png`. `Acacia Wood Button` also carries
    # `deprecated`. Two different sprite ids naming one file is not a
    # conflict -- `parse_sprite_files` only refuses a conflict on one id
    # naming two files -- so both rows must survive as separate entries.
    ("InvSprite", "Acacia Wood Button"),
    ("InvSprite", "Acacia Button"),
    # `Cave Air` names `File:Blank.png`, a file several other ids also share.
    ("InvSprite", "Cave Air"),
    # An ordinary `BlockSprite` and `ItemSprite` row each, hyphenated exactly
    # as `pipeline.normalize.reconcile.hyphenated_sprite_id` expects.
    ("BlockSprite", "acacia-button"),
    ("BlockSprite", "acacia-door"),
    ("ItemSprite", "iron-sword"),
    # An `EntitySprite`, an `EffectSprite`, a `BiomeSprite`, and an `EnvSprite`
    # row, one each, so every family Phase 2 reconciles against has at least
    # one real row in this fixture.
    ("EntitySprite", "zombie-villager-desert-shepherd"),
    ("EffectSprite", "absorption"),
    ("BiomeSprite", "deep-ocean"),
    ("EnvSprite", "abandoned-village"),
    # The two advancement icon eras.
    ("AchievementSprite", "acquire-hardware"),
    ("NewAchievementSprite", "atlantis?"),
)

# A small slice of families that are not in `VANILLA_FAMILIES`, to pin the
# family filter against real rows rather than only ones built in memory.
# `keep` caps how many rows of that slice are kept, the same way
# `build_bucket_row_snapshot.fetch_slice` caps a whole-page read.
FAMILY_SAMPLES: tuple[tuple[str, int], ...] = (
    # Minecraft Dungeons, out of scope alongside every other non-Java product.
    ("DungeonsItemSprite", 3),
    # Legacy Console Edition, out of scope alongside Bedrock.
    ("LegacyBlockSprite", 2),
    # Wiki editor persona skins, not a Minecraft Java Edition fact at all.
    ("SkinSprite", 2),
)


def fetch_row(family: str, sprite_id: str) -> dict[str, object]:
    """Return the one row of `(family, sprite_id)`, or raise if the wiki holds none."""
    rows = fetch_bucket_rows(
        BUCKET, COLUMNS, revision=REVISION, where=(("name", family), ("id", sprite_id))
    )
    if not rows:
        raise ValueError(f"the wiki holds no {family!r} row of id {sprite_id!r}.")
    return rows[0]


def fetch_family_sample(family: str, keep: int) -> list[dict[str, object]]:
    """Return up to `keep` rows of `family`, in whatever order the wiki answers."""
    rows = fetch_bucket_rows(BUCKET, COLUMNS, revision=REVISION, where=(("name", family),))
    return rows[:keep]


def write_fixture(path: Path, document: dict[str, object]) -> None:
    """Write the fixture, indented, with a final newline and LF endings."""
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    """Fetch every row and sample, and write the snapshot."""
    rows = [fetch_row(family, sprite_id) for family, sprite_id in ROWS]
    for family, keep in FAMILY_SAMPLES:
        sample = fetch_family_sample(family, keep)
        rows.extend(sample)
        print(f"{family}: {len(sample)} sample rows")
    for (family, sprite_id), row in zip(ROWS, rows, strict=False):
        print(f"{family}/{sprite_id}: {row}")
    write_fixture(
        FIXTURE,
        {
            "captured": REVISION,
            "api_url": BUCKET_API_URL,
            "note": (
                "Chosen rows and family samples of the Minecraft Wiki spritefile bucket, one "
                "per trap pipeline.enrich.sprite has to survive. Rebuilt by "
                "tests/fixtures/build_sprite_snapshot.py. Content is CC BY-NC-SA 3.0."
            ),
            "rows": rows,
        },
    )
    print(f"{FIXTURE.name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
