"""JSON Schema files. They are the contract between the pipeline and the web app.

The pipeline validates its output against these files. The web app generates
its TypeScript types from the same files, through
`scripts/generate-schema-types.js`. The two sides never import each other, so
this directory is the only place where they meet.

Each file is self-contained. A file holds every definition it needs in `$defs`,
and no file refers to another file. The generator writes one TypeScript file per
schema, so a cross-file reference would copy a type into two outputs.
"""

import json
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_DIR", "SCHEMA_SUFFIX", "load_schema", "schema_names", "schema_paths"]

SCHEMA_DIR = Path(__file__).resolve().parent

# The generator names each TypeScript output after the part of the file name in
# front of this suffix. `entity.schema.json` becomes `web/types/entity.ts`.
SCHEMA_SUFFIX = ".schema.json"


def schema_paths() -> list[Path]:
    """Return every schema file, sorted by name."""
    return sorted(SCHEMA_DIR.glob(f"*{SCHEMA_SUFFIX}"))


def schema_names() -> list[str]:
    """Return the short name of every schema file, sorted.

    The short name drops the suffix. `entity.schema.json` gives `entity`.
    """
    return [path.name[: -len(SCHEMA_SUFFIX)] for path in schema_paths()]


def load_schema(name: str) -> dict[str, Any]:
    """Read one schema file and return it.

    Pass the short name, without the suffix. An unknown name raises
    `FileNotFoundError`, because a silent empty result would let the validation
    gate pass on a schema that nobody wrote.
    """
    path = SCHEMA_DIR / f"{name}{SCHEMA_SUFFIX}"
    if not path.is_file():
        available = ", ".join(schema_names()) or "none"
        raise FileNotFoundError(f"No schema named {name!r} in {SCHEMA_DIR}. Available: {available}")
    parsed: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path.name} must hold a JSON object at the top level")
    return parsed
