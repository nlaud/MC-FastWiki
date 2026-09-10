"""The `Entity` model, and the discriminated `Section` union it carries.

`pipeline/schema/entity.schema.json` is the contract this module exists to
satisfy in Python. CLAUDE.md draws the line: the JSON Schema is what the web
app's TypeScript is generated from, and this module is what the merge stage
(Phase 3's remaining work, not this task) actually builds and validates
against before anything is written to `/data/dist`. The two describe the same
shape from two languages, and `tests/test_schema_contract.py`'s structural
agreement test is what keeps a field added on one side from going unnoticed
on the other.

## Two approved decisions, mirrored here exactly

**D1 -- `wikiUrl` is conditionally required.** Real registry IDs have no wiki
page at all, so `wikiUrl` cannot be an unconditional requirement without making
those IDs impossible to represent. The JSON Schema expresses the rule as a
top-level `if`/`then` and
`Entity._wiki_url_required_when_wiki_authored_content_is_shown` enforces the
identical rule in Python, which is the side that actually stops a bad build:
the pipeline constructs `Entity` instances directly and never round-trips
through a JSON Schema validator.

The trigger is wiki-*authored* content, which is narrower than "any Tier B
field", and the narrowing was forced by the live data rather than chosen for
convenience. `blurb` is the wiki's own prose and a section is a table the wiki
compiled, so either at Tier B requires the attribution link. An `icon` does
not, because Decision 3 of `TODO.md` records that the sprites are Mojang's
textures wherever they are fetched from -- the wiki hosts them, it did not
write them -- and because the id-based icon route reads the hyphenated
registry path out of Tier A without consulting a wiki article at all.
Measured against the live 26.2 data on 2026-08-31, 7 biome IDs resolve an icon
by that route and have no wiki page in the join table. Counting the icon as
wiki-authored would have demanded a link with nothing to point at and made
those seven impossible to build, which is the same failure the decision exists
to prevent, one tier further in.

**D2 -- seven sections carry real fields.** `StatBlock`, `SpawnInfo`,
`DropTable`, `TradeTable`, `AdvancementInfo`, `RecipeTree`, and `FoodInfo` are closed
models here, each mirroring one shape this pipeline already builds:
`pipeline.enrich.infobox.EntityInfobox`, `pipeline.enrich.spawn_table.
SpawnIndex.by_mob`, `pipeline.enrich.droptable.DropIndex.by_mob`, `pipeline.
enrich.trade.TradeIndex`, `pipeline.enrich.advancement.AdvancementTree`, and
`pipeline.obtain.tree.ObtainTree`, respectively. `RecipeTree` is the one
exception to "this pipeline already builds": no build stage ever constructs
one any more, only the shape it describes -- see `RecipeTree`'s own
docstring below for why the field stays fully specified here regardless.
`tests/test_schema_contract.py`'s `REAL_SECTION_MODELS` checks this module's
field names against the schema for all seven now, not six. The other seven
members of the `Section` union stay open bags (`model_config = ...
extra="allow"`), because the phase that fills each one has not run yet;
every one of their docstrings names the phase that will, matching the
schema's own updated descriptions.

## Why `Section` is `Annotated[..., Field(discriminator="type")]`

A plain `Union` asks pydantic to try every member in order and keep the first
one that validates, which is slow with fourteen members and, worse, ambiguous
for the eight open `extra="allow"` bags -- almost anything with a `type` field
would validate against several of them if pydantic had to guess. A
discriminated union reads `type` first and validates against exactly one
member, which is also the only reading that matches how the web app's
generated TypeScript already treats this field: a discriminator, not a
guess.

## The `name`/`ref` pattern, and why it repeats across three sections

`ItemAmount.ref`, `SpawnEntry.biome_ref`, `DropEntry.item_ref`, and
`TradeEntry.profession_ref` all share one shape: a display `name` that is
always present, because Tier B tables are keyed by the wiki's own display
name and not by registry ID, plus an optional `ref` that the merge fills in
only when it can resolve that name to a registry ID. Where `ref` is present a
renderer prints a link; where it is absent, it prints `name` as plain text.
`TODO.md`'s Phase 6 lint pass ("flag any renderer printing a known entity
name as plain text instead of a link") reads that absence as its signal, so
`ref` being optional is not a gap to be filled in later -- it is the data
this pipeline is supposed to produce for a name it genuinely could not
resolve.

## Field naming: explicit aliases, not `alias_generator`

The JSON Schema is camelCase (`wikiUrl`, `sourceTiers`, `mobType`); Python
convention is snake_case. Every model here uses `Field(alias="camelCase")` on
the handful of fields where the two differ, plus `populate_by_name=True` so a
caller can still construct one by its Python name. `Field(alias=...)` was
chosen over `alias_generator=to_camel` specifically because
`pyproject.toml` turns on the pydantic mypy plugin's
`warn_required_dynamic_aliases`: that option exists to catch exactly the
situation an `alias_generator` creates -- mypy cannot statically resolve a
generated alias, so it cannot check whether a required field's synthesized
`__init__` keyword is the field name or the alias, and it warns rather than
silently getting it wrong. A literal string alias has no such ambiguity, so
mypy resolves it without a warning, and every model uses the same mechanism
for the same reason -- there is no model here where a dynamic alias would
have been more convenient.

## Provenance is written where the value is written, never reconstructed

`EntityDraft` exists because a merge that writes a dozen fields and then
tries to reconstruct which tier produced each one, after the fact, is
guessing -- the tier that a merge step is currently reading from is a fact it
knows at that moment and nowhere else. `EntityDraft.set` and
`EntityDraft.add_aliases` both take the contributing tier as a required
argument and record it in the same call that writes the value, so there is no
code path that can write a field and forget its provenance.
"""

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pipeline.extract.harvest import HarvestTier, HarvestTool
from pipeline.normalize import NormalizeError

__all__ = [
    "ENTITY_ID_PATTERN",
    "AdvancementInfo",
    "ApplicableItems",
    "BiomeInfo",
    "BiomeSpawnEntry",
    "BreedingInfo",
    "BreedingItem",
    "ChestLoot",
    "ChestLootContainer",
    "ChestLootItem",
    "ConcentricRingsPlacement",
    "DamageValue",
    "DistributionEntry",
    "DropEntry",
    "DropNote",
    "DropTable",
    "EffectLink",
    "EffectSource",
    "EffectSources",
    "EnchantInfo",
    "EnchantRarity",
    "EnchantSlot",
    "Entity",
    "EntityDraft",
    "EntityKind",
    "EntityRef",
    "ExclusionZone",
    "FoodEffect",
    "FoodInfo",
    "GenerationInfo",
    "GenerationScope",
    "HarvestDrop",
    "HarvestGate",
    "HarvestInfo",
    "HarvestTier",
    "HarvestTool",
    "IntegerRange",
    "ItemAmount",
    "JavaProbability",
    "LabelledText",
    "LabelledValue",
    "LinkList",
    "LootingDrop",
    "Measure",
    "NoisePlacement",
    "ObtainList",
    "ProfessionInfo",
    "RandomSpreadPlacement",
    "Ratio",
    "RecipeTree",
    "RecipeTreeInput",
    "RecipeTreeNode",
    "RecipeTreeProducer",
    "Section",
    "SizeValue",
    "SourceTier",
    "SpawnEntry",
    "SpawnInfo",
    "StatBlock",
    "StructureInfo",
    "StructurePlacement",
    "StructureSibling",
    "StructureSpawnEntry",
    "TradeEntry",
    "TradeTable",
    "VeinInfo",
]

