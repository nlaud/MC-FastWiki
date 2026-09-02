"""The `Entity` model, its discriminated `Section` union, and the `EntityDraft` builder.

`pipeline.normalize.entity` is the Python mirror of `pipeline/schema/
entity.schema.json`. Three things about it are worth testing on their own,
separately from the structural agreement test in `test_schema_contract.py`
that checks the two sides stay in sync:

* The `Section` union is discriminated, not a plain `Union` -- a dict with
  `type: "DropTable"` has to become a `DropTable` and nothing else, every
  time, or a renderer picks the wrong component for a real section.
* Decision D1 (`wikiUrl` required exactly when `sourceTiers` names Tier B for
  some field) is enforced here, in Python, at the point an `Entity` is
  actually built -- this pipeline never runs a JSON Schema validator, so this
  is the check that would actually catch a bad build, not the schema's copy
  of the same rule.
* `EntityDraft` is the only place a merge step is meant to write a field, and
  its whole reason to exist is that provenance is written in the same call as
  the value. A draft that could lose or fake provenance would defeat the
  point of having it as a type at all.
"""

import pytest
from pydantic import TypeAdapter

from pipeline.normalize import NormalizeError
from pipeline.normalize.entity import (
    DropTable,
    Entity,
    EntityDraft,
    EntityKind,
    ObtainList,
    Section,
    SourceTier,
    StatBlock,
)


def minimal_entity(**overrides: object) -> Entity:
    """Return a minimal valid `Entity`, with `overrides` layered on top.

    Every test below starts from a Tier-A-only entity with no wiki page, the
    `poplar_*` shape decision D1 exists to keep representable, and overrides
    only the fields the test cares about.
    """
    fields: dict[str, object] = {
        "id": "minecraft:creeper",
        "kind": EntityKind.MOB,
        "name": "Creeper",
        "aliases": (),
        "sourceTiers": {"name": SourceTier.A},
        "sections": (),
    }
    fields.update(overrides)
    return Entity.model_validate(fields)


# --- The discriminated `Section` union --------------------------------------


def test_a_drop_table_dict_parses_as_drop_table_and_nothing_else() -> None:
    """The `type` discriminator must pick exactly one member, not the first that fits.

    `isinstance(parsed, DropTable)` alone would also pass for a `dict` union
    member never narrowed at all, so this pins the type name down explicitly
    too, rather than relying only on the class check.
    """
    adapter: TypeAdapter[Section] = TypeAdapter(Section)
    parsed = adapter.validate_python({"type": "DropTable", "drops": []})
    assert isinstance(parsed, DropTable)
    assert parsed.type == "DropTable"
    assert type(parsed).__name__ == "DropTable"


def test_a_stat_block_dict_parses_as_stat_block() -> None:
    adapter: TypeAdapter[Section] = TypeAdapter(Section)
    parsed = adapter.validate_python({"type": "StatBlock"})
    assert isinstance(parsed, StatBlock)
    assert parsed.health == ()


def test_an_open_bag_section_keeps_its_extra_fields() -> None:
    """`ObtainList` and the other six still-open sections still accept `additionalProperties`.

    `RecipeTree` closed up when Phase 3's obtain tree landed -- see `pipeline.
    obtain.tree` and the `RecipeTree`/`RecipeTreeNode` models this module now
    declares -- so it is no longer one of the open bags this test covers.
    The rest have not been filled in yet, so a section like this arrives with
    whatever shape a later phase gives it, and `extra="allow"` has to keep
    that shape rather than dropping it.
    """
    adapter: TypeAdapter[Section] = TypeAdapter(Section)
    parsed = adapter.validate_python({"type": "ObtainList", "someFutureField": "kept"})
    assert isinstance(parsed, ObtainList)
    assert parsed.model_dump(by_alias=True)["someFutureField"] == "kept"


def test_an_unknown_type_value_is_refused() -> None:
    """A `type` the union does not name is a build-time fault, not a silent pass-through."""
    adapter: TypeAdapter[Section] = TypeAdapter(Section)
    with pytest.raises(Exception, match="type"):
        adapter.validate_python({"type": "NotASection"})


# --- Serialization: camelCase aliases ----------------------------------------


def test_serializing_by_alias_produces_the_schema_camel_case_keys() -> None:
    entity = minimal_entity(
        wikiUrl=None,
        sourceTiers={"name": SourceTier.A},
    )
    dumped = entity.model_dump(by_alias=True)
    assert set(dumped) == {
        "id",
        "kind",
        "name",
        "aliases",
        "icon",
        "blurb",
        "wikiUrl",
        "sourceTiers",
        "sections",
    }
    # No snake_case leaked through: `wiki_url` and `source_tiers` must be absent.
    assert "wiki_url" not in dumped
    assert "source_tiers" not in dumped


