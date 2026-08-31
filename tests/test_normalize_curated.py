"""Tier C loading: shape faults, Decision D3's position-based staleness, and the
committed `/data/curated` files themselves.

Every test that exercises the loader builds its own documents on `tmp_path`,
so a malformed input is written by the test and never by hand-editing a fixture
that could quietly drift out of sync with the loader's own rules.
"""

import json
import re
from pathlib import Path

import pytest

from pipeline.normalize import NormalizeError
from pipeline.normalize.curated import (
    ALIASES_FILENAME,
    OVERRIDES_FILENAME,
    EntityOverride,
    load_curated,
)
from pipeline.normalize.entity import ENTITY_ID_PATTERN, EntityKind

REPO_ROOT = Path(__file__).resolve().parent.parent
CURATED_DIR = REPO_ROOT / "data" / "curated"

# Mojang's list holds every snapshot alongside the releases, newest first, so
# the front of it is almost never the version a build targets. The snapshot
# below is here on purpose: it is what made `release_order[0]` the wrong answer
# for "the build's target", and a fixture without one lets that bug back in.
RELEASE_ORDER = ("26.3-snapshot-10", "26.2", "26.1", "1.21.10", "1.21.4")

# What `VersionManifest.latest_release_id` answers for the list above.
TARGET_VERSION = "26.2"


def write_curated(
    directory: Path,
    *,
    aliases: dict[str, object] | None = None,
    overrides: dict[str, object] | None = None,
) -> None:
    """Write both curated documents into `directory`, with sensible defaults."""
    (directory / ALIASES_FILENAME).write_text(
        json.dumps(
            aliases
            if aliases is not None
            else {"verifiedFor": "26.2", "note": "x", "aliases": {}}
        ),
        encoding="utf-8",
    )
    (directory / OVERRIDES_FILENAME).write_text(
        json.dumps(
            overrides
            if overrides is not None
            else {"verifiedFor": "26.2", "note": "x", "entities": {}}
        ),
        encoding="utf-8",
    )


# --- Happy path -----------------------------------------------------------------