# Mirrors `pipeline.schema.entity.schema.json`'s `$defs.entityId.pattern`
# exactly. A namespaced identifier: `minecraft:creeper`, `collection:compostable`.
ENTITY_ID_PATTERN = re.compile(r"^[a-z0-9_-]+:[a-z0-9_./-]+$")


class SourceTier(StrEnum):
    """The tier that produced one field, mirroring the schema's `sourceTier`.

    A is vanilla game data from mcmeta, the completeness layer. B is the
    Minecraft Wiki, the presentation layer. C is a curated override, hand
    maintained where upstream has nothing or is wrong. The three are ordered
    A < B < C, and a later tier wins where two disagree on the same field --
    the same precedence CLAUDE.md states for the pipeline as a whole.
    """

    A = "A"
    B = "B"
    C = "C"


# The rank of each tier for the "a later tier wins" comparisons this module
# needs -- `EntityDraft.add_aliases` uses it to keep the highest tier that
# ever contributed a given alias. Kept as an explicit mapping rather than
# relying on enum declaration order staying meaningful, so a reordering of
# `SourceTier`'s members for some unrelated reason cannot silently invert it.
_TIER_RANK: Mapping[SourceTier, int] = {SourceTier.A: 0, SourceTier.B: 1, SourceTier.C: 2}


class EntityKind(StrEnum):
    """The discriminator of `Entity`, mirroring the schema's `entityKind` enum.

    Selects the renderer on the web side. CLAUDE.md documents this project's
    phases and decisions, but it does not actually enumerate the kinds
    anywhere -- a claim used to sit here that it did, and that claim was
    wrong regardless of how many members this class carried. This class and
    its mirror in `pipeline/schema/entity.schema.json` are the only source of
    truth for how many kinds there are and what each one is.

    There are ten now. `ENTITY` is the newest, added when `pipeline.
    normalize.merge` stopped mapping every `entity_type` registry ID onto
    `MOB` unconditionally. `pipeline.extract.entity_class.classify_entity_
    types` sorts each `entity_type` path into one of three classes from two
    Tier A signals -- a spawn egg item, an entity loot table -- and the merge
    stage demotes `entity_type` out of that ID's own registry precedence
    whenever neither signal applies, so a `block` or `item` registry
    membership wins the ID instead. `ENTITY` is what is left over: an
    `entity_type` ID with neither signal AND no other registry membership at
    all. Measured against the live 26.2 data on 2026-08-31, 23 IDs land here
    -- `experience_orb`, `lightning_bolt`, and `marker` among them.

    `ENTITY` is deliberately never the kind of anything that also has an item
    or a block form. `arrow` and every minecart keep `kind="item"`, and `tnt`
    keeps `kind="block"`, even though all three are also `entity_type` IDs --
    the demotion only ever lowers `entity_type`'s place in an ID's own
    precedence order, it never changes which registry wins when more than one
    still claims the ID after the demotion. An ID reaches `ENTITY` only when
    `entity_type` is demoted and nothing else was there to win in its place.
    """

    MOB = "mob"
    ITEM = "item"
    BLOCK = "block"
    EFFECT = "effect"
    ADVANCEMENT = "advancement"
    ENCHANTMENT = "enchantment"
    STRUCTURE = "structure"
    BIOME = "biome"
    COLLECTION = "collection"
    ENTITY = "entity"
    PROFESSION = "profession"


class EntityRef(BaseModel, frozen=True, populate_by_name=True):
    """A cross-reference to another entity, mirroring the schema's `entityRef`.

    A renderer never prints an entity name as plain text; it prints this
    object as a link. `id` follows the same `entityId` shape as `Entity.id`,
    validated here with a plain string pattern rather than
    `Entity`'s dedicated `NormalizeError`-raising validator, because an
    `EntityRef` is a value nested inside a larger model rather than the
    build's own unit of merge -- a malformed one is still a shape fault, and
    pydantic's own `ValidationError` names it precisely.
    """

    id: str = Field(pattern=ENTITY_ID_PATTERN.pattern)
    name: str = Field(min_length=1)


class Measure(BaseModel, frozen=True, populate_by_name=True):
    """A number, or a span of them, mirroring `pipeline.enrich.infobox.Measure`.

    A fixed value is a measure whose `minimum` equals its `maximum` -- every
    plain `{{hp|N}}` on the wiki produces one of these.
    """

    minimum: float
    maximum: float


class IntegerRange(BaseModel, frozen=True, populate_by_name=True):
    """A whole number, or a span of them, mirroring `pipeline.enrich.IntegerRange`.

    A wiki table cell such as a spawn group size or a trade quantity can be a
    single figure or a range, and this one shape covers both without a second
    field to check.
    """

    minimum: int
    maximum: int


class Ratio(BaseModel, frozen=True, populate_by_name=True):
    """An exact fraction, mirroring `pipeline.enrich.droptable.Ratio`.

    Kept as a numerator and a denominator rather than one float, because that
    is how the wiki states a drop chance or an average, and rounding it once
    here would be a loss no later stage could see or undo.
    """

    numerator: int
    denominator: int

    @property
    def value(self) -> float:
        """Return the fraction as a float, for a renderer that wants one."""
        return self.numerator / self.denominator


class LabelledText(BaseModel, frozen=True, populate_by_name=True):
    """Plain text read for a labelled variant, mirroring the infobox's own `LabelledText`.

    `StatBlock` reuses this one shape for `behavior`, `speed`, and
    `knockback_resistance` rather than declaring the same two fields three
    times.
    """

    labels: tuple[str, ...]
    text: str


class LabelledValue(BaseModel, frozen=True, populate_by_name=True):
    """A `Measure` read for a labelled variant of a mob.

    `StatBlock` reuses this one shape for `health` and `armor` rather than
    declaring the same two fields twice.
    """

    labels: tuple[str, ...]
    value: Measure


class ItemAmount(BaseModel, frozen=True, populate_by_name=True):
    """One item and how many, the shape a wiki drop or a trade side reduces to.

    See the module docstring's section on the `name`/`ref` pattern: `name` is
    always present because Tier B is keyed by display name, and `ref` is
    present only where the merge could resolve that name to a registry ID.
    """

    name: str = Field(min_length=1)
    ref: EntityRef | None = None
    quantity: IntegerRange
    note: str | None = None


