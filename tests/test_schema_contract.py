"""The JSON Schema files are the contract between the pipeline and the web app.

Nothing else reads them yet. The pipeline stages that validate against them
arrive in later phases, and the TypeScript generator runs on the other side of
the repository. These tests hold the invariants that both sides need, so a
broken contract fails here instead of failing in a build that ships wrong data.
"""

import json
import re
from typing import Any

import pytest

from pipeline.schema import SCHEMA_DIR, SCHEMA_SUFFIX, load_schema, schema_names, schema_paths

DRAFT = "https://json-schema.org/draft/2020-12/schema"

# CLAUDE.md names these 13 render blocks. The renderer switches on the `type`
# field, so a missing member here is a section that no page can ever show, and
# an extra member is a renderer that no schema describes.
SECTION_TYPES = {
    "StatBlock",
    "SpawnInfo",
    "DropTable",
    "RecipeTree",
    "ObtainList",
    "BreedingInfo",
    "EffectSources",
    "AdvancementInfo",
    "TradeTable",
    "ChestLoot",
    "EnchantInfo",
    "GenerationInfo",
    "LinkList",
}

# CLAUDE.md names these 9 kinds of searchable thing.
ENTITY_KINDS = {
    "mob",
    "item",
    "block",
    "effect",
    "advancement",
    "enchantment",
    "structure",
    "biome",
    "collection",
}

SCHEMA_NAMES = schema_names()


def _refs(node: Any) -> list[str]:
    """Return every `$ref` string under one node of a schema."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_refs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_refs(item))
    return found


# `examples`, `const`, and `default` hold instance data, not sub-schemas. A JSON
# object in one of them would look like a schema to the walker below.
INSTANCE_KEYWORDS = frozenset({"examples", "const", "default", "enum"})


def _nodes(node: Any) -> list[dict[str, Any]]:
    """Return every sub-schema object under one node, including the node."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for key, value in node.items():
            if key not in INSTANCE_KEYWORDS:
                found.extend(_nodes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_nodes(item))
    return found


def _pascal_case(name: str) -> str:
    """Return the type name that a schema file name should produce."""
    return "".join(part.capitalize() for part in re.split(r"[_-]", name))


def test_the_directory_holds_schema_files() -> None:
    """An empty directory would make every test below pass for the wrong reason."""
    assert SCHEMA_NAMES == ["entity", "manifest"]


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_declares_the_draft_and_its_own_id(name: str) -> None:
    """A reader needs the draft, and a validator needs the identifier.

    The identifier ends with the file name. A mismatch sends a `$ref` from
    another document to a schema that the author did not mean.
    """
    schema = load_schema(name)
    assert schema["$schema"] == DRAFT
    assert schema["$id"].endswith(f"/{name}{SCHEMA_SUFFIX}")


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_self_contained(name: str) -> None:
    """No schema file may point at another file.

    The generator writes one TypeScript file per schema. A cross-file reference
    would copy the same type into two output files, and the web app would then
    hold two names for one thing.
    """
    outside = [ref for ref in _refs(load_schema(name)) if not ref.startswith("#/$defs/")]
    assert outside == []


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_reference_resolves(name: str) -> None:
    """A reference to a missing definition makes the generator produce `unknown`.

    That failure is silent. The web app keeps compiling, and the field loses its
    type.
    """
    schema = load_schema(name)
    defs = schema.get("$defs", {})
    missing = [ref for ref in _refs(schema) if ref.removeprefix("#/$defs/") not in defs]
    assert missing == []


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_definition_is_used_or_named(name: str) -> None:
    """An unused definition is dead weight, or it is a forgotten reference."""
    schema = load_schema(name)
    used = {ref.removeprefix("#/$defs/") for ref in _refs(schema)}
    # `entityRef` is the one exception. Every section payload arrives in Phase 3,
    # so nothing points at it yet. CLAUDE.md still names it as part of the
    # contract, and the generator exports it through `unreachableDefinitions`.
    unused = set(schema.get("$defs", {})) - used - {"entityRef"}
    assert unused == set()


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_declares_a_title(name: str) -> None:
    """A schema without a `title` gets its TypeScript name from its `$id`.

    json-schema-to-typescript falls back to the `$id` when no title names the
    root, and the `$id` here is a URL. A title-less `sprites.schema.json` emits
    `export interface HttpsMcFastwikiLocalSchemaSpritesSchemaJson`, which no
    hand-written import would ever name. Every other gate passes on it, so the
    trap only surfaces once someone reads the generated file.
    """
    schema = load_schema(name)
    assert schema.get("title") == _pascal_case(name)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_required_name_is_a_declared_property(name: str) -> None:
    """A misspelled `required` entry fails in two directions at once.

    Both schemas close their objects with `additionalProperties: false`, so a
    required name that no `properties` block declares can never be supplied and
    the schema rejects every instance. The generator meanwhile drops the unknown
    name and marks the real field optional, so the web app compiles against a
    contract that the pipeline can no longer satisfy. Neither side names the
    typo.
    """
    offenders: list[str] = []
    for node in _nodes(load_schema(name)):
        required = node.get("required")
        if not isinstance(required, list):
            continue
        declared = node.get("properties", {})
        offenders.extend(field for field in required if field not in declared)
    assert offenders == []


