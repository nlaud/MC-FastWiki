"""The package version and the project version must agree.

`pipeline.__version__` is written by hand, and `project.version` in
pyproject.toml is written by hand too. Nothing keeps them equal, so a release
can ship a manifest that names a version the package does not report. This
test is the thing that keeps them equal.
"""

import tomllib
from pathlib import Path

import pipeline

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_package_version_matches_pyproject() -> None:
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert pipeline.__version__ == metadata["project"]["version"]