# --- StatBlock ------------------------------------------------------------


class DamageValue(BaseModel, frozen=True, populate_by_name=True):
    """One damage figure, its variant, and the difficulty tier(s) it applies at.

    Mirrors `pipeline.enrich.infobox.DamageValue`. `difficulties` stays a
    tuple of plain strings rather than importing `infobox.Difficulty`,
    because this model mirrors the JSON contract -- which declares the field
    as an array of strings -- and not the enrich stage's own intermediate
    parsing types.
    """

    labels: tuple[str, ...]
    difficulties: tuple[str, ...]
    value: Measure


class SizeValue(BaseModel, frozen=True, populate_by_name=True):
    """One height/width pair, and the variant it describes.

    Mirrors `pipeline.enrich.infobox.SizeValue`.
    """

    labels: tuple[str, ...]
    height: float
    width: float


class StatBlock(BaseModel, frozen=True, populate_by_name=True):
    """Named numbers of an entity, mirroring `pipeline.enrich.infobox.EntityInfobox`.

    `speed` and `knockback_resistance` are carried here but deliberately not
    rendered, per `TODO.md` Phase 6 -- they are stored so a later renderer can
    use them without a pipeline change, not because today's renderer shows
    them.
    """

    type: Literal["StatBlock"] = "StatBlock"
    health: tuple[LabelledValue, ...] = ()
    damage: tuple[DamageValue, ...] = ()
    armor: tuple[LabelledValue, ...] = ()
    size: tuple[SizeValue, ...] = ()
    behavior: tuple[LabelledText, ...] = ()
    mob_type: tuple[str, ...] = Field(default=(), alias="mobType")
    speed: tuple[LabelledText, ...] = ()
    knockback_resistance: tuple[LabelledText, ...] = Field(default=(), alias="knockbackResistance")


# --- SpawnInfo --------------------------------------------------------------


class SpawnEntry(BaseModel, frozen=True, populate_by_name=True):
    """One mob spawning in one biome, at one weight.

    Mirrors `pipeline.enrich.spawn_table.SpawnEntry`. `biome_ref` follows the
    module docstring's `name`/`ref` pattern: present only where the merge
    resolved the wiki's biome name to a `worldgen/biome` registry ID.
    """

    biome: str
    biome_ref: EntityRef = Field(alias="biomeRef")
    category: str
    weight: float
    total_weight: float = Field(alias="totalWeight")
    group_size: IntegerRange = Field(alias="groupSize")
    note: str | None = None
    note_name: str | None = Field(default=None, alias="noteName")


class SpawnInfo(BaseModel, frozen=True, populate_by_name=True):
    """Where the entity spawns, and under which conditions.

    Mirrors `pipeline.enrich.spawn_table.SpawnIndex.by_mob`: one entry per
    biome the wiki records a Java spawn weight for.
    """

    type: Literal["SpawnInfo"] = "SpawnInfo"
    entries: tuple[SpawnEntry, ...] = ()


# --- DropTable ---------------------------------------------------------------


class DropNote(BaseModel, frozen=True, populate_by_name=True):
    """One condition on a drop, as wikitext. Mirrors `pipeline.enrich.droptable.DropNote`."""

    name: str | None = None
    content: str


class DistributionEntry(BaseModel, frozen=True, populate_by_name=True):
    """One `{count, chance}` pair of a `LootingDrop.distribution`.

    The schema represents `pipeline.enrich.droptable.LootingDrop.distribution`
    -- a `Mapping[int, Ratio]` on the Python enrich side -- as an array of
    these pairs sorted by `count` rather than as a JSON object keyed by the
    count, because a JSON object key must be a string and a numeric-looking
    string key such as `"10"` is exactly the kind of value that sorts wrong
    the moment something reads it as text instead of as a number. See
    `pipeline/schema/entity.schema.json`'s `lootingDrop` definition for the
    same reasoning on the schema side.
    """

    count: int
    chance: Ratio


class LootingDrop(BaseModel, frozen=True, populate_by_name=True):
    """What one mob drops of one item at one looting level.

    Mirrors `pipeline.enrich.droptable.LootingDrop`, with `distribution`
    reshaped as `DistributionEntry`'s docstring explains.
    """

    looting_level: int = Field(alias="lootingLevel")
    minimum: int
    maximum: int
    average: Ratio
    drop_chance: Ratio = Field(alias="dropChance")
    quantity_text: str = Field(alias="quantityText")
    distribution: tuple[DistributionEntry, ...] = ()


class DropEntry(BaseModel, frozen=True, populate_by_name=True):
    """What one mob drops of one item, across every looting level the wiki records.

    `item_ref` follows the module docstring's `name`/`ref` pattern.
    """

    item: str
    item_ref: EntityRef | None = Field(default=None, alias="itemRef")
    notes: tuple[DropNote, ...] = ()
    by_looting_level: tuple[LootingDrop, ...] = Field(default=(), alias="byLootingLevel")


class DropTable(BaseModel, frozen=True, populate_by_name=True):
    """What the entity drops, per looting level.

    Mirrors `pipeline.enrich.droptable.DropIndex.by_mob`. Java only, per
    non-negotiable 1 of CLAUDE.md.
    """

    type: Literal["DropTable"] = "DropTable"
    drops: tuple[DropEntry, ...] = ()


# --- TradeTable --------------------------------------------------------------


class JavaProbability(BaseModel, frozen=True, populate_by_name=True):
    """How likely a trade is to be offered, mirroring `pipeline.enrich.trade.Probability`.

    Only the Java figure is carried through the merge at all -- see
    `TradeEntry`'s docstring.
    """

    text: str
    low: float
    high: float


class TradeEntry(BaseModel, frozen=True, populate_by_name=True):
    """One trade a profession offers at one level.

    Mirrors `pipeline.enrich.trade.WikiTrade`. `profession_ref` links to
    the profession entity where one exists (for the 13 villager professions).
    Only `java_probability` is carried; `bedrock_probability` is dropped upstream
    in `pipeline.enrich.trade`, per non-negotiable 1 of CLAUDE.md.
    """

    profession: str
    profession_ref: EntityRef | None = Field(default=None, alias="professionRef")
    level: str
    wanted: tuple[ItemAmount, ...] = ()
    given: ItemAmount
    java_probability: JavaProbability | None = Field(default=None, alias="javaProbability")
    max_trades: IntegerRange | None = Field(default=None, alias="maxTrades")
    villager_xp: int | None = Field(default=None, alias="villagerXp")
    price_multiplier: float | None = Field(default=None, alias="priceMultiplier")