def test_a_nested_camel_case_alias_also_round_trips() -> None:
    """A field several levels deep, not just the top-level `Entity`, keeps its schema name."""
    entity = minimal_entity(
        sourceTiers={"name": SourceTier.A, "sections.StatBlock": SourceTier.B},
        wikiUrl="https://minecraft.wiki/w/Creeper",
        sections=(StatBlock(mob_type=("Monster",)),),
    )
    dumped = entity.model_dump(by_alias=True)
    assert dumped["sections"][0]["mobType"] == ("Monster",)
    assert "mob_type" not in dumped["sections"][0]


# --- Decision D1: `wikiUrl` required when wiki-*authored* content is shown ---


def test_a_tier_b_blurb_without_a_wiki_url_raises() -> None:
    """The wiki's own prose on screen with no link back is the license breach D1 guards."""
    with pytest.raises(NormalizeError, match="wiki-authored"):
        minimal_entity(sourceTiers={"blurb": SourceTier.B})


def test_a_tier_b_section_without_a_wiki_url_raises() -> None:
    """A section is a table the wiki compiled, so it carries the same obligation as prose."""
    with pytest.raises(NormalizeError, match="wiki-authored"):
        minimal_entity(sourceTiers={"sections.StatBlock": SourceTier.B})


def test_tier_b_provenance_with_a_wiki_url_is_accepted() -> None:
    entity = minimal_entity(
        sourceTiers={"blurb": SourceTier.B},
        wikiUrl="https://minecraft.wiki/w/Creeper",
        blurb="A creeper is a hostile mob.",
    )
    assert entity.wiki_url == "https://minecraft.wiki/w/Creeper"


def test_a_tier_b_icon_alone_does_not_require_a_wiki_url() -> None:
    """An icon is Mojang's texture that the wiki hosts, not content the wiki authored.

    Decision 3 of `TODO.md` records that position, and the id-based icon route
    makes it concrete: it reads the hyphenated registry path out of Tier A and
    consults no wiki article at all, so there is frequently no page to link
    to. Measured against the live 26.2 data on 2026-08-31, 7 biome IDs
    resolve an icon that way while the join table holds no row for them.
    Treating the icon as wiki-authored made all 7 impossible to build, which
    is the exact failure D1 exists to prevent.
    """
    entity = minimal_entity(
        sourceTiers={"name": SourceTier.A, "icon": SourceTier.B},
        icon="BiomeSprite:sunflower-plains",
    )
    assert entity.wiki_url is None


def test_a_tier_b_name_alone_does_not_require_a_wiki_url() -> None:
    """A display name is a fact the wiki transcribes, not prose it wrote.

    In practice a Tier B name and a `wikiUrl` arrive from the same
    `ResourceLocation` row, so this case does not occur in a real merge. It is
    pinned anyway, because the rule is stated in terms of which fields are
    wiki-*authored*, and `name` is not one of them.
    """
    entity = minimal_entity(sourceTiers={"name": SourceTier.B})
    assert entity.wiki_url is None


def test_tier_a_only_provenance_with_no_wiki_url_is_accepted() -> None:
    """The `poplar_*` shape decision D1 exists for: no Tier B field, no wiki page."""
    entity = minimal_entity(sourceTiers={"name": SourceTier.A, "icon": SourceTier.A})
    assert entity.wiki_url is None


def test_tier_c_only_provenance_with_no_wiki_url_is_also_accepted() -> None:
    """A curated override alone never triggers the wiki attribution requirement."""
    entity = minimal_entity(sourceTiers={"name": SourceTier.C})
    assert entity.wiki_url is None


# --- The alias validators ---------------------------------------------------


def test_an_alias_matching_the_name_casefolded_raises() -> None:
    with pytest.raises(NormalizeError, match="casefolded"):
        minimal_entity(aliases=("creeper",), name="Creeper")


def test_an_alias_matching_the_name_exactly_also_raises() -> None:
    with pytest.raises(NormalizeError, match="casefolded"):
        minimal_entity(aliases=("Creeper",), name="Creeper")


def test_an_empty_string_alias_raises() -> None:
    with pytest.raises(NormalizeError, match="empty string"):
        minimal_entity(aliases=("",))


def test_a_duplicate_alias_raises() -> None:
    with pytest.raises(NormalizeError, match="more than once"):
        minimal_entity(aliases=("creep", "creep"))


def test_clean_distinct_aliases_are_accepted() -> None:
    entity = minimal_entity(aliases=("creep", "sssh"))
    assert entity.aliases == ("creep", "sssh")


# --- The entity ID pattern validator -----------------------------------------


def test_an_id_with_no_namespace_separator_raises() -> None:
    with pytest.raises(NormalizeError, match="not a valid entity ID"):
        minimal_entity(id="Creeper")


def test_an_id_with_an_uppercase_namespace_raises() -> None:
    with pytest.raises(NormalizeError, match="not a valid entity ID"):
        minimal_entity(id="Minecraft:creeper")


