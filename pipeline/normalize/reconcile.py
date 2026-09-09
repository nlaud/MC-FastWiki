"""Where Tier A and Tier B agree, and where a merge cannot happen yet.

Tier A (`pipeline.extract`) is a list of registry IDs -- `iron_sword`,
`acacia_button`, `creeper`. Tier B (`pipeline.enrich.resource_location`) is a
table the wiki wrote, mapping a display name to a registry ID. Neither one
carries an icon; `pipeline.enrich.sprite` reads a third table, keyed by a
sprite *family* and an *id* inside it, with no registry ID in sight at all.
This module is where those three tables meet, and it answers two separate
questions that are easy to conflate:

* Does the wiki know about this Tier A ID at all -- does `resource_location`
  hold a row for it? That is `missing_from_tier_b`.
* Does an icon chain resolve for this ID -- does `InvSprite`, `BlockSprite`, or
  whichever family the ID's registry uses actually hold a matching entry? That
  is `missing_icons`, and it is a different, usually smaller, count. The two
  disagree because the id-based route of an icon chain needs no wiki row at
  all: `BlockSprite`'s `acacia-button` is keyed straight off the hyphenated
  registry path, so a Tier A ID with no `resource_location` row can still have
  a working icon, and measurement on 2026-08-30 found this is the common case
  for the one family of misses both counts share, the unreleased `poplar_*`
  wood set: 13 items and 13 blocks have no wiki row, but only 4 items and 2
  blocks have no icon.

**Icon resolution chains through two routes, in order, and both are named by
`IconRule`.** The display-name route asks `pipeline.enrich.resource_location`
what the wiki calls this registry ID, then looks that display name up in
`InvSprite` -- the family the wiki uses for the icons a player actually sees in
an inventory slot. The id-based route skips the wiki's own name entirely and
asks `pipeline.enrich.sprite` for the hyphenated registry path directly, in
one or more fallback families. Measured on 2026-08-30, over the full mcmeta
`26.2` registries and the full `spritefile` bucket:

| registry | count | iconed | missing |
|---|---|---|---|
| `item` | 1658 | 1654 | `poplar_boat`, `poplar_chest_boat`, `poplar_shelf`, `sulfur_cube_bucket` |
| `block` | 1286 | 1284 | `poplar_shelf`, `poplar_wall_sign` |
| `entity_type` | 161 | 158 | `cushion`, `poplar_chest_boat`, `spawner_minecart` |
| `mob_effect` | 40 | 40 | none |
| `worldgen/biome` | 67 | 67 | none |
| `enchantment` | 43 | 1 | exempt -- see below |

`enchantment` is declared exempt rather than tracked as 42 misses out of 43.
The wiki has no `EnchantmentSprite` family, or any family this project reads
that answers an enchantment's name or ID; the one enchantment that resolved
under exhaustive testing across every family did so by accident, matching an
unrelated icon of the same short name, not because a real enchantment sprite
exists. `ICON_RULES["enchantment"]` therefore carries `has_icons=False`, and
`reconcile` reports it once, in `exempt_registries`, with the reason above,
instead of as noise repeated 42 times in `missing_icons`.

**`missing_from_tier_a` is the reverse direction, and it needs every registry,
not a hand-picked few.** The wiki's `resource_location` table also names
things that are not Tier A IDs at all: April Fools' content, Minecraft Earth
tie-ins, and gamerule keys such as `blockBorder`. Measured on 2026-08-30, 215
wiki-known IDs match no path in any of the 186 mcmeta registries. Checking
against a hand-picked handful instead of all 186 inflates that count to 282
with 67 false alarms: `ancient_city` is a real ID, just one that lives in
`worldgen/structure` rather than `block` or `item`, and the music discs `11`
and `13` live in `jukebox_song`. So `reconcile` tests membership of every wiki
ID against the union of every registry mcmeta publishes, not only the six this
module has an `IconRule` for.

**This module never fails a build.** `pipeline.normalize`'s package docstring
gives the reason CLAUDE.md's own tier distinction already implies: a
reconciliation gap is Tier B disagreeing with Tier A, which is the presentation
layer disagreeing with the completeness layer, not the completeness layer
being wrong. `reconcile` returns a report. Phase 3's validation gate is where a
threshold on that report belongs, once the `Entity` model it gates on exists.
"""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel

