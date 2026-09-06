"""`run_build`: fetch, extract, enrich, normalize, and emit one Minecraft version, end to end.

`pipeline/cli/__init__.py` owns argument parsing and the exit-code mapping.
This module owns the build itself -- the one function that walks every stage
this repository has built so far, in the order the earlier phases proved live
against real data, and writes `data/dist`. Nothing here talks to `argparse` or
`sys.exit`; `run_build` takes a typed `BuildOptions` and returns a typed
`BuildOutcome`, so a test drives it exactly the way `pipeline.cli` does,
minus the process boundary.

## Why the stage order is not this module's to invent

Every function this module calls already exists, tested, in its own package,
and each one's own module docstring already argues for the order it has to
run in relative to its neighbours: `pipeline.fetch.mcmeta` explains why a
version's mcmeta tag is pinned before anything reads a file of it,
`pipeline.normalize.merge` explains why the six Tier B indexes must all be
built before one `Entity` can be, and `pipeline.emit.write` explains why
nothing is written to disk until every payload of a build exists in memory.
This module does not re-argue any of that. It is wiring: call each stage with
the arguments its own signature already asks for, in the order its own
docstring already implies, and thread the two build-wide concerns -- which
`Transport` reads the network, and which `ContentCache` remembers what it
already read -- through every call that takes one.

## The mob-page rule, and why it lives here rather than in `pipeline.enrich`

`pipeline.enrich.infobox.parse_infoboxes` raises the moment it meets a page
with no `{{Infobox entity}}` template, and it is right to -- `select_infobox_
pages` in that module is how a caller keeps that promise, by splitting the
pages a build actually read into the ones with the template and the ones
without. What that module does not know is which wiki page titles a build
should even ask `pipeline.fetch.wikitext` for in the first place, because
that answer needs three sources at once that no single earlier stage holds
together: the mcmeta `entity_type` registry (Tier A), the wiki's own `Type`
classification of a `resource_location` row (Tier B, read through
`pipeline.normalize.merge.WIKI_KIND` -- promoted from that module's own
private mapping so this function reads the identical rule rather than a
second copy of it that could drift), and `pipeline.extract.entity_class`'s
three-way mob classification (also Tier A, but a different read of it than
the raw registry membership). Only `run_build`, at this point in the stage
order, holds all three, so `_select_mob_pages` lives here rather than being
pushed down into a package that would otherwise need to import across two
siblings just to answer one question this module already has every input
for.

Three conditions, all required, and the module docstring of `pipeline.
normalize.merge` -- the `_registries_of_id` and classification sections in
particular -- explains the reasoning behind each one in full:

1. The row's own unprefixed path sits in `registries["entity_type"]`. A path
   can sit in more than one registry at once -- `chicken` is also an `item`,
   for the raw meat -- and this clause alone would let that second row's page
   through the filter, which is exactly the trap.
2. `row.kind` is one of `WIKI_KIND["entity_type"]` -- the wiki's own `Type`
   field says `entity`, not `item`. This is what keeps the raw meat item's
   page out even though its registry path is identical to the mob's: `Raw
   Chicken` has no `{{Infobox entity}}` template at all, and asking `parse_
   infoboxes` to read it kills the whole build over a page this filter should
   never have selected.
3. `entity_class.EntityClass` classifies the path as `SPAWN_EGG` or
   `LOOT_TABLE_ONLY` -- the two classes `pipeline.normalize.merge` treats as
   a mob by default. This is what keeps an entity-type page that is a
   projectile, a display entity, or a piece of level geometry (`arrow`,
   `block_display`, a minecart) out of the read: none of those has a spawn
   egg or an entity loot table, so `entity_class.classify_entity_types`
   already marked every one of them `NEITHER`.

All three together reach every mob page this build actually treats as a mob
-- and exactly one page that reaches all three checks still carries no
`{{Infobox entity}}` template: Armor Stand. `armor_stand` has an entity loot
table and no spawn egg, so clause 3 classifies it `LOOT_TABLE_ONLY`, which
`pipeline.normalize.merge`'s own docstring calls "undecided, defaults to a
mob" -- Tier A and the wiki genuinely disagree about what this thing is, and
no rule built from either source alone can settle a disagreement between the
two. `select_infobox_pages` is what keeps that one disagreement from being a
build fault: it reports Armor Stand as a page without a template rather than
raising, and `BuildOutcome.pages_without_infobox` carries that name forward
so the gap stays visible in the build's own summary and in a written report,
rather than silently dropped the moment the infobox stage moves on.

## `--offline`

An offline build never opens a socket on purpose. `_offline_transport`
returns a `Transport` that raises `FetchError` the instant it is called,
naming the URL and the cache it consulted -- and every stage that reads
through a `ContentCache` (every wiki bucket and page read, and both mcmeta
payload reads) tries the cache before it ever calls a transport, per
`pipeline.fetch.cache.fetch_and_read`'s own docstring, so a warm cache
answers those reads with no error at all and only a genuine miss reaches
this transport.

Two reads at the head of a build once stood outside that store, and both are
inside it now, because a flag that can never succeed is worse than no flag.
The change is in the fetch modules and it is opt-in, so no stage grew a
second code path and no default behaviour moved.

`resolve_mcmeta_tag` now takes a `ContentCache`, and this module always
passes one. Its URL carries the version in its own path
(`.../git/ref/tags/26.2-data`) and a published mcmeta tag never moves, so a
stored answer cannot go wrong.

`fetch_version_manifest` now takes a cache *and* a caller revision, and
refuses one without the other. Its URL names no version, so an entry keyed
by the URL alone would answer "what is the current release" with the first
answer this project ever read -- the staleness that module's docstring rules
out, and it stays ruled out. This module therefore passes a cache only when
the caller named a version, in which case the manifest is being read for
`versions`, the release history that dates a curated document, and the
version names the entry.

That is why `--minecraft-version` is *required* under `--offline` rather
than merely accepted: "what is the current release" is the one question no
cache may answer, so it is the one piece of information an offline build
cannot derive for itself. This module raises `CliError` on the missing
combination before any network call is attempted, rather than letting the
build run partway and die on an error that does not say why it happened.

The consequence worth stating plainly: `--offline` succeeds only after an
online build of that same version has primed the store. That is a property
of a cache, not a limitation being papered over, and the `FetchError` from
`_offline_transport` names the URL that was missing so the reader knows
which read to prime.
"""

