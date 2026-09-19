"""The JSON Schema files are the contract between the pipeline and the web app.

`pipeline.validate.conformance` is the pipeline stage that validates real build output against
these files, with a real `jsonschema.Draft202012Validator` -- see `tests/test_validate_
conformance.py` for that half of the coverage, including the false-positive test that runs this
repository's own committed `data/dist` back through it. The TypeScript generator runs on the other
side of the repository, from the same five files. The tests in this file hold the invariants both
sides need before either one ever reads a schema, so a broken contract fails here instead of
failing in a build that ships wrong data, or in a generator that emits `unknown`.

The bottom section, from `PYDANTIC_SECTION_MODELS` on, is a different kind of test: a structural
agreement check between `pipeline.normalize.entity`'s Pydantic models and `entity.schema.json`,
rather than an invariant of the schema file alone, and rather than an instance-level check against
a real `Entity`. It stays, alongside `pipeline.validate.conformance`'s instance check, because the
two catch different things and neither one subsumes the other. This comparison catches a field
renamed, added, or dropped on one side and forgotten on the other -- a drift an instance check
cannot see at all if the two sides happen to still agree on every instance this test process
builds. `pipeline.validate.conformance` catches the opposite failure: a correctly-declared field
whose *value* breaks the schema's own rules -- a `wikiUrl` that fails the pattern, a `sourceTiers`
key naming a field that does not exist -- which this structural comparison cannot see, because it
never inspects a value at all, only a declared shape.
"""

import json
import re
from typing import Any

import pytest
from pydantic import BaseModel

from pipeline.normalize.entity import (
    AdvancementInfo,
    BiomeInfo,
    BreedingInfo,
    ChestLoot,
    CollectionMember,
    CollectionMembers,
    CollectionTree,
    CompostInfo,
    DropTable,
    EffectSources,
    EnchantInfo,
    Entity,
    EntityKind,
    FoodInfo,
    FuelInfo,
    GenerationInfo,
    HarvestInfo,
    LinkList,
    ObtainList,
    ProfessionInfo,
    RecipeTree,
    SourceTier,
    SpawnInfo,
    StatBlock,
    StructureInfo,
    TradeTable,
)
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
    "FoodInfo",
    "HarvestInfo",
    "EffectSources",
    "AdvancementInfo",
    "TradeTable",
    "ChestLoot",
    "EnchantInfo",
    "GenerationInfo",
    "LinkList",
    "CollectionMembers",
    "CollectionTree",
    "ProfessionInfo",
    "StructureInfo",
    "BiomeInfo",
    "CompostInfo",
    "FuelInfo",
}

# `pipeline.normalize.entity.EntityKind` is the source of truth for this
# list, not CLAUDE.md -- CLAUDE.md documents phases and decisions, but it
# does not enumerate the kinds anywhere. `ENTITY` is the newest of the ten,
# added when `pipeline.normalize.merge` stopped mapping every `entity_type`
# registry ID onto `MOB` unconditionally; see that class's own docstring.
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
    "entity",
    "profession",
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
    assert SCHEMA_NAMES == ["atlas", "entity", "index", "manifest", "obtain", "shard"]


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
    # Phase 3's five real section payloads (`statBlock`, `spawnInfo`, `dropTable`,
    # `tradeTable`, `advancementInfo`) all reference `entityRef` now, through
    # fields like `itemRef` and `professionRef`, so no exception is needed for
    # it any more -- it is reached the same way every other shared `$def` is.
    unused = set(schema.get("$defs", {})) - used
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


# Keywords that compose several subschemas against the *same* JSON instance,
# rather than stepping down into a nested one. `entity.schema.json`'s D1
# conditional is a top-level `if` with `then: {"required": ["wikiUrl"]}`, and
# `then` declares no `properties` of its own -- `wikiUrl` is a property of the
# entity schema those branches all still describe, not of the branch. A
# `required` list found under one of these keywords is therefore checked
# against every `properties` block reachable through the composition, not only
# the properties declared on the same dict as the `required` list.
_COMPOSING_KEYWORDS = ("allOf", "anyOf", "oneOf", "if", "then", "else")


