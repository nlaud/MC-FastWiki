"""The Mojang version manifest, read for the current release ID and nothing else.

`python -m pipeline check` answers one question: does a Minecraft Java Edition
release exist that is newer than the one in `data/dist/manifest.json`? The
answer needs the ID of the current release, and Mojang publishes that ID here.
The command itself belongs to a later phase. This module holds the function it
calls.

The manifest also names the jars of every version. This project never downloads
one. Tier A comes from `misode/mcmeta`, which publishes the output of Mojang's
data generator as JSON, so the pipeline needs no JVM.

Two things this module does not do:

* It keeps no disk cache. CLAUDE.md asks for a content-hash cache on network
  fetches, and that rule protects the large mcmeta payloads and the several
  thousand sprites, which are immutable per version tag. This read asks what the
  current release is. A cached answer to that question is a stale answer, and a
  stale answer defeats the command. Mojang sends `Cache-Control: max-age=120`,
  so the service expects a reader to come back.
* It does not trust `latest.release` on its own. See below.
"""

from typing import Any, Self

from pydantic import BaseModel, ValidationError, model_validator

from pipeline.fetch import FetchError, Transport, decode_json, get_bytes

__all__ = [
    "RELEASE_TYPE",
    "VERSION_MANIFEST_URL",
    "LatestVersions",
    "VersionEntry",
    "VersionManifest",
    "fetch_latest_release_id",
    "fetch_version_manifest",
    "parse_version_manifest",
]

VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"

# The `type` of an entry is one of `release`, `snapshot`, `old_beta`, or
# `old_alpha`. Only the first one may drive a build.
RELEASE_TYPE = "release"


class LatestVersions(BaseModel):
    """The `latest` object. It names the current release and the current snapshot."""

    release: str
    snapshot: str


class VersionEntry(BaseModel):
    """One entry of the `versions` list.

    The entry also carries `url`, `time`, `releaseTime`, `sha1`, and
    `complianceLevel`. Those describe the jar and its metadata file, which this
    project never downloads, so the model drops them.
    """

    id: str
    type: str


class VersionManifest(BaseModel):
    """The manifest, checked for the one contradiction that would break a build."""

    latest: LatestVersions
    versions: list[VersionEntry]

    @model_validator(mode="after")
    def _latest_release_must_be_a_release(self) -> Self:
        """`latest.release` must name an entry, and that entry must be a release.

        The first non-negotiable rule of this project is Java Edition data that
        is correct. A snapshot ID reaching the build sends every later stage at
        the wrong version of the game, and the wrong numbers then look exactly
        like the right ones on the screen.

        `latest.release` is one string. No other field of the manifest guards
        it, so this check is what makes it safe to read: find the entry with
        that ID, and require the type of the entry to be `release`. A manifest
        that fails either half raises, and the build stops. CLAUDE.md asks for
        a loud failure over a guess.
        """
        entry = next((item for item in self.versions if item.id == self.latest.release), None)
        if entry is None:
            raise ValueError(
                f"latest.release names {self.latest.release!r}, but no entry of the versions "
                f"list has that id, so the type of the release cannot be checked"
            )
        if entry.type != RELEASE_TYPE:
            raise ValueError(
                f"latest.release names {self.latest.release!r}, and that entry has the type "
                f"{entry.type!r}, not {RELEASE_TYPE!r}. This build takes releases only."
            )
        return self

    @property
    def latest_release_id(self) -> str:
        """The ID of the current release, such as `26.2`.

        The validator above already proved that an entry with this ID exists and
        that the entry is a release.
        """
        return self.latest.release


def parse_version_manifest(
    payload: bytes, *, source: str = VERSION_MANIFEST_URL
) -> VersionManifest:
    """Read one manifest body and return the checked model.

    The function is pure. It reads bytes and returns a model, so every rule
    above is covered by a test that opens no socket. Any bad payload raises
    `FetchError`.
    """
    document: Any = decode_json(payload, source=source)
    if not isinstance(document, dict):
        raise FetchError(
            f"{source} returned {type(document).__name__} at the top level, not a JSON object"
        )
    try:
        return VersionManifest.model_validate(document)
    except ValidationError as error:
        raise FetchError(f"{source} is not a usable version manifest: {error}") from error


def fetch_version_manifest(*, transport: Transport = get_bytes) -> VersionManifest:
    """Read the manifest from Mojang and return the checked model.

    Pass `transport` to read the bytes from somewhere else. A test passes a
    callable of its own, so no test of this module opens a socket.
    """
    return parse_version_manifest(transport(VERSION_MANIFEST_URL))


def fetch_latest_release_id(*, transport: Transport = get_bytes) -> str:
    """Return the ID of the current Minecraft Java Edition release, such as `26.2`."""
    return fetch_version_manifest(transport=transport).latest_release_id
