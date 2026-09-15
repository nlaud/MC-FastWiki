"""Tests for `python -m pipeline check`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.cli import CliError, main
from pipeline.cli.check import CheckResult, run_check
from pipeline.fetch import Transport

FAKE_VERSIONS = [
    {"id": "26.3-snapshot-1", "type": "snapshot"},
    {"id": "26.2", "type": "release"},
    {"id": "26.1", "type": "release"},
    {"id": "26.0", "type": "release"},
]


def make_fake_transport(
    *,
    latest_release: str = "26.2",
    latest_snapshot: str = "26.3-snapshot-1",
    versions: list[dict[str, str]] | None = None,
) -> Transport:
    payload = {
        "latest": {"release": latest_release, "snapshot": latest_snapshot},
        "versions": versions if versions is not None else FAKE_VERSIONS,
    }
    encoded = json.dumps(payload).encode("utf-8")

    def transport(url: str) -> bytes:
        return encoded

    return transport


def write_dist_manifest(dist_dir: Path, version: str) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    manifest = dist_dir / "manifest.json"
    manifest.write_text(json.dumps({"minecraftVersion": version}), encoding="utf-8")
    return manifest


def test_check_built_version_is_behind(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_dist_manifest(tmp_path, "26.1")
    transport = make_fake_transport(latest_release="26.2")

    result = run_check(dist=tmp_path, transport=transport)

    assert isinstance(result, CheckResult)
    assert result.built_version == "26.1"
    assert result.current_release == "26.2"
    assert result.behind is True
    assert result.rebuild_owed is True

    captured = capsys.readouterr()
    assert "behind current release 26.2" in captured.out


def test_check_built_version_is_current(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_dist_manifest(tmp_path, "26.2")
    transport = make_fake_transport(latest_release="26.2")

    result = run_check(dist=tmp_path, transport=transport)

    assert result.built_version == "26.2"
    assert result.current_release == "26.2"
    assert result.behind is False
    assert result.rebuild_owed is False

    captured = capsys.readouterr()
    assert "up to date with current release 26.2" in captured.out


def test_check_built_version_is_pinned_ahead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_dist_manifest(tmp_path, "26.3-snapshot-1")
    transport = make_fake_transport(latest_release="26.2")

    result = run_check(dist=tmp_path, transport=transport)

    assert result.built_version == "26.3-snapshot-1"
    assert result.current_release == "26.2"
    assert result.behind is False
    assert result.rebuild_owed is False

    captured = capsys.readouterr()
    assert "ahead of current release 26.2" in captured.out


def test_check_json_output_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_dist_manifest(tmp_path, "26.1")
    transport = make_fake_transport(latest_release="26.2")

    result = run_check(dist=tmp_path, json_output=True, transport=transport)
    assert result.behind is True

    captured = capsys.readouterr()
    # Machine-readable json on stdout
    parsed = json.loads(captured.out)
    assert parsed["built_version"] == "26.1"
    assert parsed["current_release"] == "26.2"
    assert parsed["rebuild_owed"] is True
    # Human line on stderr
    assert "behind current release" in captured.err


def test_check_missing_manifest_raises_cli_error(tmp_path: Path) -> None:
    with pytest.raises(CliError, match="does not exist"):
        run_check(dist=tmp_path)


def test_check_malformed_manifest_raises_cli_error(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"someOtherKey": "value"}), encoding="utf-8")
    with pytest.raises(CliError, match="missing 'minecraftVersion'"):
        run_check(dist=tmp_path)


def test_check_unknown_version_raises_cli_error(tmp_path: Path) -> None:
    write_dist_manifest(tmp_path, "99.99-unknown")
    transport = make_fake_transport(latest_release="26.2")
    with pytest.raises(CliError, match="not found in Mojang's version manifest"):
        run_check(dist=tmp_path, transport=transport)


def test_check_cli_main_invocation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_dist_manifest(tmp_path, "26.2")
    exit_code = main(["check", "--dist", str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "26.2" in captured.out