class TradeTable(BaseModel, frozen=True, populate_by_name=True):
    """Villager and wandering trader trades, grouped by profession and level.

    Mirrors `pipeline.enrich.trade.TradeIndex`.
    """

    type: Literal["TradeTable"] = "TradeTable"
    trades: tuple[TradeEntry, ...] = ()


# --- AdvancementInfo -----------------------------------------------------


class AdvancementInfo(BaseModel, frozen=True, populate_by_name=True):
    """How the player earns an advancement, and the parent chain.

    Mirrors `pipeline.enrich.advancement.WikiAdvancement`, with `parent`
    resolved to an `EntityRef` where the merge can, alongside the raw
    `parent_title` the wiki wrote -- `WikiAdvancement`'s own docstring gives
    the reason a title that resolves to nothing is worth keeping rather than
    hiding.
    """

    type: Literal["AdvancementInfo"] = "AdvancementInfo"
    internal_id: str = Field(alias="internalId")
    title: str
    description: str | None = None
    game_description: str | None = Field(default=None, alias="gameDescription")
    parent: EntityRef | None = None
    parent_title: str | None = Field(default=None, alias="parentTitle")
    children: tuple[EntityRef, ...] = ()
    experience: int | None = None
    reward: str | None = None
    background: str | None = None


# --- The eight sections whose payload arrives in a later phase -------------
#
# Each carries only its own `type` discriminator today and accepts any other
# keys (`extra="allow"`), mirroring the schema's `additionalProperties: true`
# for these members. Every docstring names the phase that replaces the open
# payload with real fields, matching the schema's own updated descriptions.


class RecipeTreeInput(BaseModel, frozen=True, populate_by_name=True):
    """One ingredient slot of a `RecipeTreeProducer`, mirroring `pipeline.obtain.tree.TreeInput`.

    **No build stage constructs this model any more.** The pipeline used to
    walk `pipeline.obtain.tree.build_obtain_tree`'s output into a `RecipeTree`
    and write it into every entity's own shard; measured against the real
    26.2 data that cost 73.8 MB raw and 4.1 MB gzipped for a tree capped at
    depth 4, against 1.05 MB raw and 0.07 MB gzipped for the flat producer
    graph the pipeline ships instead -- `pipeline.emit.obtain`'s module
    docstring has the full comparison, including that the graph carries
    strictly *more* depth than the tree ever did (the deepest real chain is
    15 levels, past any depth-4 cap). So this model, and its three siblings
    below, are no longer something a merge stage builds; they are the shape
    the web app assembles at render time by walking `obtain.json`, using
    `pipeline.obtain.tree.build_obtain_tree` as the reference implementation
    of how to do it. They stay in the `Section` union, fully specified,
    because the renderer's assembled tree still needs a name for its own
    shape, and `entity.schema.json`'s generated TypeScript still needs to
    describe that shape to the web app -- removing these four models would
    not shrink `data/dist` by a single byte (nothing here was writing to it
    any more) and would only cost the web app its generated type.

    `item` is present for a plain item input (and absent for a tag input);
    `tag` is present for a tag input and absent otherwise -- the same
    `name`/`ref`-adjacent shape the module docstring of `pipeline.normalize.
    entity` already uses elsewhere, except here the raw id (`label`) is
    always present because an obtain-tree ingredient, unlike a Tier B row,
    is already a registry id rather than a wiki display name. `node` is the
    recursive expansion of `item`, absent for a tag input, an untagged
    alternatives list (`members` still carries the full list), or a
    cycle-dropped repeat -- see `pipeline.obtain.tree`'s own docstring for
    why those three cases all leave it unset.
    """

    label: str
    item: EntityRef | None = None
    tag: str | None = None
    count: int = 1
    members: tuple[str, ...] = ()
    node: "RecipeTreeNode | None" = None


class RecipeTreeProducer(BaseModel, frozen=True, populate_by_name=True):
    """One way to get a node's item, mirroring `pipeline.obtain.producer.Producer`.

    See `RecipeTreeInput`'s own docstring for why no build stage constructs
    this model any more, and what still fills its place in `data/dist`.
    """

    method: str
    station: str | None = None
    note: str | None = None
    source_id: str = Field(alias="sourceId")
    inputs: tuple[RecipeTreeInput, ...] = ()


class RecipeTreeNode(BaseModel, frozen=True, populate_by_name=True):
    """One item of the obtain tree, mirroring `pipeline.obtain.tree.ObtainNode`.

    See `RecipeTreeInput`'s own docstring for why no build stage constructs
    this model any more, and what still fills its place in `data/dist`.
    `expandable` marks a depth-cap stub: a renderer assembling this shape
    from `obtain.json` continues the walk by opening `item`'s own entity
    shard. `back_reference` marks a repeated-subtree collapse: the path of
    the node where this same subtree was first rendered in this tree. See
    `pipeline.obtain.tree`'s own docstring for the four rules that decide
    between these two and an ordinary, fully expanded node -- the same four
    rules a renderer has to apply to get this shape right.
    """

    item: EntityRef
    producers: tuple[RecipeTreeProducer, ...] = ()
    expandable: bool = False
    back_reference: str | None = Field(default=None, alias="backReference")


RecipeTreeInput.model_rebuild()


class RecipeTree(BaseModel, frozen=True, populate_by_name=True):
    """The obtain tree of an item, rooted at `root`. Brewing is a node of this tree.

    Mirrors `pipeline.obtain.tree.ObtainTree`. See `RecipeTreeInput`'s own
    docstring for why no build stage constructs one of these any more: the
    pipeline writes `data/dist/obtain.json`, a flat `pipeline.obtain.
    producer.ProducerIndex` assembled out of every adapter of `pipeline.
    obtain` -- crafting and smelting recipes, block and chest loot, mob
    drops, trades, and brewing -- and the web app walks that file into this
    exact shape at render time, using `pipeline.obtain.tree.
    build_obtain_tree` as its reference implementation.
    """

    type: Literal["RecipeTree"] = "RecipeTree"
    root: RecipeTreeNode


class ObtainList(BaseModel, frozen=True, populate_by_name=True, extra="allow"):
    """Every acquisition path that the wiki Obtaining section lists.

    The payload of this section arrives in Phase 6b, scraped from the wiki's
    own Obtaining section.
    """

    type: Literal["ObtainList"] = "ObtainList"


class BreedingItem(BaseModel, frozen=True, populate_by_name=True):
    """One breeding or taming item, following the name/ref pattern."""

    name: str = Field(min_length=1)
    ref: EntityRef | None = None