from pipeline.enrich.resource_location import NAMESPACE, JoinTable
from pipeline.enrich.sprite import SpriteFile, SpriteIndex
from pipeline.normalize import NormalizeError

__all__ = [
    "DEFAULT_REPORT_PATH",
    "EXEMPT_REASONS",
    "ICON_RULES",
    "AmbiguousIcon",
    "ExemptRegistry",
    "IconResolution",
    "IconRule",
    "MissingEntity",
    "MissingIcon",
    "ReconciliationReport",
    "RegistryCounts",
    "hyphenated_sprite_id",
    "reconcile",
    "resolve_display_name_icon",
    "resolve_icon",
    "write_report",
]

# Where `reconcile`'s report lands by default. `data/reports/` is gitignored,
# matching `pipeline.enrich.infobox.DEFAULT_REPORT_PATH`, and the writer takes
# an explicit path so a later emit stage can redirect it without editing this
# module.
DEFAULT_REPORT_PATH = Path("data") / "reports" / "tier-reconciliation.json"


class IconRule(BaseModel, frozen=True):
    """How one mcmeta registry's ID becomes an icon, or the declaration that it cannot.

    `display_name_families` is tried first, through the wiki's own name for
    the ID -- today that is always `("InvSprite",)` or nothing, because
    `InvSprite` is the only family this project reads that is keyed by display
    name rather than by ID. `id_families` is tried after, keyed by the
    hyphenated registry path itself and needing no wiki row to succeed. Either
    tuple may be empty; a rule with both empty and `has_icons=True` would
    simply never resolve, which is why `enchantment` instead sets
    `has_icons=False` and is reported as an exemption rather than a registry
    that silently never gets an icon.

    `join_kinds` is the field that is easy to leave out and expensive to leave
    out. `JoinTable.by_registry_id` is keyed by the namespaced path alone --
    `minecraft:chicken` -- and mcmeta's registries are not. The raw chicken
    *item* and the chicken *mob* are both `minecraft:chicken`, and so are
    `cod`, `salmon`, `rabbit`, and `experience_bottle`, whose entity is the
    thrown bottle. One key, two entities, and the join table answers with the
    rows of both.

    Without `join_kinds` that costs twice. The display-name route sees two
    names for one ID, cannot tell which registry each belongs to, and gives up:
    measured on 2026-08-30, that alone put 5 items that have perfectly good
    icons into the missing-icon report. Worse is the case where it does not
    give up -- an ID whose two rows share one name would resolve the item
    through the mob's row, and `TODO.md` is explicit that a wrong icon is worse
    than a missing one.

    So each rule names the `ResourceLocation.kind` values that belong to its
    registry, and the display-name route only ever reads rows of those kinds.
    The wiki's vocabulary is its own, not mcmeta's: `entity_type` is `entity`
    on the wiki, `mob_effect` is `effect`, and `worldgen/biome` is `biome`.
    """

    registry: str
    display_name_families: tuple[str, ...] = ()
    id_families: tuple[str, ...] = ()
    # The wiki `Type` values whose rows may name this registry's IDs. Empty
    # means the display-name route is not used at all, so there is nothing to
    # filter -- which is every rule that resolves by ID alone.
    join_kinds: tuple[str, ...] = ()
    has_icons: bool = True


# Why the one `has_icons=False` rule is exempt, kept apart from `IconRule`
# itself so the model stays the four fields the reconciliation logic actually
# branches on, and named for the report so a reader does not have to open this
# module to see what reconciliation chose not to look for.
EXEMPT_REASONS: Mapping[str, str] = {
    "enchantment": (
        "measured 2026-08-30: 42 of the 43 enchantments resolve to nothing under every sprite "
        "family this project reads, and the one that resolved did so by coincidence against an "
        "unrelated icon of the same short name. The wiki has no enchantment sprite family."
    ),
}