import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from pydantic import BaseModel

from pipeline.cli import CliError
from pipeline.emit import EmitError
from pipeline.emit.atlas import DecodedSprite, collect_sprite_files, decode_sprite, pack_atlas
from pipeline.emit.manifest import BuildInfo
from pipeline.emit.shard import DEFAULT_SHARD_SIZE
from pipeline.emit.write import DEFAULT_DIST_PATH, EmitReport, emit_build
from pipeline.emit.write import DEFAULT_REPORT_PATH as EMIT_REPORT_PATH
from pipeline.emit.write import write_report as write_emit_report
from pipeline.enrich.advancement import fetch_advancements
from pipeline.enrich.breeding import fetch_breeding
from pipeline.enrich.brewing import fetch_brewing
from pipeline.enrich.droptable import fetch_drop_tables
from pipeline.enrich.infobox import DEFAULT_REPORT_PATH as INFOBOX_REPORT_PATH
from pipeline.enrich.infobox import InfoboxReport, parse_infoboxes, select_infobox_pages
from pipeline.enrich.infobox import write_report as write_infobox_report
from pipeline.enrich.resource_location import JoinTable, fetch_join_table
from pipeline.enrich.spawn_table import fetch_spawn_tables
from pipeline.enrich.sprite import fetch_sprite_index
from pipeline.enrich.trade import fetch_trades
from pipeline.extract.advancement import extract_advancement_ids
from pipeline.extract.entity_class import EntityClass, EntityClassification, classify_entity_types
from pipeline.extract.food import extract_food
from pipeline.extract.harvest import extract_block_harvest
from pipeline.extract.tags import TagIndex
from pipeline.fetch import FetchError, Transport, decode_json, get_bytes
from pipeline.fetch.cache import DEFAULT_CACHE_ROOT, ContentCache
from pipeline.fetch.extracts import fetch_page_extracts
from pipeline.fetch.imageinfo import fetch_file_images
from pipeline.fetch.mcmeta import fetch_data_files, fetch_summary_payload, resolve_mcmeta_tag
from pipeline.fetch.sprites import download_sprites
from pipeline.fetch.version_manifest import fetch_version_manifest
from pipeline.fetch.wikitext import fetch_page_wikitext
from pipeline.normalize.curated import load_curated
from pipeline.normalize.merge import DEFAULT_REPORT_PATH as MERGE_REPORT_PATH
from pipeline.normalize.merge import (
    WIKI_KIND,
    MergeReport,
    block_drops_from_producers,
    merge_entities,
)
from pipeline.normalize.merge import write_report as write_merge_report
from pipeline.normalize.reconcile import DEFAULT_REPORT_PATH as RECONCILE_REPORT_PATH
from pipeline.normalize.reconcile import ReconciliationReport, reconcile
from pipeline.normalize.reconcile import write_report as write_reconcile_report
from pipeline.obtain.brewing import BrewingExtractionResult, build_brewing_producers
from pipeline.obtain.chests import (
    CHEST_SOURCES_FILENAME,
    load_chest_sources,
    verify_chest_sources,
)
from pipeline.obtain.loot import (
    LootExtractionResult,
    UnresolvedTradeOrDrop,
    extract_block_and_chest_loot,
    producers_from_drop_index,
    producers_from_trade_index,
)
from pipeline.obtain.producer import ObtainMethod, ProducerIndex
from pipeline.obtain.recipes import RecipeExtractionResult, SkippedRecipe, extract_recipes
from pipeline.validate import ValidationError, ValidationReport, validate_build