def test_every_entity_carries_its_attribution_link() -> None:
    """CLAUDE.md: "every entity keeps a `wikiUrl`".

    The wiki text is CC BY-NC-SA 3.0, so a blurb without a link to its source
    page breaks the license. An optional field lets the pipeline ship one.
    """
    schema = load_schema("entity")
    assert "wikiUrl" in schema["required"]


def test_the_attribution_link_points_at_minecraft_wiki() -> None:
    """CLAUDE.md: "Use minecraft.wiki, not Fandom, for this."

    A curated override is the likely path for a Fandom URL. Without the pattern
    it validates, and the page then credits a wiki that this project never
    scraped, under attribution terms that nobody checked.
    """
    pattern = load_schema("entity")["properties"]["wikiUrl"]["pattern"]
    assert re.match(pattern, "https://minecraft.wiki/w/Creeper")
    assert not re.match(pattern, "https://minecraft.fandom.com/wiki/Creeper")
    assert not re.match(pattern, "https://minecraft-wiki.example/w/Creeper")


def test_entity_kinds_match_the_documented_list() -> None:
    schema = load_schema("entity")
    assert set(schema["$defs"]["entityKind"]["enum"]) == ENTITY_KINDS


def test_the_section_union_covers_every_render_block() -> None:
    """Each member of the union fixes its own `type` value.

    The `type` field is the discriminator. Two members with one value would make
    the renderer pick the wrong block, and a member without a constant would
    make the union impossible to narrow.
    """
    schema = load_schema("entity")
    members = [ref.removeprefix("#/$defs/") for ref in _refs(schema["$defs"]["section"])]
    constants = [schema["$defs"][member]["properties"]["type"]["const"] for member in members]

    assert len(constants) == len(set(constants))
    assert set(constants) == SECTION_TYPES


def test_load_schema_rejects_an_unknown_name() -> None:
    """A silent empty result would let a validation gate pass with no schema."""
    with pytest.raises(FileNotFoundError, match="No schema named 'sprites'"):
        load_schema("sprites")


def test_schema_paths_and_names_agree() -> None:
    assert [path.name for path in schema_paths()] == [
        f"{name}{SCHEMA_SUFFIX}" for name in SCHEMA_NAMES
    ]
    assert all(path.parent == SCHEMA_DIR for path in schema_paths())


def test_the_files_hold_no_trailing_whitespace_and_end_with_one_newline() -> None:
    """The generator reads these files on every build. Keep the bytes stable."""
    for path in schema_paths():
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert json.loads(text)