# The chains measured live on 2026-08-30, over mcmeta `26.2`'s registries and
# the full `spritefile` bucket. See the module docstring's table for the counts
# each chain produced.
ICON_RULES: Mapping[str, IconRule] = {
    "item": IconRule(
        registry="item",
        display_name_families=("InvSprite",),
        id_families=("ItemSprite", "BlockSprite"),
        # Both kinds, and measured rather than assumed. Most of the item
        # registry is block items, and the wiki files those under `block`, not
        # `item`: `minecraft:gold_block` is the item you hold and its only row
        # is the `block` row named `Block of Gold`. Filtering to `item` alone
        # dropped 27 of them -- `coal_block`, `diamond_block`, `hay_block`,
        # `comparator`, `repeater`, `spawner`, `vine` -- into the missing-icon
        # report on the run of 2026-08-30 that measured it.
        #
        # Taking both kinds does not reopen the collision `join_kinds` exists
        # to close. That collision is an item against an *entity* of one path,
        # which is what `chicken` and `experience_bottle` are, and neither kind
        # here is `entity`. Where a path really does hold an item row and a
        # block row, both describe the same thing the player picks up.
        join_kinds=("item", "block"),
    ),
    "block": IconRule(
        registry="block",
        display_name_families=("InvSprite",),
        id_families=("BlockSprite", "ItemSprite"),
        join_kinds=("block",),
    ),
    "entity_type": IconRule(registry="entity_type", id_families=("EntitySprite",)),
    "mob_effect": IconRule(registry="mob_effect", id_families=("EffectSprite",)),
    "worldgen/biome": IconRule(registry="worldgen/biome", id_families=("BiomeSprite",)),
    "enchantment": IconRule(registry="enchantment", has_icons=False),
    "profession": IconRule(registry="villager_profession", id_families=("EntitySprite",)),
}


class IconResolution(BaseModel, frozen=True):
    """What `resolve_icon` found for one registry ID, and every route it tried to find it."""

    registry_id: str
    sprite: SpriteFile | None
    matched_family: str | None = None
    # `"display_name"` or `"id"`, naming which half of the chain matched.
    matched_route: str | None = None
    # Every `(family, sprite_id)` pair actually looked up, in the order tried,
    # whether or not it matched. Carried into `MissingIcon` so a report reader
    # can see what was tried without re-deriving it from `IconRule`.
    routes_tried: tuple[tuple[str, str], ...] = ()
    # Set when the display-name route found a name, but that name is one of
    # `JoinTable.ambiguous_names`'s entries -- more than one registry ID shares
    # it. `resolve_icon` never picks an icon in that case; see its own
    # docstring for why a wrong icon is worse than a missing one.
    ambiguous_display_name: str | None = None


class MissingEntity(BaseModel, frozen=True):
    """A Tier A registry ID with no `resource_location` row at all."""

    registry: str
    registry_id: str


class MissingIcon(BaseModel, frozen=True):
    """A reconciled ID whose rule says it should have an icon, and does not."""

    registry: str
    registry_id: str
    routes_tried: tuple[tuple[str, str], ...]


class AmbiguousIcon(BaseModel, frozen=True):
    """A reconciled ID whose display name names more than one registry ID.

    `pipeline.enrich.resource_location.JoinTable.resolve` already refuses to
    pick one registry ID for such a display name; this is the icon-side
    consequence recorded as its own report line, so a wrong icon is never
    chosen quietly for either resolve.
    """

    registry: str
    registry_id: str
    display_name: str
    candidate_registry_ids: tuple[str, ...]


class ExemptRegistry(BaseModel, frozen=True):
    """A registry `reconcile` did not check for icons, and why."""

    registry: str
    reason: str


class RegistryCounts(BaseModel, frozen=True):
    """How one registry's icon check came out, so a report reads without counting rows."""

    total: int
    iconed: int
    missing: int