def _required_offenders(node: Any, declared: frozenset[str] = frozenset()) -> list[str]:
    """Return every `required` name under `node` that no reachable `properties` declares.

    `declared` carries the property names of the nearest enclosing schema that
    still describes the same instance as `node`. A plain object schema's own
    `properties` extends it; `allOf`/`anyOf`/`oneOf`/`if`/`then`/`else` pass it
    through unchanged, because those keywords do not change which instance is
    being validated. Any other key -- `properties`' own values, `items`,
    `$defs`, and so on -- steps into a different instance, so the search there
    starts over with nothing inherited: a nested object's `required` list has
    nothing to do with its parent's fields.
    """
    if isinstance(node, list):
        offenders: list[str] = []
        for item in node:
            offenders.extend(_required_offenders(item, declared))
        return offenders
    if not isinstance(node, dict):
        return []

    local_declared = declared | set(node.get("properties", {}))
    offenders = []
    required = node.get("required")
    if isinstance(required, list):
        offenders.extend(field for field in required if field not in local_declared)

    for key, value in node.items():
        if key in INSTANCE_KEYWORDS:
            continue
        if key in _COMPOSING_KEYWORDS:
            offenders.extend(_required_offenders(value, local_declared))
        elif key == "properties":
            for prop_schema in value.values():
                offenders.extend(_required_offenders(prop_schema))
        else:
            offenders.extend(_required_offenders(value))
    return offenders


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_required_name_is_a_declared_property(name: str) -> None:
    """A misspelled `required` entry fails in two directions at once.

    Both schemas close their objects with `additionalProperties: false`, so a
    required name that no `properties` block declares can never be supplied and
    the schema rejects every instance. The generator meanwhile drops the unknown
    name and marks the real field optional, so the web app compiles against a
    contract that the pipeline can no longer satisfy. Neither side names the
    typo.

    `_required_offenders` walks conditional composition (`allOf`/`if`/`then`/
    ...) as part of the same instance rather than as a nested schema, which
    `entity.schema.json`'s D1 conditional needs: its `then` branch requires
    `wikiUrl` without declaring `properties` of its own, because `wikiUrl` is
    already declared on the entity schema those keywords apply to.
    """
    assert _required_offenders(load_schema(name)) == []


def test_wiki_url_is_required_only_when_a_field_is_tier_b() -> None:
    """CLAUDE.md: "every entity keeps a `wikiUrl`" -- narrowed by decision D1.

    The wiki text is CC BY-NC-SA 3.0, so an entity that shows wiki-authored
    content without a link to its source page breaks the license. But real
    registry IDs have no wiki page at all, so `wikiUrl` cannot be
    unconditionally required. `entity.schema.json` instead requires it exactly
    when `sourceTiers` marks `blurb` or some `sections.*` key as Tier B,
    through a top-level `if`/`then`; this test pins that structure down so a
    future edit cannot quietly turn `wikiUrl` back into an unconditional
    requirement, or drop the conditional and lose it entirely.

    The `anyOf` has two branches on purpose and both are asserted below. An
    `icon` at Tier B triggers neither, because the sprites are Mojang's
    textures the wiki hosts rather than authored (Decision 3 of `TODO.md`) and
    the id-based icon route never reads a wiki article. Widening the condition
    back to "any Tier B field" made 7 live biome IDs impossible to build, so
    the branch list is the part that must not quietly grow.

    The keywords sit at the top level rather than inside an `allOf`, and the
    assertion below is what holds them there. Both spellings validate the same
    instances, so nothing about validation would notice the difference. The
    generator does: it renders an `allOf` member as an intersection with an
    open object, so the exported `Entity` becomes
    `{ [k: string]: unknown } & { ... }` and the web app loses the
    excess-property checking that `additionalProperties: false` exists to give
    it. A schema edit that reaches for `allOf` here fails this test rather than
    silently widening a type nobody reads.
    """
    schema = load_schema("entity")
    assert "wikiUrl" not in schema["required"]
    assert "sourceTiers" in schema["required"]
    assert "allOf" not in schema
    assert schema["if"]["required"] == ["sourceTiers"]
    assert schema["then"]["required"] == ["wikiUrl"]

    branches = schema["if"]["anyOf"]
    assert len(branches) == 2, "the trigger list must not grow without a reason recorded here"

    blurb_branch, sections_branch = branches
    tiers = blurb_branch["properties"]["sourceTiers"]
    assert tiers["required"] == ["blurb"]
    assert tiers["properties"]["blurb"] == {"const": "B"}

    # "not (every `sections.` key is not B)", i.e. at least one is B. JSON
    # Schema has no keyword that asks whether a map holds a value.
    patterned = sections_branch["properties"]["sourceTiers"]["not"]["patternProperties"]
    assert patterned == {"^sections\\.": {"not": {"const": "B"}}}


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