__all__ = [
    "CURATED_DIRECTORY",
    "OBTAIN_REPORT_NAME",
    "PAGES_WITHOUT_INFOBOX_REPORT_NAME",
    "VALIDATION_REPORT_NAME",
    "BuildOptions",
    "BuildOutcome",
    "ObtainReport",
    "run_build",
]

# `load_curated` reads this directory unconditionally. The stage order this
# module implements names it as a literal `Path("data") / "curated"`, not a
# value derived from any CLI flag, because Tier C is this repository's own
# committed, hand-reviewed content and not a build output a caller would ever
# want to redirect the way `--dist` or `--cache` redirect generated payloads.
CURATED_DIRECTORY = Path("data") / "curated"

# `select_infobox_pages`'s second half -- the mob pages this build asked for
# that carried no `{{Infobox entity}}` template -- is not the report of any
# existing stage module, so it gets a small file of its own alongside the
# four stage reports, under the same `--reports` directory.
PAGES_WITHOUT_INFOBOX_REPORT_NAME = "pages-without-infobox.json"

# `pipeline.obtain` has five adapters (`recipes`, `loot`'s two Tier A tables,
# `loot`'s two Tier B inversions, `brewing`) and none of them owns a report
# file of its own the way `pipeline.enrich.infobox` or `pipeline.normalize.
# merge` do -- each one returns its skips and unresolved rows alongside its
# producers, for this module to gather into one file, the same way `pages-
# without-infobox.json` gathers a fact that belongs to no single stage.
OBTAIN_REPORT_NAME = "obtain-report.json"

# `pipeline.validate.ValidationGate.report` is not the report of any earlier
# stage module either -- it is stage 7.5's own report, gathered here the same
# way `obtain-report.json` gathers stage 3b/4b's.
VALIDATION_REPORT_NAME = "validation.json"


class ObtainReport(BaseModel, frozen=True):
    """Every gap `pipeline.obtain`'s adapters found while building the obtain tree.

    `items_with_no_producer` is every `item`/`block` registry path this
    build enumerates as an entity with zero producers of any kind --
    expected to be large. Most of it is raw material this pipeline has no
    obtain method for at all (world generation, fishing, and the wiki's own
    Obtaining section are `TODO.md` Phase 6b's job, not this one's), so a
    long list here is not itself a fault; it is the honest boundary of what
    this phase covers. `potions_with_no_brewing_path` is `pipeline.obtain.
    brewing.BrewingExtractionResult.uncovered_potions` -- expected to hold
    exactly `water` and `luck` on the live 26.2 data. `unresolved_tier_b_
    names` covers what the brief calls "unresolved tag ingredients": every
    wiki display name `pipeline.obtain.loot`'s two Tier B inversions could
    not resolve to exactly one registry ID, from `pipeline.enrich.droptable`
    and `pipeline.enrich.trade`. `unresolved_effect_names` is `pipeline.
    obtain.brewing.BrewingExtractionResult.unresolved_effects`. `skipped_
    recipes` is every `crafting_special_*` and otherwise-unhandled recipe
    type `pipeline.obtain.recipes` skipped, per `TODO.md`'s own instruction
    to count rather than raise on it.
    """

    items_with_no_producer: tuple[str, ...] = ()
    potions_with_no_brewing_path: tuple[str, ...] = ()
    unresolved_tier_b_names: tuple[UnresolvedTradeOrDrop, ...] = ()
    unresolved_effect_names: tuple[str, ...] = ()
    skipped_recipes: tuple[SkippedRecipe, ...] = ()


class BuildOptions(BaseModel, frozen=True):
    """Every flag `python -m pipeline build` accepts, already parsed and typed.

    `minecraft_version` of `None` means "resolve Mojang's current release,"
    the same default `pipeline.fetch.version_manifest.fetch_latest_release_
    id` already documents. Every path defaults to the same constant the stage
    module that owns it already exports, so a caller reading either this
    model or `pipeline.cli`'s argument parser sees one number, not two that
    could drift.
    """

    minecraft_version: str | None = None
    dist: Path = DEFAULT_DIST_PATH
    cache: Path = DEFAULT_CACHE_ROOT
    reports: Path = Path("data") / "reports"
    shard_size: int = DEFAULT_SHARD_SIZE
    offline: bool = False
    quiet: bool = False
    # Downgrades a regression-check failure (stage 7.5's second half) to a
    # warning that is still written to `data/reports/validation.json` in
    # full. Never downgrades a schema conformance failure -- see `pipeline.
    # validate`'s own module docstring for why that half stays absolute.
    allow_regression: bool = False