class BreedingInfo(BaseModel, frozen=True, populate_by_name=True):
    """The items that breed a mob, its taming requirements, and its timings.

    Mirrors `pipeline.enrich.breeding.BreedingIndex`. The two timings are
    carried as seconds rather than as display strings so the renderer formats
    them and never has to infer them from the food list.
    """

    type: Literal["BreedingInfo"] = "BreedingInfo"
    items: tuple[BreedingItem, ...] = ()
    requires_taming: bool = Field(default=False, alias="requiresTaming")
    taming_items: tuple[BreedingItem, ...] = Field(default=(), alias="tamingItems")
    cooldown_seconds: int = Field(default=300, ge=0, alias="cooldownSeconds")
    baby_growth_seconds: int = Field(default=1200, ge=0, alias="babyGrowthSeconds")


class EffectLink(BaseModel, frozen=True, populate_by_name=True):
    """One status effect a food section names, following the name/ref pattern."""

    name: str = Field(min_length=1)
    ref: EntityRef | None = None


class FoodEffect(BaseModel, frozen=True, populate_by_name=True):
    """One status effect that eating an item applies.

    `duration_ticks` and `level` are carried raw rather than as display strings,
    for the same reason `BreedingInfo` carries seconds: the renderer is the one
    place that knows how a duration and a level should read on screen. `level`
    is 1-based here even though `pipeline.extract.food.AppliedEffect.amplifier`
    is 0-based, because the schema is what the web reads and "Regeneration II"
    is level 2, not amplifier 1. The conversion happens once, in
    `pipeline.normalize.merge`, rather than in every reader.

    `probability` is the chance of the whole `apply_effects` group the source
    put this effect in, copied onto each effect of that group. Three items in
    26.2 carry one below 1.0.
    """

    name: str = Field(min_length=1)
    ref: EntityRef | None = None
    duration_ticks: int = Field(ge=0, alias="durationTicks")
    level: int = Field(ge=1)
    probability: float = Field(gt=0.0, le=1.0)


class FoodInfo(BaseModel, frozen=True, populate_by_name=True):
    """What eating an item restores, and what else it does.

    Mirrors `pipeline.extract.food.FoodFacts`, flattened into the four things a
    page shows. `nutrition` and `saturation` are `None` together for an item
    that is consumable without being food -- the milk bucket restores nothing
    and still clears every effect -- and a renderer reads that pair to decide
    whether it is drawing a `Food` block or a `Consuming` one.

    The three payload-free consume effects become two booleans and a list
    rather than a fourth kind of row, because `clear_all_effects` and
    `teleport_randomly` each say one whole thing and carry nothing else.
    `play_sound` has no counterpart here at all: it is parsed by the extract so
    that an unknown type still raises, and then dropped, because a sound is not
    something an item page can show. The one item whose only consume effect is
    a sound, `ominous_bottle`, therefore gets no section.
    """

    type: Literal["FoodInfo"] = "FoodInfo"
    nutrition: int | None = None
    saturation: float | None = None
    can_always_eat: bool = Field(default=False, alias="canAlwaysEat")
    effects: tuple[FoodEffect, ...] = ()
    removes: tuple[EffectLink, ...] = ()
    clears_all_effects: bool = Field(default=False, alias="clearsAllEffects")
    teleports_randomly: bool = Field(default=False, alias="teleportsRandomly")


HarvestGate = Literal["silk_touch", "shears"]


class HarvestDrop(BaseModel, frozen=True, populate_by_name=True):
    """An item dropped when this block is broken.

    `gate` indicates whether this drop requires a special tool or enchantment
    such as Silk Touch or shears.
    """

    id: str
    name: str | None = None
    count: int = 1
    gate: HarvestGate | None = None


class HarvestInfo(BaseModel, frozen=True, populate_by_name=True):
    """What tool and tier are needed to harvest a block.

    Carries the tool list in the order of `HarvestTool`, the material floor tier
    from `HarvestTier`, whether breaking the block without the right tool
    still drops itself, and what the block drops when broken.
    """

    type: Literal["HarvestInfo"] = "HarvestInfo"
    tools: tuple[HarvestTool, ...] = ()
    tier: HarvestTier
    drops_without_tool: bool = Field(default=False, alias="dropsWithoutTool")
    drops: tuple[HarvestDrop, ...] = ()


class EffectSource(BaseModel, frozen=True, populate_by_name=True):
    """One source that grants or inflicts a status effect."""

    name: str = Field(min_length=1)
    ref: EntityRef | None = None
    qualifier: str | None = None
    potency: str | None = None
    length: str | None = None
    note: str | None = None


class EffectSources(BaseModel, frozen=True, populate_by_name=True):
    """Every source of a status effect, its category, and what it does."""

    type: Literal["EffectSources"] = "EffectSources"
    category: Literal["positive", "negative", "neutral"]
    behaviour: str | None = None
    sources: tuple[EffectSource, ...] = ()
    removed_by: tuple[EffectLink, ...] = Field(default=(), alias="removedBy")


class ChestLootItem(BaseModel, frozen=True, populate_by_name=True):
    """One item appearing in a chest or container table."""

    item: EntityRef
    chance: float
    stack_range: IntegerRange = Field(alias="stackRange")


class ChestLootContainer(BaseModel, frozen=True, populate_by_name=True):
    """One container (chest, barrel, dispenser, pot, vault) within a structure."""

    label: str
    items: tuple[ChestLootItem, ...] = ()


class ChestLoot(BaseModel, frozen=True, populate_by_name=True):
    """The loot tables and containers that generate inside a structure."""

    type: Literal["ChestLoot"] = "ChestLoot"
    containers: tuple[ChestLootContainer, ...] = ()


EnchantSlot = Literal[
    "any",
    "armor",
    "feet",
    "hand",
    "head",
    "legs",
    "mainhand",
    "offhand",
]

EnchantRarity = Literal["common", "uncommon", "rare", "very_rare"]


class ApplicableItems(BaseModel, frozen=True, populate_by_name=True):
    """The group of items an enchantment can be applied to."""

    group: str = Field(min_length=1)
    items: tuple[EntityRef, ...] = ()


class EnchantInfo(BaseModel, frozen=True, populate_by_name=True):
    """Levels, applicable items, costs, and the exclusive set.

    Carries max level, anvil cost, table cost ranges, applicable items, exclusive
    set, and classification flags (treasure, curse, tradeable).
    """

    type: Literal["EnchantInfo"] = "EnchantInfo"
    max_level: int = Field(ge=1, le=5, alias="maxLevel")
    weight: int = Field(ge=1)
    rarity: EnchantRarity
    anvil_cost: int = Field(ge=0, alias="anvilCost")
    slots: tuple[EnchantSlot, ...] = ()
    cost_ranges: tuple[IntegerRange, ...] = Field(alias="costRanges")
    supported_items: ApplicableItems = Field(alias="supportedItems")
    primary_items: ApplicableItems | None = Field(default=None, alias="primaryItems")
    exclusive_set: tuple[EntityRef, ...] = Field(default=(), alias="exclusiveSet")
    treasure: bool = False
    curse: bool = False
    tradeable: bool = True


