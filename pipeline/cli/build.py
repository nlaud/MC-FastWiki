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
from pipeline.emit.manifest import BuildInfo
from pipeline.emit.shard import DEFAULT_SHARD_SIZE
from pipeline.emit.write import DEFAULT_DIST_PATH, EmitReport, emit_build
from pipeline.emit.write import DEFAULT_REPORT_PATH as EMIT_REPORT_PATH
from pipeline.emit.write import write_report as write_emit_report
from pipeline.enrich.advancement import fetch_advancements
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
from pipeline.fetch import FetchError, Transport, decode_json, get_bytes
from pipeline.fetch.cache import DEFAULT_CACHE_ROOT, ContentCache
from pipeline.fetch.extracts import fetch_page_extracts
from pipeline.fetch.mcmeta import fetch_data_files, fetch_summary_payload, resolve_mcmeta_tag
from pipeline.fetch.version_manifest import fetch_version_manifest
from pipeline.fetch.wikitext import fetch_page_wikitext
from pipeline.normalize.curated import load_curated
from pipeline.normalize.merge import DEFAULT_REPORT_PATH as MERGE_REPORT_PATH
from pipeline.normalize.merge import WIKI_KIND, MergeReport, merge_entities
from pipeline.normalize.merge import write_report as write_merge_report
from pipeline.normalize.reconcile import DEFAULT_REPORT_PATH as RECONCILE_REPORT_PATH
from pipeline.normalize.reconcile import ReconciliationReport, reconcile
from pipeline.normalize.reconcile import write_report as write_reconcile_report

__all__ = [
    "CURATED_DIRECTORY",
    "PAGES_WITHOUT_INFOBOX_REPORT_NAME",
    "BuildOptions",
    "BuildOutcome",
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


class BuildOutcome(BaseModel, frozen=True):
    """What one `run_build` call did, for a caller that wants more than the exit code.

    Carries the resolved version and mcmeta pin (neither of which the caller
    may have known in advance, when `minecraft_version` was left unset), the
    finished entity count, every stage report `run_build` produced, the paths
    it wrote them to, and `pages_without_infobox` -- the mob-page gap the
    module docstring's "mob-page rule" section explains in full, carried out
    here specifically so it is visible to a caller and to a person reading
    the stderr summary, rather than silently dropped the moment the infobox
    stage moves past it.
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
    pages_without_infobox: Sequence[str],
) -> tuple[Path, ...]:
    """Write every stage report into `reports_root`, and return the paths written.

    Each of the four existing `write_report` functions keeps its own module's
    basename -- `DEFAULT_REPORT_PATH.name` -- rooted at `reports_root` rather
    than at each module's own `data/reports/` default, so a `--reports` flag
    redirects every one of them without this function knowing anything about
    their internal shape. `pages_without_infobox` is not a report any stage
    module owns, so it gets its own small file, written the same way `emit.
    write.write_report` and its siblings write theirs: indented JSON, sorted
    keys, one trailing newline.
    """
    reconciliation_path = reports_root / RECONCILE_REPORT_PATH.name
    merge_path = reports_root / MERGE_REPORT_PATH.name
    infobox_path = reports_root / INFOBOX_REPORT_PATH.name
    emit_path = reports_root / EMIT_REPORT_PATH.name
    pages_without_infobox_path = reports_root / PAGES_WITHOUT_INFOBOX_REPORT_NAME

    write_reconcile_report(reconciliation_report, reconciliation_path)
    write_merge_report(merge_report, merge_path)
    write_infobox_report(infobox_report, infobox_path)
    write_emit_report(emit_report, emit_path)

    reports_root.mkdir(parents=True, exist_ok=True)
    document = {"pagesWithoutInfobox": sorted(pages_without_infobox)}
    pages_without_infobox_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return (
        reconciliation_path,
        merge_path,
        infobox_path,
        emit_path,
        pages_without_infobox_path,
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
    files = fetch_data_files(
        data_tag, groups=("advancement", "loot_table"), cache=store, transport=mcmeta_transport
    )
    advancement_ids = extract_advancement_ids(files)
    classification = classify_entity_types(files, registries)
    report(
        f"tier A: {len(registries)} registries, {len(advancement_ids)} advancement ids, "
        f"{len(classification.by_path)} entity_type paths classified"
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
    report(
        f"tier B page text: {len(extract_report.extracts)} blurbs, "
        f"{len(mob_pages)} mob pages selected, {len(with_box)} infoboxes parsed, "
        f"{len(without_box)} mob pages with no infobox template"
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
    )
    report(f"normalize: {len(result.entities)} entities merged")

    # --- 8. emit ----------------------------------------------------------------------
    build_info = BuildInfo(minecraft_version=version, mcmeta_ref=data_tag.tag, built_at=built_at)
    emit_report = emit_build(result, build_info, dist=options.dist, shard_size=options.shard_size)
    report(
        f"emit: {emit_report.entity_count} entities in {len(emit_report.shards)} shards, "
        f"wrote {options.dist}"
    )

    # --- 9. reports ---------------------------------------------------------------------
    report_paths = _write_reports(
        reports_root=options.reports,
        reconciliation_report=reconciliation_report,
        merge_report=result.report,
        infobox_report=infobox_report,
        emit_report=emit_report,
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
    )