def test_a_well_formed_id_is_accepted() -> None:
    entity = minimal_entity(id="collection:compostable")
    assert entity.id == "collection:compostable"


# --- The `sourceTiers` unknown-key validator ---------------------------------


def test_a_source_tiers_key_naming_no_real_field_raises() -> None:
    with pytest.raises(NormalizeError, match="does not declare"):
        minimal_entity(sourceTiers={"totallyMadeUp": SourceTier.A})


def test_a_section_type_source_tiers_key_is_accepted() -> None:
    entity = minimal_entity(
        sourceTiers={"name": SourceTier.A, "sections.DropTable": SourceTier.B},
        wikiUrl="https://minecraft.wiki/w/Creeper",
    )
    assert entity.source_tiers["sections.DropTable"] == SourceTier.B


def test_an_unknown_section_type_in_a_sections_key_raises() -> None:
    """`sections.NotASection` is not one of the thirteen real section types."""
    with pytest.raises(NormalizeError, match="does not declare"):
        minimal_entity(sourceTiers={"sections.NotASection": SourceTier.A})


# --- `EntityDraft` ------------------------------------------------------------


def test_entity_draft_set_records_provenance_for_every_field_it_writes() -> None:
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.set("icon", "zombie", SourceTier.A)
    draft.set("blurb", "A zombie is a hostile mob.", SourceTier.B)
    draft.set("wikiUrl", "https://minecraft.wiki/w/Zombie", SourceTier.B)
    entity = draft.build()
    assert entity.icon == "zombie"
    assert entity.blurb == "A zombie is a hostile mob."
    assert entity.source_tiers["icon"] == SourceTier.A
    assert entity.source_tiers["blurb"] == SourceTier.B
    assert entity.source_tiers["wikiUrl"] == SourceTier.B
    # `id`, `kind`, and `name` get their provenance at construction time.
    assert entity.source_tiers["id"] == SourceTier.A
    assert entity.source_tiers["kind"] == SourceTier.A
    assert entity.source_tiers["name"] == SourceTier.A


def test_entity_draft_set_rejects_an_unknown_field_name() -> None:
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    with pytest.raises(NormalizeError, match="does not know a field"):
        draft.set("madeUpField", "value", SourceTier.A)


def test_entity_draft_add_aliases_unions_rather_than_overwrites() -> None:
    """A second call must not lose what the first call already added."""
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.add_aliases(["zombie_boss"], SourceTier.A)
    draft.add_aliases(["zomb"], SourceTier.C)
    entity = draft.build()
    assert set(entity.aliases) == {"zombie_boss", "zomb"}


def test_entity_draft_add_aliases_records_the_highest_contributing_tier() -> None:
    """`sourceTiers["aliases"]` reflects the highest tier of any contributing alias."""
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.add_aliases(["zombie_boss"], SourceTier.A)
    entity = draft.build()
    assert entity.source_tiers["aliases"] == SourceTier.A

    draft.add_aliases(["zomb"], SourceTier.C)
    entity = draft.build()
    assert entity.source_tiers["aliases"] == SourceTier.C


def test_entity_draft_add_aliases_does_not_downgrade_the_recorded_tier() -> None:
    """A later, lower-tier alias must not overwrite an earlier higher-tier one's rank."""
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.add_aliases(["zomb"], SourceTier.C)
    draft.add_aliases(["zombie_boss"], SourceTier.A)
    entity = draft.build()
    assert set(entity.aliases) == {"zomb", "zombie_boss"}
    assert entity.source_tiers["aliases"] == SourceTier.C


def test_entity_draft_add_section_replaces_rather_than_duplicates_by_type() -> None:
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.add_section(StatBlock(mob_type=("Monster",)), SourceTier.B)
    draft.add_section(StatBlock(mob_type=("Monster", "Undead")), SourceTier.B)
    draft.set("wikiUrl", "https://minecraft.wiki/w/Zombie", SourceTier.B)
    entity = draft.build()
    assert len(entity.sections) == 1
    section = entity.sections[0]
    assert isinstance(section, StatBlock)
    assert section.mob_type == ("Monster", "Undead")
    assert entity.source_tiers["sections.StatBlock"] == SourceTier.B


def test_entity_draft_build_runs_the_d1_validator() -> None:
    """A draft that adds Tier B content but never sets `wikiUrl` must fail at `build`.

    `build` is the one place a merge step can still say which entity and
    which field caused the failure -- a draft is mutable and un-validated
    until then.
    """
    draft = EntityDraft(
        id="minecraft:zombie", kind=EntityKind.MOB, name="Zombie", tier=SourceTier.A
    )
    draft.add_section(StatBlock(mob_type=("Monster",)), SourceTier.B)
    with pytest.raises(NormalizeError, match="Tier B"):
        draft.build()