class BuildOutcome(BaseModel, frozen=True):
    """What one `run_build` call did, for a caller that wants more than the exit code.

    Carries the resolved version and mcmeta pin (neither of which the caller
    may have known in advance, when `minecraft_version` was left unset), the
    finished entity count, every stage report `run_build` produced, the paths
    it wrote them to, and `pages_without_infobox` -- the mob-page gap the
    module docstring's "mob-page rule" section explains in full, carried out
    here specifically so it is visible to a caller and to a person reading
    the stderr summary, rather than silently dropped the moment the infobox
    stage moves past it. `validation_report` is stage 7.5's own report --
    present here even for a passing build, so a caller can see, for instance,
    every regression check `--allow-regression` downgraded rather than only
    finding out about them by reading `data/reports/validation.json`.
    """

    minecraft_version: str
    mcmeta_summary_ref: str
    mcmeta_data_ref: str
    entity_count: int
    dist: Path
    reports: Path
    report_paths: tuple[Path, ...]
    pages_without_infobox: tuple[str, ...]
    reconciliation_report: ReconciliationReport
    infobox_report: InfoboxReport
    merge_report: MergeReport
    emit_report: EmitReport
    obtain_report: ObtainReport
    validation_report: ValidationReport


def _offline_transport(cache: ContentCache) -> Transport:
    """Return a `Transport` that refuses the network, naming the URL and the cache it consulted.

    `pipeline.fetch.cache.fetch_and_read` and `pipeline.fetch.cache.
    ContentCache.fetch` both try the cache before they ever call a transport,
    so this function is only ever reached on a genuine cache miss -- a warm
    cache answers every `fetch_and_read`-based read with no call to this
    transport at all. The message says both facts a person needs to act on
    the failure: which URL was missing, and which cache directory did not
    have it, so the next step is obviously "warm that cache" rather than "is
    the network down."
    """

    def transport(url: str) -> bytes:
        raise FetchError(
            f"{url} is not in the cache at {cache.root}, and this build was run with "
            f"--offline. An offline build reads the cache only; it never falls back to "
            f"the network on a miss."
        )

    return transport


def _mcmeta_transport(transport: Transport | None) -> Transport:
    """Return `transport`, or `get_bytes` when the caller named none.

    `resolve_mcmeta_tag`, `fetch_version_manifest`, `fetch_summary_payload`,
    and `fetch_data_files` all declare `transport: Transport = get_bytes` --
    positional-or-keyword, not `Transport | None` -- so `run_build`'s own
    `transport: Transport | None = None` ("each fetcher's own default") has to
    be resolved to a concrete `Transport` before it reaches one of them. The
    wiki fetchers need no such helper: they already declare `transport:
    Transport | None = None` themselves, so `None` is passed through to them
    unchanged.
    """
    return get_bytes if transport is None else transport


def _select_mob_pages(
    *,
    registries: Sequence[str],
    join_table: JoinTable,
    classification: EntityClassification,
) -> tuple[str, ...]:
    """Return the wiki page titles this build reads infoboxes for.

    `registries` is `registries["entity_type"]` alone -- every unprefixed
    path mcmeta files under that one registry -- and `classification` is
    `pipeline.extract.entity_class.classify_entity_types`'s answer over the
    same mcmeta payload. See the module docstring's "mob-page rule" section
    for why all three clauses below are required, and for Armor Stand, the
    one page that passes all three and still carries no `{{Infobox entity}}`
    template.
    """
    entity_type_paths = frozenset(registries)
    wanted_kinds = WIKI_KIND["entity_type"]
    mob_classes = (EntityClass.SPAWN_EGG, EntityClass.LOOT_TABLE_ONLY)
    pages = {
        row.page
        for row in join_table.entries
        if row.resource_location in entity_type_paths
        and row.kind in wanted_kinds
        and classification.by_path.get(row.resource_location) in mob_classes
    }
    return tuple(sorted(pages))