# --- Structural agreement: `pipeline.normalize.entity` vs `entity.schema.json` ---
#
# The module docstring explains why this is a structural comparison rather
# than an instance validation. `PYDANTIC_SECTION_MODELS` maps every section's
# schema `$defs` key to the Pydantic class that mirrors it, covering all 13
# union members; `REAL_SECTION_MODELS` narrows that to the five decision-D2
# sections whose schema definitions are closed (`additionalProperties: false`).

PYDANTIC_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "statBlock": StatBlock,
    "spawnInfo": SpawnInfo,
    "dropTable": DropTable,
    "recipeTree": RecipeTree,
    "obtainList": ObtainList,
    "breedingInfo": BreedingInfo,
    "foodInfo": FoodInfo,
    "harvestInfo": HarvestInfo,
    "effectSources": EffectSources,
    "advancementInfo": AdvancementInfo,
    "tradeTable": TradeTable,
    "chestLoot": ChestLoot,
    "enchantInfo": EnchantInfo,
    "generationInfo": GenerationInfo,
    "linkList": LinkList,
    "collectionMembers": CollectionMembers,
    "collectionTree": CollectionTree,
    "professionInfo": ProfessionInfo,
    "structureInfo": StructureInfo,
    "biomeInfo": BiomeInfo,
    "compostInfo": CompostInfo,
    "fuelInfo": FuelInfo,
}

# Decision D2's seven sections, plus `foodInfo` and `harvestInfo`: the schema closes these with
# `additionalProperties: false` and declares every field by name, so their
# property sets can be compared to the Pydantic side exactly, field for field.
REAL_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "statBlock": StatBlock,
    "spawnInfo": SpawnInfo,
    "dropTable": DropTable,
    "recipeTree": RecipeTree,
    "tradeTable": TradeTable,
    "advancementInfo": AdvancementInfo,
    "breedingInfo": BreedingInfo,
    "foodInfo": FoodInfo,
    "harvestInfo": HarvestInfo,
    "generationInfo": GenerationInfo,
    "enchantInfo": EnchantInfo,
    "professionInfo": ProfessionInfo,
    "chestLoot": ChestLoot,
    "linkList": LinkList,
    "collectionMembers": CollectionMembers,
    "collectionTree": CollectionTree,
    "structureInfo": StructureInfo,
    "biomeInfo": BiomeInfo,
    "compostInfo": CompostInfo,
    "fuelInfo": FuelInfo,
}


def _serialization_aliases(model: type[BaseModel]) -> set[str]:
    """Return the name each of `model`'s fields serializes under with `by_alias=True`.

    A field with no explicit `Field(alias=...)` serializes under its own
    Python name, so this falls back to the field name rather than requiring
    every field to declare a redundant alias identical to itself.
    """
    return {
        info.alias if info.alias is not None else name for name, info in model.model_fields.items()
    }


def _required_field_names(model: type[BaseModel]) -> set[str]:
    """Return the serialization alias of every field of `model` that has no default."""
    return {
        (info.alias if info.alias is not None else name)
        for name, info in model.model_fields.items()
        if info.is_required()
    }


def test_entity_top_level_properties_match_the_pydantic_fields() -> None:
    """A field added to one side and forgotten on the other must fail here."""
    schema_properties = set(load_schema("entity")["properties"])
    assert schema_properties == _serialization_aliases(Entity)


def test_entity_top_level_required_matches_the_pydantic_required_fields() -> None:
    """D1's conditional `wikiUrl` requirement is checked separately; this is the plain list."""
    schema_required = set(load_schema("entity")["required"])
    assert schema_required == _required_field_names(Entity)


def test_entity_kind_enum_matches_the_python_enum() -> None:
    schema = load_schema("entity")
    assert set(schema["$defs"]["entityKind"]["enum"]) == {member.value for member in EntityKind}


