"""Regression fixture for the pydantic mypy plugin settings.

`mypy` is the runner here, not pytest, so the file name stays outside pytest's
`test_*.py` collection pattern. Each call below must produce exactly the error
code named in its `type: ignore`. `warn_unused_ignores` comes with mypy strict
mode, so if `[tool.pydantic-mypy]` in pyproject.toml ever loses
`init_typed` or `init_forbid_extra`, the matching error disappears, the ignore
turns unused, and `mypy` fails.

Guarding this matters because both failures are silent at runtime: pydantic
coerces what it can and drops unknown keys without a warning, so a curated
override with a misspelled field would take effect nowhere and report nothing.
"""

from pydantic import BaseModel


class FoodComponent(BaseModel):
    """Stand-in for a real model. Mirrors `minecraft:food` from Tier A."""

    nutrition: int
    saturation: float


def wrong_field_type() -> FoodComponent:
    """`init_typed` turns a mistyped field into an `arg-type` error."""
    return FoodComponent(nutrition="four", saturation=2.4)  # type: ignore[arg-type]


def misspelled_field() -> FoodComponent:
    """`init_forbid_extra` turns an unknown field into a `call-arg` error."""
    return FoodComponent(nutrition=4, saturation=2.4, saturationn=2.4)  # type: ignore[call-arg]


def correct_call() -> FoodComponent:
    """The settings must not reject a correct call."""
    return FoodComponent(nutrition=4, saturation=2.4)