def _write_reports(
    *,
    reports_root: Path,
    reconciliation_report: ReconciliationReport,
    merge_report: MergeReport,
    infobox_report: InfoboxReport,
    emit_report: EmitReport,
    obtain_report: ObtainReport,
    validation_report: ValidationReport,
    pages_without_infobox: Sequence[str],
) -> tuple[Path, ...]:
    """Write every stage report into `reports_root`, and return the paths written.

    Each of the four existing `write_report` functions keeps its own module's
    basename -- `DEFAULT_REPORT_PATH.name` -- rooted at `reports_root` rather
    than at each module's own `data/reports/` default, so a `--reports` flag
    redirects every one of them without this function knowing anything about
    their internal shape. `pages_without_infobox`, `obtain_report`, and
    `validation_report` are not the report of any stage module either, so
    each gets its own small file, written the same way `emit.write.
    write_report` and its siblings write theirs: indented JSON, sorted keys,
    one trailing newline.
    """
    reconciliation_path = reports_root / RECONCILE_REPORT_PATH.name
    merge_path = reports_root / MERGE_REPORT_PATH.name
    infobox_path = reports_root / INFOBOX_REPORT_PATH.name
    emit_path = reports_root / EMIT_REPORT_PATH.name
    pages_without_infobox_path = reports_root / PAGES_WITHOUT_INFOBOX_REPORT_NAME
    obtain_report_path = reports_root / OBTAIN_REPORT_NAME
    validation_report_path = reports_root / VALIDATION_REPORT_NAME

    write_reconcile_report(reconciliation_report, reconciliation_path)
    write_merge_report(merge_report, merge_path)
    write_infobox_report(infobox_report, infobox_path)
    write_emit_report(emit_report, emit_path)

    reports_root.mkdir(parents=True, exist_ok=True)
    document = {"pagesWithoutInfobox": sorted(pages_without_infobox)}
    pages_without_infobox_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    obtain_document = obtain_report.model_dump(mode="json")
    obtain_report_path.write_text(
        json.dumps(obtain_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validation_document = validation_report.model_dump(mode="json")
    validation_report_path.write_text(
        json.dumps(validation_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return (
        reconciliation_path,
        merge_path,
        infobox_path,
        emit_path,
        pages_without_infobox_path,
        obtain_report_path,
        validation_report_path,
    )


def run_build(
    options: BuildOptions,
    *,
    transport: Transport | None = None,
    cache: ContentCache | None = None,
    now: datetime | None = None,
    stream: TextIO = sys.stderr,
) -> BuildOutcome:
    """Run fetch through emit for one Minecraft version, and write `data/dist`.

    `transport` is `None` by default, meaning every stage reads through
    whichever `Transport` its own module already defaults to -- `get_bytes`
    for the mcmeta readers, the shared rate-limited `WIKI_TRANSPORT` for
    every wiki reader. Pass a fake transport (a `dict` lookup, typically) to
    drive a whole build with no socket opened; every call below is threaded
    through the same one object, so a test's fixture covers every read with a
    single dictionary. `cache` defaults to a fresh `ContentCache` rooted at
    `options.cache`; pass one explicitly to reuse a warm cache across two
    calls in one test, such as the determinism test that runs a build twice
    and diffs the bytes it wrote. `now` defaults to `datetime.now(UTC)`; pass
    a pinned value for a reproducible `BuildInfo.built_at`, which is the one
    field `pipeline.emit.write`'s own determinism rule excuses from
    byte-for-byte reproduction between two runs -- pinning it here is what
    lets a test hold every other byte to that rule anyway. `stream` is where
    progress lines go, `sys.stderr` by default; `options.quiet` suppresses
    them entirely rather than redirecting them.

    Raises `CliError` when `options.offline` is set and `options.minecraft_
    version` is not -- see the module docstring's `--offline` section for
    why an offline build cannot resolve "latest" for itself. Raises
    `FetchError`, `ExtractError`, `EnrichError`, `NormalizeError`, or
    `EmitError` for whatever fault the stage that raised it already
    documents; this function adds no guard of its own around any of them.
    """
    if options.offline and options.minecraft_version is None:
        raise CliError(
            "the build was run with --offline and no --minecraft-version. "
            "fetch_version_manifest keeps no cache of its own -- a cached answer to "
            "'what is the current release' would be a stale answer, and that defeats the "
            "read -- so an offline build cannot resolve the latest release for itself. "
            "Pass --minecraft-version to name the version this build targets."
        )

    store = cache if cache is not None else ContentCache(options.cache)
    built_at = now if now is not None else datetime.now(UTC)

    def report(line: str) -> None:
        if not options.quiet:
            print(line, file=stream)

    network_transport = _offline_transport(store) if options.offline else transport
    mcmeta_transport = _mcmeta_transport(network_transport)

    # --- 1. version -----------------------------------------------------------
    #
    # The manifest is read through the cache only when the caller already named
    # the version. A build that says `--minecraft-version 26.2` wants this
    # document for `versions` alone -- the release history that dates a curated
    # file -- and that history does not change for a version already released,
    # so it is safe to store under that version as the cache revision. A build
    # that named no version is asking the other question, "what is current",
    # and `fetch_version_manifest`'s own docstring is explicit that a stored
    # answer to that one is a wrong answer. So that build reads the network,
    # every time, which is also why `--offline` requires `--minecraft-version`.
    manifest = fetch_version_manifest(
        cache=store if options.minecraft_version is not None else None,
        revision=options.minecraft_version,
        transport=mcmeta_transport,
    )
    version = options.minecraft_version or manifest.latest.release
    release_order = tuple(entry.id for entry in manifest.versions)
    report(f"version: {version}")

    # --- 2. pin mcmeta ----------------------------------------------------------
    #
    # Cached unconditionally, unlike the manifest above: a tag URL carries the
    # version in its own path and a published mcmeta tag never moves, so there
    # is no question here that a stored answer could get wrong.
    summary_tag = resolve_mcmeta_tag(
        version, branch="summary", cache=store, transport=mcmeta_transport
    )
    data_tag = resolve_mcmeta_tag(version, branch="data", cache=store, transport=mcmeta_transport)
    report(f"mcmeta: summary={summary_tag.tag} data={data_tag.tag}")

    # --- 3. Tier A --------------------------------------------------------------
    registries_path = "registries/data.json"
    registries_payload = fetch_summary_payload(
        summary_tag, "registries", cache=store, transport=mcmeta_transport
    )
    registries: dict[str, list[str]] = decode_json(
        registries_payload, source=summary_tag.raw_url(registries_path)
    )
    item_components_path = "item_components/data.json"
    item_components_payload = fetch_summary_payload(
        summary_tag, "item_components", cache=store, transport=mcmeta_transport
    )
    item_components: dict[str, dict[str, object]] = decode_json(
        item_components_payload, source=summary_tag.raw_url(item_components_path)
    )
    food_index = extract_food(item_components)
    files = fetch_data_files(
        data_tag,
        groups=("advancement", "loot_table", "recipe", "tags"),
        cache=store,
        transport=mcmeta_transport,
    )
    advancement_ids = extract_advancement_ids(files)
    classification = classify_entity_types(files, registries)
    harvest_index = extract_block_harvest(files)
    report(
        f"tier A: {len(registries)} registries, {len(advancement_ids)} advancement ids, "
        f"{len(classification.by_path)} entity_type paths classified, "
        f"{len(food_index)} items that can be eaten, "
        f"{len(harvest_index)} blocks with harvest requirements"
    )

    # --- 3b. obtain, Tier A half: crafting/smelting recipes and block/chest loot ---
    item_tags = TagIndex(files, registry="item")
    recipe_result: RecipeExtractionResult = extract_recipes(files, tags=item_tags)
    loot_result: LootExtractionResult = extract_block_and_chest_loot(files)
    curated_chests = load_chest_sources(CURATED_DIRECTORY / CHEST_SOURCES_FILENAME)
    chest_tables = {
        producer.source_id
        for producer in loot_result.producers
        if producer.method is ObtainMethod.CHEST_LOOT
    }
    verify_chest_sources(chest_tables, curated_chests)
    report(
        f"obtain, tier A: {len(recipe_result.producers)} recipe producers "
        f"({len(recipe_result.skipped)} recipes skipped), "
        f"{len(loot_result.producers)} block/chest loot producers"
    )

    # --- 4. Tier B buckets -------------------------------------------------------
    join_table = fetch_join_table(revision=version, cache=store, transport=network_transport)
    sprite_index = fetch_sprite_index(revision=version, cache=store, transport=network_transport)
    drop_index = fetch_drop_tables(revision=version, cache=store, transport=network_transport)
    spawn_index = fetch_spawn_tables(revision=version, cache=store, transport=network_transport)
    trade_index = fetch_trades(revision=version, cache=store, transport=network_transport)
    advancement_tree = fetch_advancements(
        revision=version, cache=store, transport=network_transport
    )
    report(
        f"tier B buckets: {len(join_table.entries)} resource_location, "
        f"{len(sprite_index.entries)} sprites, {len(drop_index.drops)} drops, "
        f"{len(spawn_index.entries)} spawns, {len(trade_index.trades)} trades, "
        f"{len(advancement_tree.advancements)} wiki advancements"
    )

    # --- 4b. obtain, Tier B half: mob loot, trades, and brewing -----------------
    mob_loot_producers, unresolved_drops = producers_from_drop_index(
        drop_index, join_table=join_table
    )
    trade_producers, unresolved_trades = producers_from_trade_index(
        trade_index, join_table=join_table
    )
    brewing_index = fetch_brewing(revision=version, cache=store, transport=network_transport)
    brewing_result: BrewingExtractionResult = build_brewing_producers(
        brewing_index, registries.get("potion", ())
    )
    report(
        f"obtain, tier B: {len(mob_loot_producers)} mob loot producers, "
        f"{len(trade_producers)} trade producers, {len(brewing_result.producers)} brewing "
        f"producers, {len(brewing_result.uncovered_potions)} potions with no brewing path"
    )

    producer_index = ProducerIndex.merge(
        [
            ProducerIndex.from_producers(recipe_result.producers),
            ProducerIndex.from_producers(loot_result.producers),
            ProducerIndex.from_producers(mob_loot_producers),
            ProducerIndex.from_producers(trade_producers),
            ProducerIndex.from_producers(brewing_result.producers),
        ]
    )

    # --- 5. Tier B page text ------------------------------------------------------
    pages = sorted({entry.page for entry in join_table.entries})
    extract_report = fetch_page_extracts(
        pages, revision=version, cache=store, transport=network_transport
    )

    mob_pages = _select_mob_pages(
        registries=registries.get("entity_type", ()),
        join_table=join_table,
        classification=classification,
    )
    wikitext = fetch_page_wikitext(
        mob_pages, revision=version, cache=store, transport=network_transport
    )
    with_box, without_box = select_infobox_pages(wikitext.contents())
    infobox_report = parse_infoboxes(with_box)
    breeding_index = fetch_breeding(
        revision=version, cache=store, transport=network_transport
    )
    report(
        f"tier B page text: {len(extract_report.extracts)} blurbs, "
        f"{len(mob_pages)} mob pages selected, {len(with_box)} infoboxes parsed, "
        f"{len(without_box)} mob pages with no infobox template, "
        f"{len(breeding_index.by_mob)} mobs with breeding data"
    )
    if without_box:
        report(f"  pages without an infobox: {', '.join(without_box)}")

    # --- 6. Tier C ----------------------------------------------------------------
    curated = load_curated(CURATED_DIRECTORY, release_order=release_order, target_version=version)
    report(
        f"tier C: {len(curated.aliases)} curated alias entries, "
        f"{len(curated.overrides)} overrides"
    )

    # --- 7. normalize ---------------------------------------------------------------
    reconciliation_report = reconcile(
        registries=registries, join_table=join_table, sprite_index=sprite_index
    )
    result = merge_entities(
        registries=registries,
        advancement_ids=advancement_ids,
        join_table=join_table,
        sprite_index=sprite_index,
        infobox_report=infobox_report,
        spawn_index=spawn_index,
        drop_index=drop_index,
        trade_index=trade_index,
        advancement_tree=advancement_tree,
        extract_report=extract_report,
        curated=curated,
        entity_classification=classification,
        breeding_index=breeding_index,
        food_index=food_index,
        harvest_index=harvest_index,
        block_drops=block_drops_from_producers(loot_result.producers),
    )
    report(f"normalize: {len(result.entities)} entities merged")

    # --- 7b. sprite atlas -------------------------------------------------------------
    #
    # Sits after normalize because it needs `result.entities` -- specifically, the icon key
    # `pipeline.normalize.merge` already resolved onto each one -- and before validate/emit
    # because stage 7.5's conformance half needs the finished `Atlas` to check `sprites.json`
    # against `atlas.schema.json` before anything reaches disk, and stage 8 needs it to write
    # `sprites.png` and `sprites.json` at all. See `pipeline.emit.atlas`'s own module docstring
    # for the packer itself; this stage is wiring, the same role every other stage here plays.
    selection = collect_sprite_files(
        result.entities, sprite_index, extra_icons=curated.hud_sprites
    )
    image_report = fetch_file_images(
        selection.file_titles, revision=version, cache=store, transport=network_transport
    )
    download_report = download_sprites(
        image_report.images, cache=store, transport=network_transport
    )
    decoded_sprites: dict[str, DecodedSprite] = {}
    decode_failures: list[str] = []
    for title, payload in download_report.images.items():
        try:
            decoded_sprites[title] = decode_sprite(payload, title=title)
        except EmitError as error:
            # A per-file decode fault, collected rather than raised: `pipeline.fetch.sprites`'s
            # own module docstring already argues that one bad file must not abort a run over
            # roughly 1,900 of them, and a body that downloads intact but fails to decode is the
            # same shape of gap, one step later in the pipe.
            decode_failures.append(str(error))
    resolved_icons = {
        icon: title for icon, title in selection.icon_to_file.items() if title in decoded_sprites
    }
    atlas = pack_atlas(decoded_sprites, resolved_icons)
    sprite_failures = (
        len(selection.unresolved_icons)
        + len(image_report.missing)
        + len(download_report.failed)
        + len(decode_failures)
    )
    report(
        f"sprite atlas: {len(selection.icon_to_file) + len(selection.unresolved_icons)} icon "
        f"keys requested, {len(selection.file_titles)} files resolved, "
        f"{len(download_report.images)} sprites downloaded, {atlas.frame_count} frames packed "
        f"into {atlas.coordinates.width}x{atlas.coordinates.height}, {sprite_failures} failures"
    )

    # --- 7.5 validate -------------------------------------------------------------------
    #
    # `validate_build` reads `options.dist`'s baseline snapshot now, before emit gets any
    # chance to overwrite the very directory it reads -- see `pipeline.validate`'s own
    # module docstring for why that ordering is this call's job, not the gate's own.
    gate = validate_build(
        dist=options.dist,
        merge_result=result,
        producer_index=producer_index,
        allow_regression=options.allow_regression,
        atlas_icon_count=len(atlas.coordinates.sprites),
    )

    # --- 8. emit ----------------------------------------------------------------------
    build_info = BuildInfo(minecraft_version=version, mcmeta_ref=data_tag.tag, built_at=built_at)
    emit_report = emit_build(
        result,
        build_info,
        dist=options.dist,
        shard_size=options.shard_size,
        producer_index=producer_index,
        gate=gate,
        atlas=atlas,
    )
    validation_report = gate.report
    if validation_report is None:
        # Unreachable in practice: `emit_build` always calls a non-`None` gate before it
        # writes anything, and it only reached the line above by returning, which only
        # happens after `ValidationGate.__call__` has already set `.report`. The guard is
        # what lets mypy narrow `validation_report` to `ValidationReport` below, the same
        # role `merge_entities`'s own unreachable `NormalizeError` guard plays.
        raise ValidationError(
            "emit_build returned without ever calling the validation gate it was given."
        )
    documents_checked = sum(validation_report.conformance.checked.values())
    # The downgraded count is named on its own rather than folded into the blocking count. A build
    # run with `--allow-regression` has zero blocking failures by construction, so reporting only
    # that number would print a line that reads as completely clean for the one build that most
    # needs a second look -- the reader would have to open `validation.json` to learn that anything
    # failed at all.
    downgraded = tuple(check for check in validation_report.regression.checks if check.downgraded)
    downgraded_note = f", {len(downgraded)} downgraded by --allow-regression" if downgraded else ""
    report(
        f"validate: {documents_checked} documents checked, "
        f"{len(validation_report.conformance.failures)} conformance failures, "
        f"baseline={'present' if validation_report.regression.has_baseline else 'absent'}, "
        f"{len(validation_report.regression.blocking_failures)} blocking regression failures"
        f"{downgraded_note}"
    )
    report(
        f"emit: {emit_report.entity_count} entities in {len(emit_report.shards)} shards, "
        f"{emit_report.obtain_producer_count} obtain producers ({emit_report.obtain_bytes} "
        f"bytes), wrote {options.dist}"
    )

    # --- 9. reports ---------------------------------------------------------------------
    obtainable_paths = frozenset(registries.get("item", ())) | frozenset(
        registries.get("block", ())
    )
    items_with_no_producer = tuple(
        sorted(
            f"minecraft:{path}"
            for path in obtainable_paths
            if not producer_index.producers_of(f"minecraft:{path}")
        )
    )
    obtain_report = ObtainReport(
        items_with_no_producer=items_with_no_producer,
        potions_with_no_brewing_path=brewing_result.uncovered_potions,
        unresolved_tier_b_names=tuple(unresolved_drops) + tuple(unresolved_trades),
        unresolved_effect_names=tuple(
            sorted({entry.effect_name for entry in brewing_result.unresolved_effects})
        ),
        skipped_recipes=recipe_result.skipped,
    )
    report_paths = _write_reports(
        reports_root=options.reports,
        reconciliation_report=reconciliation_report,
        merge_report=result.report,
        infobox_report=infobox_report,
        emit_report=emit_report,
        obtain_report=obtain_report,
        validation_report=validation_report,
        pages_without_infobox=without_box,
    )
    report(f"reports: wrote {len(report_paths)} files to {options.reports}")

    return BuildOutcome(
        minecraft_version=version,
        mcmeta_summary_ref=summary_tag.tag,
        mcmeta_data_ref=data_tag.tag,
        entity_count=len(result.entities),
        dist=options.dist,
        reports=options.reports,
        report_paths=report_paths,
        pages_without_infobox=without_box,
        reconciliation_report=reconciliation_report,
        infobox_report=infobox_report,
        merge_report=result.report,
        emit_report=emit_report,
        obtain_report=obtain_report,
        validation_report=validation_report,
    )