class ReconciliationReport(BaseModel, frozen=True):
    """What one reconciliation of Tier A against Tier B and the sprite index produced.

    Reporting only. `reconcile`'s own docstring, and `pipeline.normalize`'s
    package docstring above it, both give the reason this model has no field
    that can fail a build: that decision belongs to Phase 3's validation gate,
    once the `Entity` model it would gate on exists.
    """

    missing_from_tier_b: tuple[MissingEntity, ...] = ()
    missing_from_tier_a: tuple[str, ...] = ()
    missing_icons: tuple[MissingIcon, ...] = ()
    ambiguous_icons: tuple[AmbiguousIcon, ...] = ()
    exempt_registries: tuple[ExemptRegistry, ...] = ()
    counts: Mapping[str, RegistryCounts] = {}


def hyphenated_sprite_id(registry_id: str) -> str:
    """Return the sprite id that `BlockSprite`/`ItemSprite`/etc write for a registry ID.

    `BlockSprite` writes `acacia-button` where the registry writes
    `acacia_button` -- every underscore becomes a hyphen and nothing else
    changes. A namespace prefix is stripped first, because a sprite id never
    carries one: passing either `acacia_button` or `minecraft:acacia_button`
    gives the same answer, so a caller need not track which form it is
    holding.
    """
    path = registry_id.split(":", 1)[-1]
    return path.replace("_", "-")


def resolve_icon(
    registry_id: str,
    rule: IconRule,
    join_table: JoinTable,
    sprite_index: SpriteIndex,
) -> IconResolution:
    """Return the icon `registry_id` resolves to under `rule`, or every route that failed.

    The display-name route runs first, and only when `rule` names a family for
    it. `join_table.by_registry_id` gives the display name(s) the wiki uses for
    this ID; when there is exactly one and it is not one of
    `join_table.ambiguous_names`'s entries, each family of
    `display_name_families` is tried against it in order. A display name that
    *is* ambiguous is never tried at all -- `JoinTable.resolve` already refuses
    to pick a registry ID for such a name, and picking an icon through it would
    make the same wrong choice from the other direction. When more than one
    display name maps to this one registry ID, a case the live join table
    happens not to produce, the first one recorded is used, for the same
    determinism reason `pipeline.enrich.resource_location.parse_resource_locations`
    gives for its own page-choice tie-break.

    The id-based route runs after, unconditionally: it needs no wiki row, so it
    still gives an ID with no `resource_location` entry a chance to resolve.
    Each family of `id_families` is tried, in order, against
    `hyphenated_sprite_id(registry_id)`.

    Every route considered -- matched or not -- is recorded in
    `routes_tried`, in the order it was tried, so a `MissingIcon` built from a
    failed resolution shows exactly what was looked for.

    An ambiguous display name only reaches the returned `IconResolution` when
    the id-based route also fails to resolve anything: the field exists to
    report a genuine dead end, not to flag an ID that already has a working
    icon through the other route. So a caller sees `ambiguous_display_name`
    set only on a resolution whose `sprite` is also `None`.
    """
    routes_tried: list[tuple[str, str]] = []
    ambiguous_display_name: str | None = None

    if rule.display_name_families:
        rows = join_table.by_registry_id.get(registry_id, ())
        # The kind filter, and the reason `IconRule.join_kinds` exists: one
        # namespaced path can name an item and an entity at once, and reading
        # both rows as names for this registry's ID is how the raw chicken
        # loses its icon to the chicken mob.
        candidates = tuple(entry for entry in rows if entry.kind in rule.join_kinds)
        display_names = {entry.display_name for entry in candidates}
        if len(display_names) == 1:
            display_name = candidates[0].display_name
            name_candidates = join_table.candidates(display_name)
            ids_for_name = {
                entry.registry_id
                for entry in name_candidates
                if entry.kind in rule.join_kinds
            }
            if len(ids_for_name) > 1:
                ambiguous_display_name = display_name
            else:
                for family in rule.display_name_families:
                    routes_tried.append((family, display_name))
                    sprite = sprite_index.lookup(family, display_name)
                    if sprite is not None:
                        return IconResolution(
                            registry_id=registry_id,
                            sprite=sprite,
                            matched_family=family,
                            matched_route="display_name",
                            routes_tried=tuple(routes_tried),
                        )

    sprite_id = hyphenated_sprite_id(registry_id)
    for family in rule.id_families:
        routes_tried.append((family, sprite_id))
        sprite = sprite_index.lookup(family, sprite_id)
        if sprite is not None:
            return IconResolution(
                registry_id=registry_id,
                sprite=sprite,
                matched_family=family,
                matched_route="id",
                routes_tried=tuple(routes_tried),
            )

    return IconResolution(
        registry_id=registry_id,
        sprite=None,
        routes_tried=tuple(routes_tried),
        ambiguous_display_name=ambiguous_display_name,
    )


