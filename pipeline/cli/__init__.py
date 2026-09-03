"""`python -m pipeline build`: the command line entry point of the pipeline.

Every stage package before this one -- `pipeline.fetch`, `pipeline.extract`,
`pipeline.enrich`, `pipeline.normalize`, `pipeline.emit` -- is a library. Each
one is tested by importing it directly, and none of them defines a way for a
person at a terminal to run a whole build. This package is that way. It holds
two things and nothing else: `CliError`, the one fault this package raises
that no earlier stage already has a name for, and `main`, the function
`pipeline/__main__.py` calls with `sys.argv[1:]`.

`main` parses arguments, dispatches to `pipeline.cli.build.run_build`, and
maps whatever that call raises onto a process exit code. It does the mapping
itself rather than let a stage exception reach the interpreter, because a
raw Python traceback is not what a person running a build wants to read when
the wiki is unreachable or a Minecraft version has no data yet -- CLAUDE.md's
own error-message rule ("error messages are written to be read by a person")
applies to a build failure at the command line exactly as it applies to a
`FetchError` raised deep inside `pipeline.fetch`.

## Exit codes

* **0** -- the build finished and wrote `data/dist`.
* **1** -- a build stage raised one of `FetchError`, `ExtractError`,
  `EnrichError`, `NormalizeError`, `EmitError`, `ValidationError`, or this
  package's own `CliError`. `main` prints `str(error)` to stderr, with no
  traceback, and returns 1. Every one of those seven classes already writes a
  message meant for a person to read -- that is the whole point of the
  exception hierarchy CLAUDE.md's tiers describe -- so `main` adds nothing to
  it and hides nothing from it.
* **2** -- a usage error: an unknown flag, a missing subcommand, a value
  `argparse` itself cannot parse. `argparse.ArgumentParser.parse_args` raises
  `SystemExit(2)` for these on its own, and `--help`/`-h` raises `SystemExit
  (0)` the same way. `main` does not catch `SystemExit` at all, so both of
  argparse's own exit codes reach the process exactly as argparse chose them.

## One subcommand: `build`

`python -m pipeline build` is the only command this package defines. There is
no `check` subcommand -- an earlier phase of this project sketched one
(`python -m pipeline check` answering "does a newer release exist"), but that
command was never built, and this task adds `build` alone. A `check`
subcommand is a natural follow-up once something other than a human reads its
answer, not a gap this module leaves open by accident.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pipeline.emit.shard import DEFAULT_SHARD_SIZE
from pipeline.emit.write import DEFAULT_DIST_PATH
from pipeline.fetch.cache import DEFAULT_CACHE_ROOT

__all__ = ["CliError", "main"]


class CliError(Exception):
    """A fault of the CLI itself, not of any build stage.

    Reserved for a constraint no earlier stage's own exception can name --
    today, exactly one: `--offline` with no `--minecraft-version`, which
    `pipeline.cli.build.run_build`'s own module docstring explains in full.
    Every other fault a build can hit already has a home in `FetchError`,
    `ExtractError`, `EnrichError`, `NormalizeError`, or `EmitError`, and
    `main` maps all six exception classes onto the same exit code for the
    same reason: each one is already a message written for a person to read.
    """


# Where `data/reports/` sits by default. Every one of the four stage report
# writers already exports its own `DEFAULT_REPORT_PATH` rooted here; this is
# the directory itself, for the `--reports` flag's own default.
DEFAULT_REPORTS_ROOT = Path("data") / "reports"


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of `python -m pipeline`.

    A function, not a module-level constant, so a test that calls `main`
    more than once builds a fresh, unshared parser every time --
    `argparse.ArgumentParser` is mutable, and reusing one instance across
    calls would let state from an earlier parse leak into a later one.
    """
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Build-time data pipeline for MC-FastWiki.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser(
        "build",
        help="Fetch, extract, enrich, normalize, and emit one Minecraft version.",
        description=(
            "Run the whole pipeline for one Minecraft Java Edition release and write "
            "data/dist."
        ),
    )
    build_parser.add_argument(
        "--minecraft-version",
        dest="minecraft_version",
        metavar="ID",
        default=None,
        help="The Minecraft release to build, such as 26.2. Defaults to Mojang's "
        "current release.",
    )
    build_parser.add_argument(
        "--dist",
        type=Path,
        metavar="PATH",
        default=DEFAULT_DIST_PATH,
        help=f"Where to write the site payload. Defaults to {DEFAULT_DIST_PATH}.",
    )
    build_parser.add_argument(
        "--cache",
        type=Path,
        metavar="PATH",
        default=DEFAULT_CACHE_ROOT,
        help=f"Where the content-addressed fetch cache lives. Defaults to "
        f"{DEFAULT_CACHE_ROOT}.",
    )
    build_parser.add_argument(
        "--reports",
        type=Path,
        metavar="PATH",
        default=DEFAULT_REPORTS_ROOT,
        help=f"Where to write the build's stage reports. Defaults to {DEFAULT_REPORTS_ROOT}.",
    )
    build_parser.add_argument(
        "--shard-size",
        dest="shard_size",
        type=int,
        metavar="N",
        default=DEFAULT_SHARD_SIZE,
        help=f"Entities per shard file. Defaults to {DEFAULT_SHARD_SIZE}.",
    )
    build_parser.add_argument(
        "--offline",
        action="store_true",
        help="Read the fetch cache only; never open the network. Requires "
        "--minecraft-version.",
    )
    build_parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress lines on stderr.",
    )
    build_parser.add_argument(
        "--allow-regression",
        dest="allow_regression",
        action="store_true",
        help="Downgrade a validation gate regression-check failure to a warning, still recorded "
        "in full in data/reports/validation.json. Never downgrades a schema conformance "
        "failure -- a malformed document always fails the build.",
    )
    return parser


def main(argv: Sequence[str]) -> int:
    """Parse `argv`, run the build it names, and return the process exit code.

    `argv` is `sys.argv[1:]`, not `sys.argv` itself -- `pipeline/__main__.py`
    passes it that way, and a test passes its own list the same way, so
    neither one has to know this function ignores the program name.

    See the module docstring for the exit codes and what each one means.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    options = BuildOptions(
        minecraft_version=args.minecraft_version,
        dist=args.dist,
        cache=args.cache,
        reports=args.reports,
        shard_size=args.shard_size,
        offline=args.offline,
        quiet=args.quiet,
        allow_regression=args.allow_regression,
    )

    try:
        run_build(options)
    except (
        FetchError,
        ExtractError,
        EnrichError,
        NormalizeError,
        EmitError,
        ValidationError,
        CliError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


# Imported after `CliError` is defined, not at the top of the file:
# `pipeline.cli.build` imports `CliError` from this package to raise it, so
# this package's own `CliError` has to exist as an attribute of the
# `pipeline.cli` module before that submodule is loaded. Putting this import
# above the class definition would make `build.py`'s `from pipeline.cli
# import CliError` fail with a circular-import error, because the
# partially-initialised `pipeline.cli` module would not have set the name
# yet -- the same ordering `pipeline.emit.__init__` keeps for `pipeline.emit.
# write` and explains in full.
from pipeline.cli.build import BuildOptions, run_build  # noqa: E402
from pipeline.emit import EmitError  # noqa: E402
from pipeline.enrich import EnrichError  # noqa: E402
from pipeline.extract import ExtractError  # noqa: E402
from pipeline.fetch import FetchError  # noqa: E402
from pipeline.normalize import NormalizeError  # noqa: E402
from pipeline.validate import ValidationError  # noqa: E402