class VeinInfo(BaseModel, frozen=True, populate_by_name=True):
    """One placed feature's contribution to a block's generation in one dimension.

    `min_y` and `max_y` are absent together for a feature placed on a heightmap,
    which states a surface rather than a band, and `surface` is what a renderer
    reads to say so. `tries` is present only where the placement states a
    per-chunk attempt count; `pipeline.extract.generation` explains which counts
    qualify and which are patch density.
    """

    feature: str
    min_y: int | None = Field(default=None, alias="minY")
    max_y: int | None = Field(default=None, alias="maxY")
    surface: bool = False
    densest_y: int | None = Field(default=None, alias="densestY")
    tries: int | float | None = None
    chunk_chance: int | None = Field(default=None, alias="chunkChance")
    vein_size: int | None = Field(default=None, alias="veinSize")


class GenerationScope(BaseModel, frozen=True, populate_by_name=True):
    """How one block generates in one dimension."""

    dimension: str
    min_y: int | None = Field(default=None, alias="minY")
    max_y: int | None = Field(default=None, alias="maxY")
    densest_y: int | None = Field(default=None, alias="densestY")
    surface_only: bool = Field(default=False, alias="surfaceOnly")
    attempts_per_chunk: int | float | None = Field(default=None, alias="attemptsPerChunk")
    biome_count: int = Field(alias="biomeCount")
    all_biomes_of_dimension: bool = Field(alias="allBiomesOfDimension")
    biomes: tuple[EntityRef, ...] = ()
    veins: tuple[VeinInfo, ...] = ()


class GenerationInfo(BaseModel, frozen=True, populate_by_name=True):
    """Where a block, a structure, or a biome generates.

    One scope per dimension the block generates in, rather than one dimension for
    the whole block. Gravel and the two mushrooms generate in the overworld and
    the nether at once, and every field of a scope -- the band, the attempts, the
    biomes -- is a fact about one dimension, so folding two worlds into one row
    would state a band that exists in neither.
    """

    type: Literal["GenerationInfo"] = "GenerationInfo"
    scopes: tuple[GenerationScope, ...] = ()


class LinkList(BaseModel, frozen=True, populate_by_name=True):
    """A plain list of links to other entities."""

    type: Literal["LinkList"] = "LinkList"
    title: str | None = None
    links: tuple[EntityRef, ...] = ()


class ProfessionInfo(BaseModel, frozen=True, populate_by_name=True):
    """Villager profession details: workstation block and trade count."""

    type: Literal["ProfessionInfo"] = "ProfessionInfo"
    workstation: EntityRef | None = Field(default=None)
    trade_count: int = Field(ge=0, alias="tradeCount")


class ExclusionZone(BaseModel, frozen=True, populate_by_name=True):
    """An area around another structure set where this structure cannot place."""

    other_set: str = Field(alias="otherSet")
    chunk_count: int = Field(alias="chunkCount")


class RandomSpreadPlacement(BaseModel, frozen=True, populate_by_name=True):
    """Placement across the world with spacing and separation."""

    type: Literal["minecraft:random_spread"] = "minecraft:random_spread"
    spacing: int
    separation: int
    spread_type: str | None = Field(default=None, alias="spreadType")
    frequency: float | None = None
    frequency_reduction_method: str | None = Field(default=None, alias="frequencyReductionMethod")
    exclusion_zone: ExclusionZone | None = Field(default=None, alias="exclusionZone")
    salt: int | None = None


class ConcentricRingsPlacement(BaseModel, frozen=True, populate_by_name=True):
    """Placement in concentric rings around the world origin (e.g. Strongholds)."""

    type: Literal["minecraft:concentric_rings"] = "minecraft:concentric_rings"
    count: int
    distance: int
    spread: int
    preferred_biomes: str = Field(alias="preferredBiomes")
    salt: int | None = None


StructurePlacement = Annotated[
    RandomSpreadPlacement | ConcentricRingsPlacement,
    Field(discriminator="type"),
]


class StructureSibling(BaseModel, frozen=True, populate_by_name=True):
    """Another structure belonging to the same structure set, with its relative weight."""

    structure: EntityRef
    weight: int


class StructureSpawnEntry(BaseModel, frozen=True, populate_by_name=True):
    """One mob spawn override inside a structure bounding box."""

    category: str
    mob: EntityRef
    group_size: IntegerRange = Field(alias="groupSize")
    weight: int


class StructureInfo(BaseModel, frozen=True, populate_by_name=True):
    """Where and how a structure generates, its siblings, mob spawns, and suppressed spawns."""

    type: Literal["StructureInfo"] = "StructureInfo"
    dimension: Literal["overworld", "nether", "end"]
    step: str
    biomes: tuple[EntityRef, ...] = ()
    placement: StructurePlacement
    siblings: tuple[StructureSibling, ...] = ()
    spawns: tuple[StructureSpawnEntry, ...] = ()
    suppressed_spawns: tuple[str, ...] = Field(default=(), alias="suppressedSpawns")


class BiomeSpawnEntry(BaseModel, frozen=True, populate_by_name=True):
    """One mob spawning in a biome, at a given weight and group size."""

    category: str
    mob: EntityRef
    group_size: IntegerRange = Field(alias="groupSize")
    weight: int
    total_weight: int = Field(alias="totalWeight")
    note: str | None = None
    note_name: str | None = Field(default=None, alias="noteName")


class NoisePlacement(BaseModel, frozen=True, populate_by_name=True):
    """One noise climate placement rule for an Overworld biome."""

    route: Literal["depth", "non_inland", "direct_inland", "group", "group_terrain"]
    group: str | None = None
    temperature: str | None = None
    humidity: str | None = None
    continentalness: str | None = None
    erosion: str | None = None
    weirdness: str | None = None
    pv: str | None = None
    depth: str | None = None
    additional_requirement: str | None = Field(default=None, alias="additionalRequirement")
    condition: str | None = None
    sibling: EntityRef | None = None


class BiomeInfo(BaseModel, frozen=True, populate_by_name=True):
    """Climate, mob spawns, and generating blocks of a biome."""

    type: Literal["BiomeInfo"] = "BiomeInfo"
    # Absent where no dimension tag lists the biome, which in 26.2 is `the_void`
    # alone. See `pipeline.extract.biome.extract_biomes` for why that is stated as
    # nothing rather than defaulted to the overworld.
    dimension: Literal["overworld", "nether", "end"] | None = None
    temperature: float
    temperature_modifier: str | None = Field(default=None, alias="temperatureModifier")
    downfall: float
    has_precipitation: bool = Field(alias="hasPrecipitation")
    precipitation: Literal["rain", "snow", "none"]
    creature_spawn_probability: float | None = Field(
        default=None, alias="creatureSpawnProbability"
    )
    spawn_costs: Mapping[str, Mapping[str, float]] = Field(default_factory=dict, alias="spawnCosts")
    spawns: tuple[BiomeSpawnEntry, ...] = ()
    blocks: tuple[EntityRef, ...] = ()
    common_blocks_count: int = Field(default=0, alias="commonBlocksCount")
    noise_placements: tuple[NoisePlacement, ...] = Field(
        default=(), alias="noisePlacements"
    )