def resolve_display_name_icon(
    display_name: str,
    join_table: JoinTable,
    sprite_index: SpriteIndex,
    *,
    rules: Mapping[str, IconRule] = ICON_RULES,
) -> IconResolution:
    """Return the icon `display_name` resolves to through `join_table` and `rules`.

    Strips a trailing `.gif` or `.png` extension, resolves the display name to
    candidate registry IDs through `join_table`, and runs `resolve_icon` across
    the matching rules.

    Item and block candidates are preferred first (as advancements and recipes
    name items or blocks) before considering other kinds. If multiple distinct
    registry IDs remain within that candidate group, the name is ambiguous and
    the route declines rather than guessing.

    Every route considered is recorded in `routes_tried`, matching `resolve_icon`.
    """
    clean_name = re.sub(r"\.(?:gif|png)\Z", "", display_name, flags=re.IGNORECASE).strip()
    routes_tried: list[tuple[str, str]] = []

    candidates = join_table.candidates(clean_name)
    if not candidates:
        routes_tried.append(("display_name", clean_name))
        return IconResolution(
            registry_id="",
            sprite=None,
            routes_tried=tuple(routes_tried),
        )

    # Prefer item and block candidates first, matching advancement icon semantics
    item_candidates = tuple(c for c in candidates if c.kind in ("item", "block"))
    target_candidates = item_candidates if item_candidates else candidates

    distinct_ids = list(dict.fromkeys(c.registry_id for c in target_candidates))
    if len(distinct_ids) > 1:
        routes_tried.append(("ambiguous", clean_name))
        return IconResolution(
            registry_id="",
            sprite=None,
            routes_tried=tuple(routes_tried),
            ambiguous_display_name=clean_name,
        )

    registry_id = distinct_ids[0]
    candidate_kind = target_candidates[0].kind

    registries_to_try: list[str]
    if candidate_kind == "item":
        registries_to_try = ["item", "block"]
    elif candidate_kind == "block":
        registries_to_try = ["block", "item"]
    elif candidate_kind == "entity":
        registries_to_try = ["entity_type"]
    elif candidate_kind == "biome":
        registries_to_try = ["worldgen/biome"]
    elif candidate_kind == "effect":
        registries_to_try = ["mob_effect"]
    else:
        registries_to_try = ["item", "block", "entity_type"]

    last_resolution: IconResolution | None = None
    for reg in registries_to_try:
        rule = rules.get(reg)
        if rule is None or not rule.has_icons:
            continue
        resolution = resolve_icon(registry_id, rule, join_table, sprite_index)
        if resolution.sprite is not None:
            return resolution
        routes_tried.extend(resolution.routes_tried)
        last_resolution = resolution

    return IconResolution(
        registry_id=registry_id,
        sprite=None,
        routes_tried=tuple(routes_tried),
        ambiguous_display_name=last_resolution.ambiguous_display_name if last_resolution else None,
    )


