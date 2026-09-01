"""Build the `data/dist/manifest.json` payload: which build this is, and when it ran.

`manifest.schema.json`'s own description names the reader: a future `python -m
pipeline check` compares the latest Mojang release against this file to decide
whether a rebuild is needed at all, so every field here answers a question that
comparison asks -- which Minecraft version, which `mcmeta` tag, which pipeline
release, and when.

**`built_at` is a parameter of `BuildInfo`, never a `datetime.now()` call
inside this module.** A function that reaches for the wall clock itself is a
function no test can pin: two calls to `build_manifest` in the same test would
produce two different `builtAt` values, and asserting anything about the field
would mean either freezing the real clock or tolerating a flaky comparison.
Taking `built_at` as data instead makes `build_manifest` a pure function of its
arguments, the same property every other model-building function in this
pipeline already has, and `tests/test_emit_manifest.py`'s round-trip assertion
is what that property is for.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator

from pipeline import __version__

__all__ = ["MANIFEST_SCHEMA_VERSION", "BuildInfo", "Manifest", "build_manifest"]

# The constant `manifest.schema.json`'s `schemaVersion` pins. Raised only when
# a change to this file's shape would break an older reader.
MANIFEST_SCHEMA_VERSION = 1


class BuildInfo(BaseModel, frozen=True):
    """What one build run knows about itself, before it is turned into a manifest.

    `minecraft_version` and `mcmeta_ref` come from the fetch stage that ran
    ahead of this one; `built_at` is the caller's own clock read, taken once
    per build rather than read again here -- see the module docstring for why.
    """

    minecraft_version: str = Field(min_length=1)
    mcmeta_ref: str = Field(min_length=1)
    built_at: datetime

    @field_validator("built_at")
    @classmethod
    def _built_at_is_utc(cls, value: datetime) -> datetime:
        """Refuse a naive or non-UTC timestamp.

        `manifest.schema.json`'s `builtAt` description states the field is UTC,
        and a naive `datetime` cannot honestly claim any zone at all -- it would
        serialise with no offset, which `format: date-time` accepts but which
        silently means "unknown zone" to anyone who reads it back. A `pydantic.
        ValidationError` names the fault precisely, the same reasoning `Entity
        Ref.id`'s own docstring gives for using a plain field constraint instead
        of an `EmitError`: this is a malformed value handed to a model
        constructor, not a fault in the shape of a whole build.
        """
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError(
                f"built_at must be a UTC-aware datetime, got {value!r}. Pass "
                f"datetime.now(UTC), not datetime.now()."
            )
        return value


class Manifest(BaseModel, frozen=True, populate_by_name=True):
    """The whole `manifest.json` payload, mirroring `manifest.schema.json`."""

    schema_version: int = Field(default=MANIFEST_SCHEMA_VERSION, alias="schemaVersion")
    minecraft_version: str = Field(alias="minecraftVersion")
    mcmeta_ref: str = Field(alias="mcmetaRef")
    pipeline_version: str = Field(alias="pipelineVersion")
    built_at: datetime = Field(alias="builtAt")


def build_manifest(build: BuildInfo) -> Manifest:
    """Return the `Manifest` of one build. `pipelineVersion` comes from `pipeline.__version__`.

    `tests/test_version.py` already keeps `pipeline.__version__` equal to
    `pyproject.toml`'s `project.version`, so reading it here rather than
    threading a version string through `BuildInfo` keeps the manifest and the
    installed package from ever disagreeing about which release wrote a build.
    """
    return Manifest(
        minecraft_version=build.minecraft_version,
        mcmeta_ref=build.mcmeta_ref,
        pipeline_version=__version__,
        built_at=build.built_at,
    )
