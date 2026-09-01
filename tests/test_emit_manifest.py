"""`build_manifest`: the small payload that names one build of the site.

`built_at` is a parameter of `BuildInfo` rather than a `datetime.now()` call
inside `build_manifest` -- see that function's module docstring -- and these
tests lean on exactly that property: every assertion below passes a fixed
timestamp and checks it round-trips, with no clock to freeze.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

import pipeline
from pipeline.emit.manifest import MANIFEST_SCHEMA_VERSION, BuildInfo, build_manifest


def test_every_required_field_is_present_on_the_built_manifest() -> None:
    build = BuildInfo(
        minecraft_version="26.2",
        mcmeta_ref="26.2-data",
        built_at=datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC),
    )
    manifest = build_manifest(build)

    dumped = manifest.model_dump(mode="json", by_alias=True)
    assert set(dumped) == {
        "schemaVersion",
        "minecraftVersion",
        "mcmetaRef",
        "pipelineVersion",
        "builtAt",
    }
    assert dumped["schemaVersion"] == MANIFEST_SCHEMA_VERSION
    assert dumped["minecraftVersion"] == "26.2"
    assert dumped["mcmetaRef"] == "26.2-data"


def test_pipeline_version_matches_the_installed_package_version() -> None:
    """`tests/test_version.py` keeps `pipeline.__version__` equal to `pyproject.toml`.

    This test only needs the first half of that chain: whatever
    `pipeline.__version__` currently is, `build_manifest` must report it
    unchanged, never a hardcoded string of its own.
    """
    build = BuildInfo(
        minecraft_version="26.2", mcmeta_ref="26.2-data", built_at=datetime.now(UTC)
    )
    manifest = build_manifest(build)
    assert manifest.pipeline_version == pipeline.__version__


def test_built_at_round_trips_as_iso_8601_utc() -> None:
    when = datetime(2026, 8, 31, 3, 4, 5, tzinfo=UTC)
    build = BuildInfo(minecraft_version="26.2", mcmeta_ref="26.2-data", built_at=when)
    manifest = build_manifest(build)

    dumped = manifest.model_dump(mode="json", by_alias=True)
    assert datetime.fromisoformat(dumped["builtAt"]) == when


def test_a_naive_built_at_is_refused() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        BuildInfo(
            minecraft_version="26.2", mcmeta_ref="26.2-data", built_at=datetime(2026, 8, 31)
        )


def test_a_non_utc_offset_is_refused() -> None:
    eastern = datetime(2026, 8, 31, tzinfo=timezone(timedelta(hours=-4)))
    with pytest.raises(ValidationError, match="UTC-aware"):
        BuildInfo(minecraft_version="26.2", mcmeta_ref="26.2-data", built_at=eastern)