def test_source_tier_enum_matches_the_python_enum() -> None:
    schema = load_schema("entity")
    assert set(schema["$defs"]["sourceTier"]["enum"]) == {member.value for member in SourceTier}


def test_every_section_union_member_has_a_matching_pydantic_model() -> None:
    """`SECTION_TYPES` names 13 render blocks; `PYDANTIC_SECTION_MODELS` must cover all 13."""
    assert set(PYDANTIC_SECTION_MODELS) == {
        ref.removeprefix("#/$defs/") for ref in _refs(load_schema("entity")["$defs"]["section"])
    }


def test_section_type_constants_match_the_python_type_literals() -> None:
    """The schema's 13 `type` consts and the Python models' 13 `type` literal defaults agree."""
    schema = load_schema("entity")
    schema_constants = {
        schema["$defs"][def_name]["properties"]["type"]["const"]
        for def_name in PYDANTIC_SECTION_MODELS
    }
    python_literals = {
        model.model_fields["type"].default for model in PYDANTIC_SECTION_MODELS.values()
    }
    assert schema_constants == python_literals == SECTION_TYPES


@pytest.mark.parametrize("def_name", sorted(REAL_SECTION_MODELS))
def test_a_real_sections_declared_properties_match_its_pydantic_model(def_name: str) -> None:
    """For each of decision D2's five sections, the schema and the model declare the same fields."""
    schema_properties = set(load_schema("entity")["$defs"][def_name]["properties"])
    assert schema_properties == _serialization_aliases(REAL_SECTION_MODELS[def_name])


def test_collection_member_declared_properties_match_its_pydantic_model() -> None:
    schema_properties = set(load_schema("entity")["$defs"]["collectionMember"]["properties"])
    assert schema_properties == _serialization_aliases(CollectionMember)


def test_curated_chest_sources_completeness() -> None:
    from pipeline.obtain import ObtainError
    from pipeline.obtain.chests import (
        DEFAULT_CHEST_SOURCES_PATH,
        load_chest_sources,
        verify_chest_sources,
    )

    assert DEFAULT_CHEST_SOURCES_PATH.is_file()
    chests = load_chest_sources(DEFAULT_CHEST_SOURCES_PATH)
    assert len(chests) == 66

    valid_prefixes = (
        # `barrels` arrived in 26.3 with the Abandoned Camp. Its table is a
        # `minecraft:chest` like every other entry here, so it belongs in this
        # file rather than in `loot-sources.json`.
        "loot_table/barrels/",
        "loot_table/chests/",
        "loot_table/dispensers/",
        "loot_table/pots/",
        "loot_table/spawners/",
    )
    for path, entry in chests.items():
        assert any(path.startswith(prefix) for prefix in valid_prefixes)
        assert path.endswith(".json")
        assert entry.structure
        assert entry.structure[0].isupper()
        assert entry.container
        assert entry.container[0].isupper()

    # Completeness check: verifying against its own keys succeeds
    verify_chest_sources(chests.keys(), chests)

    # Missing table check: raises ObtainError
    with pytest.raises(ObtainError, match="found 1 chest loot tables with no curated entry"):
        verify_chest_sources(["loot_table/chests/unknown_mystery_chest.json"], chests)


def test_curated_loot_sources_completeness() -> None:
    from pipeline.obtain import ObtainError
    from pipeline.obtain.loot import (
        DEFAULT_LOOT_SOURCES_PATH,
        load_loot_sources,
        verify_loot_sources,
    )

    assert DEFAULT_LOOT_SOURCES_PATH.is_file()
    loot = load_loot_sources(DEFAULT_LOOT_SOURCES_PATH)
    assert len(loot) == 57

    for path, entry in loot.items():
        assert path.startswith("loot_table/")
        assert path.endswith(".json")
        assert entry.structure
        assert entry.structure[0].isupper()
        assert entry.container
        assert entry.container[0].isupper()

    # Completeness check: verifying against its own keys succeeds
    verify_loot_sources(loot.keys(), loot)

    # Missing table check: raises ObtainError
    with pytest.raises(ObtainError, match="found 1 loot tables with no curated entry"):
        verify_loot_sources(["loot_table/archaeology/unknown_arch.json"], loot)
