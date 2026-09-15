"""Argument parsing and exit codes of `python -m pipeline`.

`pipeline.cli.main` is the one function `pipeline/__main__.py` calls, and it is
also the one function this module drives directly -- no test here spawns a
subprocess, because `main` takes `argv` as a plain list and returns an `int`,
exactly so a test does not have to. What this module pins is the contract
CLAUDE.md and the task plan both state: `--help` exits 0, a usage error exits
2 with no build attempted, and each of the six fault classes `main` catches
maps to exit 1 with `str(error)` on stderr and no traceback.
"""

from pathlib import Path

import pytest

import pipeline.cli as cli_module
from pipeline.cli import CliError, main
from pipeline.cli.build import BuildOptions
from pipeline.emit import EmitError
from pipeline.emit.shard import DEFAULT_SHARD_SIZE
from pipeline.emit.write import DEFAULT_DIST_PATH
from pipeline.enrich import EnrichError
from pipeline.extract import ExtractError
from pipeline.fetch import FetchError
from pipeline.fetch.cache import DEFAULT_CACHE_ROOT
from pipeline.normalize import NormalizeError


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "build" in capsys.readouterr().out


def test_build_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["build", "--help"])
    assert excinfo.value.code == 0
    assert "--minecraft-version" in capsys.readouterr().out


def test_no_subcommand_exits_two() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_unknown_subcommand_exits_two() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["nope"])
    assert excinfo.value.code == 2


def test_unknown_flag_exits_two() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["build", "--nope"])
    assert excinfo.value.code == 2


FAULT_CLASSES = (FetchError, ExtractError, EnrichError, NormalizeError, EmitError, CliError)


@pytest.mark.parametrize("fault_class", FAULT_CLASSES)
def test_a_build_fault_exits_one_with_the_message_and_no_traceback(
    fault_class: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    message = f"a {fault_class.__name__} that a person should be able to read"

    def fake_run_build(options: BuildOptions) -> None:
        raise fault_class(message)

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    code = main(["build", "--minecraft-version", "26.2"])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.err == f"{message}\n"
    # No traceback: stderr holds exactly the message and nothing that looks
    # like a Python frame.
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_a_build_fault_does_not_propagate_as_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main` returns an exit code for a caught fault; it never re-raises one."""

    def fake_run_build(options: BuildOptions) -> None:
        raise FetchError("the network is unreachable")

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    # Raises nothing -- a SystemExit here would fail the test on its own.
    assert main(["build", "--minecraft-version", "26.2"]) == 1


def test_a_successful_build_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_build(options: BuildOptions) -> None:
        return None

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    assert main(["build", "--minecraft-version", "26.2"]) == 0


def test_defaults_match_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m pipeline build` with no flags builds the documented defaults."""
    captured: list[BuildOptions] = []

    def fake_run_build(options: BuildOptions) -> None:
        captured.append(options)

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    assert main(["build"]) == 0
    assert len(captured) == 1
    options = captured[0]
    assert options.minecraft_version is None
    assert options.dist == DEFAULT_DIST_PATH
    assert options.cache == DEFAULT_CACHE_ROOT
    assert options.reports == Path("data") / "reports"
    assert options.shard_size == DEFAULT_SHARD_SIZE
    assert options.offline is False
    assert options.quiet is False


def test_every_flag_reaches_build_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[BuildOptions] = []

    def fake_run_build(options: BuildOptions) -> None:
        captured.append(options)

    monkeypatch.setattr(cli_module, "run_build", fake_run_build)

    assert (
        main(
            [
                "build",
                "--minecraft-version",
                "26.2",
                "--dist",
                "out/dist",
                "--cache",
                "out/cache",
                "--reports",
                "out/reports",
                "--shard-size",
                "50",
                "--offline",
                "--quiet",
            ]
        )
        == 0
    )
    assert len(captured) == 1
    options = captured[0]
    assert options.minecraft_version == "26.2"
    assert options.dist == Path("out/dist")
    assert options.cache == Path("out/cache")
    assert options.reports == Path("out/reports")
    assert options.shard_size == 50
    assert options.offline is True
    assert options.quiet is True