def reconcile(
    *,
    registries: Mapping[str, Sequence[str]],
    join_table: JoinTable,
    sprite_index: SpriteIndex,
) -> ReconciliationReport:
    """Return the reconciliation of `registries` against `join_table` and `sprite_index`.

    `registries` is the full mcmeta registries payload -- every registry name
    mapped to its list of unprefixed ID paths, not only the six named in
    `ICON_RULES`. It is used twice, for the two directions the module
    docstring names: `missing_from_tier_b` and `missing_icons` walk only the
    registries `ICON_RULES` covers, while `missing_from_tier_a` tests every
    wiki-known ID against the union of every registry's IDs, because the
    module docstring's measurement shows what checking a handful instead
    costs -- 67 false alarms out of 282, `ancient_city` and the music discs
    among them.

    Refuses an empty `registries` or a `sprite_index` with no entries at all --
    both are a failed scrape, not a Minecraft version or a wiki with nothing to
    reconcile, matching the rule CLAUDE.md gives for every other empty result
    this pipeline can produce.
    """
    if not registries:
        raise NormalizeError(
            "reconcile was given no mcmeta registries. An empty registries payload is a failed "
            "scrape, not a version of Minecraft with nothing to reconcile."
        )
    if not sprite_index.entries:
        raise NormalizeError(
            "reconcile was given a sprite index with no entries. An empty spritefile read is a "
            "failed scrape, not a wiki with no sprites."
        )

    all_registry_ids = {path for ids in registries.values() for path in ids}
    tier_b_ids = {entry.registry_id for entry in join_table.entries}
    missing_from_tier_a = tuple(
        sorted(
            registry_id
            for registry_id in tier_b_ids
            if registry_id.split(":", 1)[-1] not in all_registry_ids
        )
    )

    missing_from_tier_b: list[MissingEntity] = []
    missing_icons: list[MissingIcon] = []
    ambiguous_icons: list[AmbiguousIcon] = []
    exempt_registries: list[ExemptRegistry] = []
    counts: dict[str, RegistryCounts] = {}

    for registry_name, rule in ICON_RULES.items():
        lookup = rule.registry if rule.registry in registries else registry_name
        ids = registries.get(lookup)
        if ids is None:
            raise NormalizeError(
                f"{registry_name!r} is a registry that ICON_RULES names, and this mcmeta "
                f"payload does not publish it. The rules have gone stale against the game."
            )
        if not rule.has_icons:
            exempt_registries.append(
                ExemptRegistry(registry=registry_name, reason=EXEMPT_REASONS[registry_name])
            )

        iconed = 0
        for path in ids:
            registry_id = f"{NAMESPACE}:{path}"
            if registry_id not in tier_b_ids:
                missing_from_tier_b.append(
                    MissingEntity(registry=registry_name, registry_id=registry_id)
                )
            if not rule.has_icons:
                continue
            resolution = resolve_icon(registry_id, rule, join_table, sprite_index)
            if resolution.ambiguous_display_name is not None:
                name_candidates = join_table.candidates(resolution.ambiguous_display_name)
                candidate_ids = tuple(
                    sorted(
                        {
                            entry.registry_id
                            for entry in name_candidates
                            if entry.kind in rule.join_kinds
                        }
                    )
                )
                ambiguous_icons.append(
                    AmbiguousIcon(
                        registry=registry_name,
                        registry_id=registry_id,
                        display_name=resolution.ambiguous_display_name,
                        candidate_registry_ids=candidate_ids
                        or join_table.ambiguous_names().get(
                            resolution.ambiguous_display_name, ()
                        ),
                    )
                )
            elif resolution.sprite is None:
                missing_icons.append(
                    MissingIcon(
                        registry=registry_name,
                        registry_id=registry_id,
                        routes_tried=resolution.routes_tried,
                    )
                )
            else:
                iconed += 1

        total = len(ids)
        counts[registry_name] = RegistryCounts(
            total=total,
            iconed=iconed if rule.has_icons else 0,
            missing=(total - iconed) if rule.has_icons else 0,
        )

    return ReconciliationReport(
        missing_from_tier_b=tuple(missing_from_tier_b),
        missing_from_tier_a=missing_from_tier_a,
        missing_icons=tuple(missing_icons),
        ambiguous_icons=tuple(ambiguous_icons),
        exempt_registries=tuple(exempt_registries),
        counts=counts,
    )


def write_report(report: ReconciliationReport, path: Path = DEFAULT_REPORT_PATH) -> None:
    """Write `report` to `path` as indented JSON, creating parent directories as needed.

    Copies `pipeline.enrich.infobox.write_report`'s shape exactly: `path`
    defaults to `DEFAULT_REPORT_PATH` and is otherwise an explicit argument, so
    a later emit stage can redirect it without editing this module.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = report.model_dump(mode="json")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