# The discriminated union. See the module docstring for why `discriminator`
# rather than a plain `Union`.
Section = Annotated[
    StatBlock
    | SpawnInfo
    | DropTable
    | RecipeTree
    | ObtainList
    | BreedingInfo
    | FoodInfo
    | HarvestInfo
    | EffectSources
    | AdvancementInfo
    | TradeTable
    | ChestLoot
    | EnchantInfo
    | GenerationInfo
    | LinkList
    | ProfessionInfo
    | StructureInfo
    | BiomeInfo,
    Field(discriminator="type"),
]


# The Entity fields a `sourceTiers` key may legitimately name, beyond a
# `sections.<Type>` key -- see `Entity._every_source_tier_key_names_something_real`.
# Kept separate from `Entity.model_fields` itself rather than computed from it,
# because `sourceTiers` and `sections` are never themselves the *subject* of a
# provenance entry -- a provenance map does not describe its own presence, and
# a whole section's provenance is recorded under `sections.<Type>`, not under
# the literal key `"sections"`.
_PROVENANCE_FIELDS = frozenset({"id", "kind", "name", "aliases", "icon", "blurb", "wikiUrl"})

# The eighteen `type` values a `sections.<Type>` provenance key may name,
# matching `tests/test_schema_contract.py`'s `SECTION_TYPES` and this module's
# own `Section` union members exactly.
_SECTION_TYPES = frozenset(
    {
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
        "ProfessionInfo",
        "StructureInfo",
        "BiomeInfo",
    }
)

_VALID_PROVENANCE_KEYS = _PROVENANCE_FIELDS | {
    f"sections.{section_type}" for section_type in _SECTION_TYPES
}


class Entity(BaseModel, frozen=True, populate_by_name=True):
    """One searchable thing, mirroring `pipeline/schema/entity.schema.json`.

    Every field name below has a camelCase alias where it differs from its
    schema counterpart; see the module docstring's naming section for why
    that is an explicit `Field(alias=...)` rather than an `alias_generator`.
    """

    id: str
    kind: EntityKind
    name: str
    aliases: tuple[str, ...]
    icon: str | None = None
    blurb: str | None = None
    wiki_url: str | None = Field(default=None, alias="wikiUrl")
    source_tiers: Mapping[str, SourceTier] = Field(alias="sourceTiers")
    sections: tuple[Section, ...]

    @field_validator("id")
    @classmethod
    def _id_matches_the_entity_id_pattern(cls, value: str) -> str:
        """Refuse an ID that is not `<namespace>:<path>`, lowercase.

        `pipeline/schema/entity.schema.json`'s `$defs.entityId.pattern` states
        the same rule for the web side; this is the pipeline side's copy of
        it, checked at the point an `Entity` is actually built rather than
        only at JSON-Schema-validation time, which this pipeline never runs.
        """
        if not ENTITY_ID_PATTERN.fullmatch(value):
            raise NormalizeError(
                f"{value!r} is not a valid entity ID. An entity ID is a namespace and a path, "
                f"lowercase, matching {ENTITY_ID_PATTERN.pattern!r} -- 'minecraft:creeper' and "
                f"'collection:compostable' are both valid, a bare display name is not."
            )
        return value

    @model_validator(mode="after")
    def _aliases_are_clean(self) -> "Entity":
        """Refuse an alias list that wastes a Phase 4 search index slot.

        An alias that repeats the entity's own name (casefolded, so `Creeper`
        and `creeper` both count) is matched by the name already, so keeping
        it doubles an index entry for nothing. An empty string matches every
        query prefix, which would make every search return everything. A
        duplicate wastes the same slot twice. All three are refused here
        rather than silently deduplicated, because a merge step that produced
        one of them has a bug worth surfacing, not smoothing over.
        """
        casefolded_name = self.name.casefold()
        seen: set[str] = set()
        for alias in self.aliases:
            if not alias:
                raise NormalizeError(f"{self.id!r} carries an empty string as an alias.")
            if alias.casefold() == casefolded_name:
                raise NormalizeError(
                    f"{self.id!r} carries {alias!r} as an alias, which is its own name "
                    f"({self.name!r}) casefolded. The name is already matched directly; "
                    f"repeating it as an alias only doubles the Phase 4 search index."
                )
            if alias in seen:
                raise NormalizeError(f"{self.id!r} carries the alias {alias!r} more than once.")
            seen.add(alias)
        return self

    @field_validator("source_tiers")
    @classmethod
    def _every_source_tier_key_names_something_real(
        cls, value: Mapping[str, SourceTier]
    ) -> Mapping[str, SourceTier]:
        """Refuse a provenance entry for a field this model does not declare.

        `sourceTiers` is keyed by field name, per the schema's own
        description of it. A key that is not one of `Entity`'s own fields and
        is not a `sections.<Type>` key is a typo -- the kind that would
        otherwise sit in the build output silently, naming a field that
        cannot be traced back to anything, forever.
        """
        unknown = sorted(set(value) - _VALID_PROVENANCE_KEYS)
        if unknown:
            raise NormalizeError(
                f"sourceTiers names fields this Entity model does not declare: {unknown}. "
                f"A provenance key must be one of {sorted(_VALID_PROVENANCE_KEYS)}."
            )
        return value

    @model_validator(mode="after")
    def _wiki_url_required_when_wiki_authored_content_is_shown(self) -> "Entity":
        """Enforce decision D1 in Python, the same rule the schema's `if`/`then` states.

        The CC BY-NC-SA 3.0 license obliges this project to link back to the
        wiki page wherever it shows content the wiki *authored*. Two fields
        can do that: `blurb`, which is the wiki's own prose, and a section,
        which is a table the wiki compiled. Either one at Tier B requires a
        `wikiUrl`. An entity with neither -- the `poplar_*` set among them --
        carries no such obligation and may leave it unset.

        An `icon` is deliberately not one of the triggers, and the reason is
        the project's own recorded position rather than a convenience.
        Decision 3 of `TODO.md` says the sprites are Mojang's textures
        wherever they are fetched from, so the wiki hosts them rather than
        authoring them. The id-based icon route makes that concrete: it reads
        the hyphenated registry path straight out of Tier A and consults no
        wiki article at all. Measured on 2026-08-31, 7 biome IDs resolve an
        icon that way while having no wiki page in the join table, so
        counting the icon would demand an attribution link that nothing
        exists to point at, and those entities could not be built.
        """
        if self.wiki_url is not None:
            return self
        authored = [
            field
            for field, tier in self.source_tiers.items()
            if tier is SourceTier.B and (field == "blurb" or field.startswith("sections."))
        ]
        if authored:
            fields = ", ".join(sorted(authored))
            raise NormalizeError(
                f"{self.id!r} carries wiki-authored content at Tier B ({fields}) but no "
                f"wikiUrl. The CC BY-NC-SA 3.0 license requires a link back to the wiki "
                f"page wherever this project shows text or tables the wiki wrote."
            )
        return self


