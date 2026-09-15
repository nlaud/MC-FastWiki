"""`python -m pipeline check`: check if a newer Minecraft release is available.

Answers whether the version in `manifest.json` is behind Mojang's current
release. Uses the ordered `versions` array from Mojang's version manifest
rather than string inequality, ensuring that a build pinned ahead of the
release (such as a snapshot) is not misidentified as behind.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.cli import CliError
from pipeline.emit.write import DEFAULT_DIST_PATH
from pipeline.fetch import Transport, get_bytes
from pipeline.fetch.version_manifest import fetch_version_manifest

__all__ = ["CheckResult", "run_check"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of checking the built version against Mojang's manifest."""

    built_version: str
    current_release: str
    behind: bool

    @property
    def rebuild_owed(self) -> bool:
        """Whether this answer should make a caller rebuild.

        Derived rather than stored. Being behind the current release is the
        only reason this command asks for a rebuild today, so the two read the
        same -- but they are different questions, and a stored second field
        could drift away from the first without anything noticing. A property
        cannot.
        """
        return self.behind

    def to_dict(self) -> dict[str, Any]:
        """The `--json` payload.

        One key per fact, in one naming convention. An earlier cut emitted
        every field twice, once in snake_case and once in camelCase, which
        leaves a consumer no way to tell which spelling is the contract and
        two places to update when one changes.
        """
        return {
            "built_version": self.built_version,
            "current_release": self.current_release,
            "behind": self.behind,
            "rebuild_owed": self.rebuild_owed,
        }


def run_check(
    *,
    dist: Path = DEFAULT_DIST_PATH,
    json_output: bool = False,
    transport: Transport = get_bytes,
) -> CheckResult:
    """Compare the built version in `dist/manifest.json` to Mojang's current release.

    Prints machine-readable JSON to stdout when `json_output` is True, and a
    human summary line to stderr. When `json_output` is False, prints the human
    summary line to stdout.

    Raises `CliError` if the manifest is missing, malformed, or references an
    unknown Minecraft version.
    """
    manifest_path = dist / "manifest.json"
    if not manifest_path.is_file():
        raise CliError(
            f"{manifest_path} does not exist. Run a build first to generate the distribution "
            "manifest."
        )

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise CliError(f"Failed to read {manifest_path}: {error}") from error

    if not isinstance(manifest_data, dict) or "minecraftVersion" not in manifest_data:
        raise CliError(
            f"{manifest_path} is malformed: missing 'minecraftVersion' top-level field."
        )

    built_version = str(manifest_data["minecraftVersion"])

    version_manifest = fetch_version_manifest(transport=transport)
    current_release = version_manifest.latest_release_id

    version_order = [entry.id for entry in version_manifest.versions]
    if built_version not in version_order:
        raise CliError(
            f"Built version {built_version!r} was not found in Mojang's version manifest. "
            "Cannot determine release ordering."
        )

    built_index = version_order.index(built_version)
    current_index = version_order.index(current_release)

    # Mojang's versions list is ordered newest first.
    # Current release sitting before built version means current release is newer.
    behind = current_index < built_index

    result = CheckResult(
        built_version=built_version,
        current_release=current_release,
        behind=behind,
    )

    if behind:
        human_line = (
            f"Built version {built_version} is behind current release {current_release}. "
            "Rebuild is owed."
        )
    elif built_version == current_release:
        human_line = (
            f"Built version {built_version} is up to date with current release {current_release}."
        )
    else:
        human_line = (
            f"Built version {built_version} is ahead of current release {current_release}."
        )

    if json_output:
        sys.stdout.write(json.dumps(result.to_dict(), indent=2) + "\n")
        sys.stderr.write(human_line + "\n")
    else:
        sys.stdout.write(human_line + "\n")

    return result