def test_a_well_formed_pair_of_documents_loads(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        aliases={
            "verifiedFor": "26.2",
            "note": "x",
            "aliases": {"minecraft:golden_apple": ["gapple"]},
        },
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.aliases == {"minecraft:golden_apple": ("gapple",)}
    assert curated.overrides == {}
    assert curated.stale == ()


def test_overrides_parse_into_entity_override_models(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        overrides={
            "verifiedFor": "26.2",
            "note": "x",
            "entities": {"minecraft:tnt": {"name": "TNT", "kind": "block"}},
        },
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.overrides == {
        "minecraft:tnt": EntityOverride(name="TNT", kind=EntityKind.BLOCK)
    }


def test_an_override_may_name_only_one_field(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        overrides={
            "verifiedFor": "26.2",
            "note": "x",
            "entities": {"minecraft:tnt": {"icon": "block:tnt"}},
        },
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    override = curated.overrides["minecraft:tnt"]
    assert override.icon == "block:tnt"
    assert override.name is None


def test_an_override_accepts_the_wiki_url_camel_case_alias(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        overrides={
            "verifiedFor": "26.2",
            "note": "x",
            "entities": {"minecraft:tnt": {"wikiUrl": "https://minecraft.wiki/w/TNT"}},
        },
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.overrides["minecraft:tnt"].wiki_url == "https://minecraft.wiki/w/TNT"


# --- Decision D3: staleness by position, never by parsing ------------------------


def test_the_target_version_is_not_read_off_the_front_of_release_order(tmp_path: Path) -> None:
    """The build's target is `latest.release`, never the newest entry of the manifest.

    Mojang's `versions` list carries every snapshot and pre-release alongside
    the releases, newest first, so its first entry is almost never a version
    this project can build against -- `VersionManifest` refuses a target that
    is not typed `release` at all. An earlier draft of `load_curated` took
    `release_order[0]` as the target anyway, and against the live manifest on
    2026-08-31 that compared every curated document to `26.3-snapshot-10` and
    reported all of them stale while the build targeted `26.2`.

    That failure is worse than a wrong number. A staleness report that fires
    on every document every time is one a reader learns to skip, so the day a
    document really does fall behind, the warning is already invisible.
    """
    write_curated(tmp_path, aliases={"verifiedFor": "26.2", "note": "x", "aliases": {}})
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert RELEASE_ORDER[0] != TARGET_VERSION, "the fixture must not let the bug hide"
    assert curated.stale == ()


def test_a_document_verified_ahead_of_the_target_is_not_stale(tmp_path: Path) -> None:
    """A document checked against a *newer* version than the build is not behind.

    It is the same comparison read the other way, and it matters because the
    curated files are edited by hand between releases: someone verifying an
    override against the snapshot they are testing on must not be told their
    own newer work is out of date.
    """
    write_curated(
        tmp_path,
        aliases={"verifiedFor": "26.3-snapshot-10", "note": "x", "aliases": {}},
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.stale == ()


def test_an_unknown_target_version_is_a_loud_fault(tmp_path: Path) -> None:
    """A target the manifest does not name is a caller bug, not a version to compare."""
    write_curated(tmp_path)
    with pytest.raises(NormalizeError, match=re.escape("26.99")):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version="26.99")


def test_a_document_verified_for_the_newest_release_is_not_stale(tmp_path: Path) -> None:
    write_curated(tmp_path, aliases={"verifiedFor": "26.2", "note": "x", "aliases": {}})
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.stale == ()


def test_a_document_verified_for_an_older_release_is_reported_stale_not_dropped(
    tmp_path: Path,
) -> None:
    write_curated(
        tmp_path,
        aliases={
            "verifiedFor": "26.1",
            "note": "x",
            "aliases": {"minecraft:golden_apple": ["gapple"]},
        },
    )
    curated = load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    # Stale is a warning. The content is kept.
    assert curated.aliases == {"minecraft:golden_apple": ("gapple",)}
    assert len(curated.stale) == 1
    assert curated.stale[0].document == ALIASES_FILENAME
    assert curated.stale[0].verified_for == "26.1"
    assert curated.stale[0].current == "26.2"


def test_the_string_comparison_trap_is_avoided_by_position(tmp_path: Path) -> None:
    """`'1.21.10' < '1.21.4'` under plain string or dotted-tuple comparison, and the game's
    own ordering says the opposite. Position in `release_order` must be the only signal.
    """
    order = ("1.21.10", "1.21.4")
    write_curated(
        tmp_path,
        aliases={"verifiedFor": "1.21.10", "note": "x", "aliases": {}},
        overrides={"verifiedFor": "1.21.4", "note": "x", "entities": {}},
    )
    curated = load_curated(tmp_path, release_order=order, target_version="1.21.10")
    assert len(curated.stale) == 1
    assert curated.stale[0].verified_for == "1.21.4"
    assert curated.stale[0].current == "1.21.10"


def test_a_verified_for_that_release_order_does_not_contain_is_a_loud_fault(
    tmp_path: Path,
) -> None:
    write_curated(tmp_path, aliases={"verifiedFor": "26.99", "note": "x", "aliases": {}})
    with pytest.raises(NormalizeError, match=re.escape("26.99")):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_empty_release_order_is_refused(tmp_path: Path) -> None:
    write_curated(tmp_path)
    with pytest.raises(NormalizeError, match="release_order"):
        load_curated(tmp_path, release_order=(), target_version="26.2")


# --- Malformed documents: Tier C's own bug, not a wiki mid-edit ------------------


def test_a_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(NormalizeError):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_a_document_that_is_not_json_raises(tmp_path: Path) -> None:
    (tmp_path / ALIASES_FILENAME).write_text("not json", encoding="utf-8")
    (tmp_path / OVERRIDES_FILENAME).write_text(
        json.dumps({"verifiedFor": "26.2", "note": "x", "entities": {}}), encoding="utf-8"
    )
    with pytest.raises(NormalizeError, match="not valid JSON"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_a_document_that_is_a_list_raises(tmp_path: Path) -> None:
    write_curated(tmp_path, aliases=["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(NormalizeError, match="not an object"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_a_document_with_no_verified_for_raises(tmp_path: Path) -> None:
    write_curated(tmp_path, aliases={"note": "x", "aliases": {}})
    with pytest.raises(NormalizeError, match="verifiedFor"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_alias_key_that_is_not_a_valid_entity_id_raises(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        aliases={"verifiedFor": "26.2", "note": "x", "aliases": {"Golden Apple": ["gapple"]}},
    )
    with pytest.raises(NormalizeError, match="not a valid entity ID"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_alias_list_that_is_not_a_list_of_strings_raises(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        aliases={
            "verifiedFor": "26.2",
            "note": "x",
            "aliases": {"minecraft:golden_apple": "gapple"},
        },
    )
    with pytest.raises(NormalizeError, match="not a list of strings"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_alias_list_holding_a_non_string_raises(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        aliases={
            "verifiedFor": "26.2",
            "note": "x",
            "aliases": {"minecraft:golden_apple": ["gapple", 5]},
        },
    )
    with pytest.raises(NormalizeError, match="not a list of strings"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_override_key_that_is_not_a_valid_entity_id_raises(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        overrides={"verifiedFor": "26.2", "note": "x", "entities": {"TNT": {"name": "TNT"}}},
    )
    with pytest.raises(NormalizeError, match="not a valid entity ID"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


def test_an_override_with_an_unknown_field_raises() -> None:
    with pytest.raises(Exception, match="not permitted"):
        EntityOverride.model_validate({"nonsenseField": "x"})


def test_an_override_with_a_bad_kind_value_raises(tmp_path: Path) -> None:
    write_curated(
        tmp_path,
        overrides={
            "verifiedFor": "26.2",
            "note": "x",
            "entities": {"minecraft:tnt": {"kind": "not-a-kind"}},
        },
    )
    with pytest.raises(NormalizeError, match="malformed"):
        load_curated(tmp_path, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)


# --- The committed `/data/curated` files themselves ------------------------------


def test_the_committed_curated_files_load() -> None:
    curated = load_curated(CURATED_DIR, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    assert curated.aliases
    assert curated.stale == ()


def test_every_committed_alias_key_matches_the_entity_id_pattern() -> None:
    curated = load_curated(CURATED_DIR, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    for entity_id in curated.aliases:
        assert ENTITY_ID_PATTERN.fullmatch(entity_id), entity_id


def test_every_committed_override_key_matches_the_entity_id_pattern() -> None:
    curated = load_curated(CURATED_DIR, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    for entity_id in curated.overrides:
        assert ENTITY_ID_PATTERN.fullmatch(entity_id), entity_id


def test_the_committed_aliases_file_holds_a_conservative_number_of_entries() -> None:
    """12-20 entries, per the brief -- enough to matter, small enough to stay reviewable."""
    curated = load_curated(CURATED_DIR, release_order=RELEASE_ORDER, target_version=TARGET_VERSION)
    total_aliases = sum(len(values) for values in curated.aliases.values())
    assert 12 <= total_aliases <= 20