class EntityDraft:
    """A mutable accumulator that writes a field's value and its provenance in one call.

    The merge stage reads several tiers and, for each field, decides which
    one wins. That decision is only ever correct at the moment it is made --
    the merge step that reads Tier B's `EntityInfobox.health` and writes it
    onto the draft is the one place that actually knows the value came from
    Tier B. A second pass that tried to reconstruct `sourceTiers` afterward,
    by inspecting the final values, would be guessing: a field with the same
    shape can come from any tier, and nothing about a finished `Entity`
    proves which one it came from. `set` and `add_aliases` both take the
    contributing tier as a required argument for that reason, and record it
    in the same call that writes the value, so there is no code path that can
    set a field and forget its provenance.

    Not a `BaseModel`. `Entity` is frozen because a finished entity should
    never be mutated after validation; a draft is the opposite by
    construction, and pydantic's own mutable-model support (`model_config =
    ConfigDict(frozen=False)`) would still run full validation on every
    intermediate `set` call, which is wasted work for a merge that is not
    finished yet and may not validate until the very last field lands.
    """

    def __init__(self, *, id: str, kind: EntityKind, name: str, tier: SourceTier) -> None:
        self._id = id
        self._kind = kind
        self._name = name
        self._icon: str | None = None
        self._blurb: str | None = None
        self._wiki_url: str | None = None
        self._aliases: dict[str, SourceTier] = {}
        self._sections: dict[str, Section] = {}
        self._provenance: dict[str, SourceTier] = {"id": tier, "kind": tier, "name": tier}

    @property
    def kind(self) -> EntityKind:
        """The entity kind set at construction."""
        return self._kind

    @property
    def name(self) -> str:
        """The display name set so far."""
        return self._name

    @property
    def wiki_url(self) -> str | None:
        """The attribution link set so far, or `None`.

        Read by the merge before it attaches a wiki-authored section. D1 makes
        that pair a hard requirement, so a caller that can add such a section
        needs to be able to ask whether the link exists *before* adding it --
        otherwise the only signal is `build` raising at the end of the run,
        by which point the cheapest thing to report (which row, which table)
        is already out of scope.
        """
        return self._wiki_url

    def set(self, field: str, value: str | None, tier: SourceTier) -> "EntityDraft":
        """Write one scalar field and its provenance together, and return `self` for chaining.

        `field` names one of `Entity`'s own settable scalar fields, by its
        schema (camelCase) name -- `"name"`, `"icon"`, `"blurb"`, or
        `"wikiUrl"`. `id` and `kind` are set once, at construction, because
        they are the join key this draft was opened for rather than a value a
        later merge step could overwrite. `aliases` and `sections` have their
        own accumulating methods below, because unlike a scalar they union
        rather than replace.
        """
        if field == "name":
            self._name = value if value is not None else self._name
        elif field == "icon":
            self._icon = value
        elif field == "blurb":
            self._blurb = value
        elif field == "wikiUrl":
            self._wiki_url = value
        else:
            raise NormalizeError(
                f"EntityDraft.set does not know a field named {field!r}. Use add_aliases for "
                f"'aliases' or add_section for a section, or add the field here if it is new."
            )
        self._provenance[field] = tier
        return self

    def add_aliases(self, values: Iterable[str], tier: SourceTier) -> "EntityDraft":
        """Union `values` into the alias set, and return `self` for chaining.

        Unlike `set`, this never overwrites: registry ID segments (Tier A),
        wiki-derived shorthand (Tier B), and curated extras (Tier C) all
        contribute aliases to the same entity, and losing an earlier tier's
        aliases because a later tier also contributed some would make the
        Phase 4 search index worse, not more current. The provenance recorded
        for `"aliases"` is the highest tier that contributed *any* alias --
        `_TIER_RANK` gives the comparison -- because `sourceTiers` has one
        slot per field and the field as a whole came from whichever tier
        contributed most recently by that ordering.
        """
        for value in values:
            current = self._aliases.get(value)
            if current is None or _TIER_RANK[tier] > _TIER_RANK[current]:
                self._aliases[value] = tier
        if self._aliases:
            self._provenance["aliases"] = max(self._aliases.values(), key=_TIER_RANK.__getitem__)
        return self

    def add_section(self, section: Section, tier: SourceTier) -> "EntityDraft":
        """Add one section and its provenance, and return `self` for chaining.

        Keyed internally by the section's own `type`, so a later call for the
        same section type replaces rather than duplicates it -- a merge that
        runs twice over the same Tier B table should not double the section
        list.
        """
        section_type = section.type
        self._sections[section_type] = section
        self._provenance[f"sections.{section_type}"] = tier
        return self

    def add_section_first(self, section: Section, tier: SourceTier) -> "EntityDraft":
        """Add one section at the front of the render order, and return `self` for chaining.

        `Entity.sections` is a tuple in render order, and `web/render/entity.ts`
        draws the blurb and then walks that tuple. So "this block belongs
        directly under the blurb" is a statement about position in this dict,
        and `add_section` alone cannot make it, because it appends in call
        order and the merge's call order is the order the tiers happen to be
        read in.

        `FoodInfo` is the one section that needs it: `TODO.md`'s Phase 6 line
        asks for hunger and saturation "right after the blurb at the top of the
        page", and the food merge runs late, after the Tier B tables, because
        it resolves effect names against the finished draft set. Rebuilding the
        dict rather than mutating it in place keeps the "one section per type"
        rule `add_section` established: a repeat call for a type already held
        moves it to the front instead of duplicating it.
        """
        section_type = section.type
        reordered: dict[str, Section] = {section_type: section}
        for held_type, held in self._sections.items():
            if held_type != section_type:
                reordered[held_type] = held
        self._sections = reordered
        self._provenance[f"sections.{section_type}"] = tier
        return self

    def build(self) -> Entity:
        """Return the frozen `Entity` this draft describes.

        Runs every validator `Entity` declares, including D1's `wikiUrl`
        check -- a draft that never called `set("wikiUrl", ...)` despite
        adding a Tier B section fails here, at the one place the merge can
        still say which entity and which fields caused it.
        """
        return Entity(
            id=self._id,
            kind=self._kind,
            name=self._name,
            aliases=tuple(self._aliases),
            icon=self._icon,
            blurb=self._blurb,
            wiki_url=self._wiki_url,
            source_tiers=dict(self._provenance),
            sections=tuple(self._sections.values()),
        )
