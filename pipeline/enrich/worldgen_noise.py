"""Extract Overworld biome noise climate parameters from wiki wikitext.

The Minecraft data files publish temperature, downfall, and precipitation, but
continentalness, erosion, weirdness, and depth live only in eight wikitext tables
in section `World generation § Biomes -> Overworld` on minecraft.wiki.

The eight tables form a two-level structure:
1. Depth route: places 4 cave biomes (Dripstone Caves, Lush Caves, Sulfur Caves, Deep Dark).
2. Non-inland route: places oceans and Mushroom Fields by continentalness against temperature.
3. Direct inland route: placed directly in the inland surface table (River, Frozen River,
   Swamp, Mangrove Swamp, Stony Shore, Windswept Savanna, Snowy Slopes, Grove, Jagged Peaks,
   Frozen Peaks, Stony Peaks).
4. Group inland route: placed via one of the five groups (Beach, Badland, Middle, Plateau,
   Shattered), where a group table resolves temperature/humidity/weirdness, and the inland
   table places the group into terrain.

Flattening the space into a 6D cross-product is deliberately rejected (it would produce
58 rows for Jungle alone). Instead, group membership is kept as parameter chips, and the
terrain placement of those groups as collapsed contiguous spans.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from pipeline.enrich import EnrichError
from pipeline.enrich.resource_location import JoinTable

__all__ = [
    "NoiseExtractionResult",
    "NoiseLegend",
    "NoisePlacement",
    "NoiseReport",
    "NoiseSibling",
    "ParsedCell",
    "extract_worldgen_noise",
    "parse_noise_legend",
    "parse_wikitable_to_grid",
    "slice_overworld_section",
]

OVERWORLD_SECTION_HEADING = "=== Overworld ==="
CONTINENTALNESS_COL_NAMES = ("Coast", "Near-inland", "Mid-inland", "Far-inland")

# The prose lists seven continentalness bands, from Mushroom fields through the
# oceans to Far-inland. The inland table names only the last four as columns, so
# its column index plus this offset is the band's index on the shared axis.
INLAND_BAND_OFFSET = 3

GROUPS = (
    "Beach biomes",
    "Badland biomes",
    "Middle biomes",
    "Plateau biomes",
    "Shattered biomes",
)


class NoiseSibling(BaseModel, frozen=True):
    """Reference to a sibling biome placed under an opposite condition in the same cell."""

    id: str
    name: str


class NoisePlacement(BaseModel, frozen=True, populate_by_name=True):
    """One noise climate placement rule for an Overworld biome.

    Every parameter appears twice, and the pair is deliberate. The bare fields
    (`temperature`, `erosion`, ...) are display strings that already carry the
    level and its numeric range, and the detail table renders them verbatim. The
    `*_levels` fields beside them are the same facts as integers.

    The renderer cannot recover a level from a display string without parsing
    `T=3 (0.2~0.55)` back apart, and a renderer that re-parses a string this
    module formatted duplicates the knowledge of how to format it. So the
    integers ship alongside rather than instead: a summary that plots where a
    biome sits on the 0-4 temperature axis reads `temperature_levels`, and the
    row that spells the exact range reads `temperature`.

    Level indices are absolute and match the prose definitions:
    temperature and humidity run 0-4, erosion runs 0-6, and
    `continentalness_bands` indexes all seven bands the prose lists, from
    0 (Mushroom fields) through 3 (Coast) to 6 (Far-inland). The inland table's
    own four columns are the last four of those, which is why placements read
    from it carry bands 3-6.
    """

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
    sibling: NoiseSibling | None = None
    temperature_levels: tuple[int, ...] = Field(default=(), alias="temperatureLevels")
    humidity_levels: tuple[int, ...] = Field(default=(), alias="humidityLevels")
    erosion_levels: tuple[int, ...] = Field(default=(), alias="erosionLevels")
    continentalness_bands: tuple[int, ...] = Field(default=(), alias="continentalnessBands")
    pv_band: str | None = Field(default=None, alias="pvBand")


class NoiseLegend(BaseModel, frozen=True):
    """Parameter bands and ranges parsed from the prose level definitions."""

    temperature: tuple[str, ...]
    humidity: tuple[str, ...]
    continentalness: tuple[tuple[str, str], ...]
    erosion: tuple[str, ...]
    pv: tuple[tuple[str, str], ...]


class NoiseReport(BaseModel, frozen=True, populate_by_name=True):
    """Summary of the noise climate extraction pass."""

    unresolved_biome_names: tuple[str, ...] = Field(alias="unresolvedBiomeNames")
    biomes_without_placement: tuple[str, ...] = Field(alias="biomesWithoutPlacement")
    table_counts: Mapping[str, int] = Field(alias="tableCounts")
    overworld_biomes_covered: int = Field(alias="overworldBiomesCovered")


class NoiseExtractionResult(BaseModel, frozen=True):
    """The result of extracting noise placements from the World generation page."""

    placements_by_biome: Mapping[str, tuple[NoisePlacement, ...]]
    report: NoiseReport
    legend: NoiseLegend


class ParsedCell(BaseModel, frozen=True):
    """One expanded cell of a wikitable."""

    is_header: bool
    rowspan: int
    colspan: int
    text: str


def slice_overworld_section(wikitext: str) -> str:
    """Extract the Overworld subsection under Biomes from the World generation page.

    Slices by heading text, never by section index, because indices shift with wiki edits.
    """
    biomes_idx = wikitext.find("== Biomes")
    search_space = wikitext[biomes_idx:] if biomes_idx != -1 else wikitext

    overworld_match = re.search(r"^={3}\s*Overworld\s*={3}", search_space, re.MULTILINE)
    if overworld_match is None:
        raise EnrichError("could not find '=== Overworld ===' heading in wikitext.")

    offset = biomes_idx if biomes_idx != -1 else 0
    start = offset + overworld_match.start()
    after_start = start + len(overworld_match.group(0))

    next_heading = re.search(r"^={2,3}[^=].*?={2,3}", wikitext[after_start:], re.MULTILINE)
    if next_heading is None:
        return wikitext[start:]
    return wikitext[start : after_start + next_heading.start()]


def parse_noise_legend(section_text: str) -> NoiseLegend:
    """Parse noise parameter ranges from the prose definitions only.

    Ignores tooltip bounds because the wiki contains a typo in the non-inland tooltip
    for T=0 (missing minus sign, reads T=-1.0~0.45 instead of -1.0~-0.45).
    """
    t_match = re.search(
        r"'''Temperature'''.*?from level 0 to level (\d+) are:\s*([^\n]+)",
        section_text,
        re.DOTALL,
    )
    if not t_match:
        raise EnrichError("could not find Temperature level definitions in prose.")
    t_ranges = tuple(r.strip().rstrip(".") for r in t_match.group(2).split(","))

    h_match = re.search(
        r"'''Humidity'''.*?from level 0 to level (\d+) are:\s*([^\n]+)",
        section_text,
        re.DOTALL,
    )
    if not h_match:
        raise EnrichError("could not find Humidity level definitions in prose.")
    h_ranges = tuple(r.strip().rstrip(".") for r in h_match.group(2).split(","))

    erosion_pos = section_text.find("'''Erosion'''")
    if erosion_pos == -1:
        raise EnrichError("could not find ''''Erosion'''' heading in prose.")

    c_matches = re.findall(r"\*\s*If\s+([-\d.~]+):\s*([^\n]+)", section_text[:erosion_pos])
    if not c_matches:
        raise EnrichError("could not find Continentalness bands in prose.")
    c_bands = tuple((name.strip(), rng.strip()) for rng, name in c_matches)

    e_match = re.search(
        r"'''Erosion'''.*?from level 0 to level (\d+) are:\s*([^\n]+)",
        section_text,
        re.DOTALL,
    )
    if not e_match:
        raise EnrichError("could not find Erosion level definitions in prose.")
    e_ranges = tuple(r.strip().rstrip(".") for r in e_match.group(2).split(","))

    pv_pos = section_text.find("'''PV'''")
    depth_pos = section_text.find("'''Depth'''")
    if pv_pos == -1 or depth_pos == -1:
        raise EnrichError("could not find PV or Depth definitions in prose.")

    pv_matches = re.findall(r"\*\s*If\s+([-\d.~]+):\s*([^\n]+)", section_text[pv_pos:depth_pos])
    if not pv_matches:
        raise EnrichError("could not find PV bands in prose.")
    pv_bands = tuple((name.strip(), rng.strip()) for rng, name in pv_matches)

    return NoiseLegend(
        temperature=t_ranges,
        humidity=h_ranges,
        continentalness=c_bands,
        erosion=e_ranges,
        pv=pv_bands,
    )


def _split_depth_zero(text: str, sep: str) -> list[str]:
    """Split text on separator at depth 0, counting {{}} and [[]]."""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    i = 0
    n = len(text)
    sep_len = len(sep)
    while i < n:
        if text.startswith("{{", i) or text.startswith("[[", i):
            depth += 1
            buffer.append(text[i : i + 2])
            i += 2
            continue
        if (text.startswith("}}", i) or text.startswith("]]", i)) and depth > 0:
            depth -= 1
            buffer.append(text[i : i + 2])
            i += 2
            continue
        if depth == 0 and text.startswith(sep, i):
            parts.append("".join(buffer))
            buffer = []
            i += sep_len
            continue
        buffer.append(text[i])
        i += 1
    parts.append("".join(buffer))
    return parts


def parse_wikitable_to_grid(table_text: str) -> list[list[ParsedCell]]:
    """Parse a MediaWiki table into a 2D dense grid, expanding rowspan and colspan.

    Asserts that every grid cell is filled exactly once (no collisions, no unfilled holes).
    """
    raw_rows = re.split(r"\n\|-", table_text)
    parsed_rows: list[list[ParsedCell]] = []

    for row_str in raw_rows:
        cells: list[ParsedCell] = []
        for line in row_str.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("{|") or stripped.startswith("|}"):
                continue
            if stripped.startswith("!") or stripped.startswith("|"):
                mark = stripped[0]
                sep = mark + mark
                rest = stripped[1:]
                parts = _split_depth_zero(rest, sep)
                for cp in parts:
                    cparts = _split_depth_zero(cp.strip(), "|")
                    rowspan = 1
                    colspan = 1
                    if len(cparts) > 1 and any(
                        k in cparts[0] for k in ("rowspan", "colspan", "style", "class", "scope")
                    ):
                        attr_text = cparts[0]
                        content_text = "|".join(cparts[1:]).strip()
                        rm = re.search(r"rowspan=[\"']?(\d+)[\"']?", attr_text, re.IGNORECASE)
                        if rm:
                            rowspan = int(rm.group(1))
                        cm = re.search(r"colspan=[\"']?(\d+)[\"']?", attr_text, re.IGNORECASE)
                        if cm:
                            colspan = int(cm.group(1))
                    else:
                        content_text = cp.strip()
                    cells.append(
                        ParsedCell(
                            is_header=(mark == "!"),
                            rowspan=rowspan,
                            colspan=colspan,
                            text=content_text,
                        )
                    )
            else:
                if cells:
                    last = cells[-1]
                    cells[-1] = ParsedCell(
                        is_header=last.is_header,
                        rowspan=last.rowspan,
                        colspan=last.colspan,
                        text=last.text + "\n" + stripped,
                    )
        if cells:
            parsed_rows.append(cells)

    if not parsed_rows:
        return []

    grid: list[list[ParsedCell]] = []
    row_spans: dict[int, tuple[int, ParsedCell]] = {}

    for r_idx, row_cells in enumerate(parsed_rows):
        current_row: list[ParsedCell] = []
        col_idx = 0
        cell_iter = iter(row_cells)

        while True:
            if col_idx in row_spans:
                rem, c = row_spans[col_idx]
                current_row.append(c)
                if rem == 1:
                    del row_spans[col_idx]
                else:
                    row_spans[col_idx] = (rem - 1, c)
                col_idx += 1
                continue

            try:
                cell = next(cell_iter)
            except StopIteration:
                break

            rowspan = cell.rowspan
            colspan = cell.colspan

            for c_offset in range(colspan):
                target_col = col_idx + c_offset
                if target_col in row_spans:
                    raise EnrichError(
                        f"cell collision at row {r_idx}, col {target_col} in wikitable."
                    )
                current_row.append(cell)
                if rowspan > 1:
                    row_spans[target_col] = (rowspan - 1, cell)
            col_idx += colspan

        grid.append(current_row)

    if row_spans:
        raise EnrichError(f"unresolved rowspans remaining in wikitable: {row_spans}")

    # Assert uniform width across all rows
    widths = {len(r) for r in grid}
    if len(widths) > 1:
        raise EnrichError(f"inconsistent row widths in wikitable: {widths}")

    return grid


def _clean_cell_text(text: str) -> str:
    """Strip references and normalize whitespace."""
    cleaned = re.sub(r"<ref\b[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<ref\b[^>]*/>", "", cleaned)
    return cleaned.strip()


def _normalize_condition(cond: str | None) -> str | None:
    """Normalize fullwidth and ASCII parentheses and whitespace."""
    if not cond:
        return None
    c = cond.replace("\uff08", "(").replace("\uff09", ")").strip()
    return c if c else None


def _extract_parenthesized_condition(text: str) -> tuple[str, str | None]:
    """Extract trailing condition in either fullwidth or ASCII parentheses."""
    m = re.search(r"[\uff08(]([^\uff09)]+)[\uff09)]\s*$", text)
    if m is not None:
        base = text[: m.start()].strip()
        cond = _normalize_condition(m.group(1))
        return base, cond
    return text.strip(), None


def _collapse_contiguous(nums: Sequence[int]) -> list[tuple[int, int]]:
    """Collapse a sequence of integers into contiguous [start, end] pairs."""
    if not nums:
        return []
    sorted_nums = sorted(set(nums))
    ranges: list[tuple[int, int]] = []
    start = sorted_nums[0]
    end = start
    for n in sorted_nums[1:]:
        if n == end + 1:
            end = n
        else:
            ranges.append((start, end))
            start = end = n
    ranges.append((start, end))
    return ranges


def _format_e_range(start_e: int, end_e: int, legend: NoiseLegend) -> str:
    if start_e == end_e:
        rng = legend.erosion[start_e] if start_e < len(legend.erosion) else ""
        return f"E={start_e} ({rng})" if rng else f"E={start_e}"
    rng_start = legend.erosion[start_e].split("~")[0] if start_e < len(legend.erosion) else ""
    rng_end = legend.erosion[end_e].split("~")[-1] if end_e < len(legend.erosion) else ""
    combined_rng = f"{rng_start}~{rng_end}" if rng_start and rng_end else ""
    return f"E={start_e}-{end_e} ({combined_rng})" if combined_rng else f"E={start_e}-{end_e}"


def _format_c_range(start_idx: int, end_idx: int, legend: NoiseLegend) -> str:
    c_band_offset = INLAND_BAND_OFFSET
    if start_idx == end_idx:
        name = CONTINENTALNESS_COL_NAMES[start_idx]
        band_idx = start_idx + c_band_offset
        rng = legend.continentalness[band_idx][1] if band_idx < len(legend.continentalness) else ""
        return f"{name} ({rng})" if rng else name
    if start_idx == 0 and end_idx == 3:
        name = "Coast to Far-inland"
        rng = "-0.19~1.0"
        return f"{name} ({rng})"
    start_name = CONTINENTALNESS_COL_NAMES[start_idx]
    end_name = CONTINENTALNESS_COL_NAMES[end_idx]
    b_start = start_idx + c_band_offset
    b_end = end_idx + c_band_offset
    rng_s = (
        legend.continentalness[b_start][1].split("~")[0]
        if b_start < len(legend.continentalness)
        else ""
    )
    rng_e = (
        legend.continentalness[b_end][1].split("~")[-1]
        if b_end < len(legend.continentalness)
        else ""
    )
    combined = f"{rng_s}~{rng_e}" if rng_s and rng_e else ""
    return (
        f"{start_name} to {end_name} ({combined})"
        if combined
        else f"{start_name} to {end_name}"
    )


def _format_pv_range(pv_name: str, legend: NoiseLegend) -> str:
    pv_lookup = dict(legend.pv)
    if pv_name in pv_lookup:
        return f"{pv_name} ({pv_lookup[pv_name]})"
    if pv_name == "High~Peaks":
        h_rng = pv_lookup.get("High", "0.2~0.7").split("~")[0]
        p_rng = pv_lookup.get("Peaks", "0.7~1.0").split("~")[-1]
        return f"High~Peaks ({h_rng}~{p_rng})"
    return pv_name


def extract_worldgen_noise(
    wikitext: str,
    *,
    join_table: JoinTable | None = None,
    biome_registry: Sequence[str] | Mapping[str, Any] | None = None,
) -> NoiseExtractionResult:
    """Extract noise climate parameters from World generation section 4."""
    section = slice_overworld_section(wikitext)
    tables = list(re.finditer(r"\{\|.*?\n\|\}", section, re.DOTALL))
    if len(tables) != 8:
        raise EnrichError(
            f"expected exactly 8 tables in World generation Overworld section, found {len(tables)}."
        )

    legend = parse_noise_legend(section)

    # Build known registry set
    known_ids: set[str] = set()
    if biome_registry is not None:
        raw_ids = set(
            biome_registry
            if isinstance(biome_registry, Sequence)
            else biome_registry.keys()
        )
        known_ids = {
            id if id.startswith("minecraft:") else f"minecraft:{id}"
            for id in raw_ids
        }

    # Biome resolver: resolves {{BiomeLink|X}} through JoinTable or display names against registry
    unresolved_names: set[str] = set()

    def resolve_biome(name: str) -> tuple[str, str] | None:
        cleaned_name = name.strip()
        # 1. Try JoinTable
        if join_table is not None:
            candidates = join_table.candidates(cleaned_name, kind="biome")
            for c in candidates:
                c_id = (
                    c.registry_id
                    if c.registry_id.startswith("minecraft:")
                    else f"minecraft:{c.registry_id}"
                )
                if not known_ids or c_id in known_ids:
                    return c_id, cleaned_name
            for e in join_table.entries:
                if e.kind == "biome" and (
                    e.display_name.casefold() == cleaned_name.casefold()
                    or e.page.casefold() == cleaned_name.casefold()
                ):
                    e_id = (
                        e.registry_id
                        if e.registry_id.startswith("minecraft:")
                        else f"minecraft:{e.registry_id}"
                    )
                    if not known_ids or e_id in known_ids:
                        return e_id, cleaned_name

        # 2. Try matching against known registry IDs
        slug = cleaned_name.casefold().replace(" ", "_")
        candidate_id = f"minecraft:{slug}"
        if not known_ids or candidate_id in known_ids:
            return candidate_id, cleaned_name

        unresolved_names.add(cleaned_name)
        return None

    placements_by_biome: dict[str, list[NoisePlacement]] = {}
    table_counts: dict[str, int] = {}

    def add_placement(b_id: str, placement: NoisePlacement) -> None:
        placements_by_biome.setdefault(b_id, []).append(placement)

    # -------------------------------------------------------------------------
    # Table 0: Depth
    # -------------------------------------------------------------------------
    grid0 = parse_wikitable_to_grid(tables[0].group(0))
    t0_count = 0
    for r in range(1, len(grid0)):
        depth_str = grid0[r][0].text.replace("D=", "").strip()
        addl_str = _clean_cell_text(grid0[r][1].text)
        bio_text = _clean_cell_text(grid0[r][2].text)
        if "surface biomes" in bio_text.casefold():
            continue
        for m in re.finditer(r"\{\{BiomeLink\|([^|}]+)", bio_text):
            resolved = resolve_biome(m.group(1))
            if resolved:
                b_id, _ = resolved
                addl = addl_str.replace("\n", ", ") if addl_str and addl_str != "N/A" else None
                add_placement(
                    b_id,
                    NoisePlacement(
                        route="depth",
                        depth=depth_str,
                        additional_requirement=addl,
                    ),
                )
                t0_count += 1
    table_counts["depth"] = t0_count

    # -------------------------------------------------------------------------
    # Table 1: Non-inland surface
    # -------------------------------------------------------------------------
    grid1 = parse_wikitable_to_grid(tables[1].group(0))
    t1_count = 0
    for r in range(1, len(grid1)):
        t_cell = grid1[r][0].text
        tm = re.search(r"T(?:\{\{=\}\}|=)(\d+)", t_cell)
        t_level = int(tm.group(1)) if tm else r - 1
        t_str = f"T={t_level} ({legend.temperature[t_level]})"

        for col_idx in range(1, 4):
            cell = grid1[r][col_idx]
            txt = _clean_cell_text(cell.text)
            c_desc = ""
            # Band indices are absolute over the seven prose bands, so the ocean
            # side of the axis lands below Coast rather than restarting at zero.
            c_bands: tuple[int, ...] = ()
            if col_idx == 1 and cell.colspan == 2:
                c_desc = "Oceans, Deep oceans (-1.05~-0.19)"
                c_bands = (1, 2)
            elif col_idx == 1:
                c_desc = "Oceans (-0.455~-0.19)"
                c_bands = (2,)
            elif col_idx == 2:
                c_desc = "Deep oceans (-1.05~-0.455)"
                c_bands = (1,)
            elif col_idx == 3:
                c_desc = "Mushroom fields (-1.2~-1.05)"
                c_bands = (0,)

            if col_idx == 2 and cell.colspan > 1:
                continue

            for m in re.finditer(r"\{\{BiomeLink\|([^|}]+)", txt):
                resolved = resolve_biome(m.group(1))
                if resolved:
                    b_id, _ = resolved
                    spans_all_t = cell.rowspan >= 5
                    eff_t = "T=0-4 (-1.0~1.0)" if spans_all_t else t_str
                    add_placement(
                        b_id,
                        NoisePlacement(
                            route="non_inland",
                            temperature=eff_t,
                            continentalness=c_desc,
                            temperature_levels=(0, 1, 2, 3, 4) if spans_all_t else (t_level,),
                            continentalness_bands=c_bands,
                        ),
                    )
                    t1_count += 1
    table_counts["non_inland"] = t1_count

    # -------------------------------------------------------------------------
    # Table 2: Inland surface
    # -------------------------------------------------------------------------
    grid2 = parse_wikitable_to_grid(tables[2].group(0))

    def extract_inland_items(cell_text: str) -> list[tuple[str, str, str | None]]:
        cleaned = _clean_cell_text(cell_text)
        items: list[tuple[str, str, str | None]] = []
        for line in re.split(r"<br\s*/?>|\n", cleaned):
            s = line.strip()
            if not s:
                continue
            base, cond = _extract_parenthesized_condition(s)
            bm = re.search(r"\{\{BiomeLink\|([^|}]+)", base)
            if bm:
                items.append(("biome", bm.group(1).strip(), cond))
            else:
                for g in GROUPS:
                    if g.casefold() in base.casefold():
                        items.append(("group", g, cond))
                        break
        return items

    by_condition: dict[tuple[str, str, str, str | None], dict[int, set[int]]] = {}
    cell_siblings_by_biome: dict[str, NoiseSibling] = {}

    for r in range(1, len(grid2)):
        e_level = int(grid2[r][0].text.replace("E=", "").strip())
        pv = grid2[r][1].text.strip()
        for c_idx in range(2, 6):
            cont_idx = c_idx - 2
            raw_cell = grid2[r][c_idx].text
            items = extract_inland_items(raw_cell)

            biome_items = [it for it in items if it[0] == "biome"]
            if len(biome_items) == 2:
                b1_res = resolve_biome(biome_items[0][1])
                b2_res = resolve_biome(biome_items[1][1])
                if b1_res and b2_res:
                    cell_siblings_by_biome[b1_res[0]] = NoiseSibling(id=b2_res[0], name=b2_res[1])
                    cell_siblings_by_biome[b2_res[0]] = NoiseSibling(id=b1_res[0], name=b1_res[1])

            for kind, name, cond in items:
                k = (kind, name, pv, cond)
                by_condition.setdefault(k, {}).setdefault(e_level, set()).add(cont_idx)

    c_collapsed: list[tuple[str, str, str, str | None, int, int, int]] = []
    for (kind, name, pv, cond), e_to_conts in sorted(
        by_condition.items(),
        key=lambda x: (x[0][0], x[0][1], x[0][2], x[0][3] or ""),
    ):
        for e_level, cont_set in sorted(e_to_conts.items()):
            for c_start, c_end in _collapse_contiguous(sorted(cont_set)):
                c_collapsed.append((kind, name, pv, cond, c_start, c_end, e_level))

    grouped_e: dict[tuple[str, str, str, str | None, int, int], list[int]] = {}
    for kind, name, pv, cond, c_start, c_end, e_level in c_collapsed:
        gk = (kind, name, pv, cond, c_start, c_end)
        grouped_e.setdefault(gk, []).append(e_level)

    group_terrain_placements: dict[str, list[NoisePlacement]] = {}
    t2_direct_count = 0

    for (kind, name, pv, cond, c_start, c_end), e_levels in sorted(
        grouped_e.items(),
        key=lambda x: (x[0][0], x[0][1], x[0][2], x[0][3] or "", x[0][4], x[0][5]),
    ):
        for e_start, e_end in _collapse_contiguous(e_levels):
            e_formatted = _format_e_range(e_start, e_end, legend)
            c_formatted = _format_c_range(c_start, c_end, legend)
            pv_formatted = _format_pv_range(pv, legend)
            e_span = tuple(range(e_start, e_end + 1))
            # The inland table's four columns are the last four prose bands, so
            # shift by 3 to keep one absolute axis shared with the ocean side.
            c_span = tuple(range(c_start + INLAND_BAND_OFFSET, c_end + INLAND_BAND_OFFSET + 1))

            if kind == "biome":
                resolved = resolve_biome(name)
                if resolved:
                    b_id, _ = resolved
                    sib = cell_siblings_by_biome.get(b_id)
                    add_placement(
                        b_id,
                        NoisePlacement(
                            route="direct_inland",
                            erosion=e_formatted,
                            pv=pv_formatted,
                            continentalness=c_formatted,
                            condition=cond,
                            sibling=sib,
                            erosion_levels=e_span,
                            continentalness_bands=c_span,
                            pv_band=pv,
                        ),
                    )
                    t2_direct_count += 1
            else:
                p = NoisePlacement(
                    route="group_terrain",
                    group=name,
                    erosion=e_formatted,
                    pv=pv_formatted,
                    continentalness=c_formatted,
                    condition=cond,
                    erosion_levels=e_span,
                    continentalness_bands=c_span,
                    pv_band=pv,
                )
                group_terrain_placements.setdefault(name, []).append(p)

    table_counts["direct_inland"] = t2_direct_count

    # -------------------------------------------------------------------------
    # Tables 3 to 7: Group tables
    # -------------------------------------------------------------------------
    groups_by_biome: dict[str, set[str]] = {}

    def extract_group_cell(
        cell_text: str,
        group_name: str,
        temp_str: str,
        hum_str: str,
        *,
        t_levels: tuple[int, ...] = (),
        h_levels: tuple[int, ...] = (),
    ) -> int:
        cleaned = _clean_cell_text(cell_text)
        lines = [
            line_item.strip()
            for line_item in re.split(r"<br\s*/?>|\n", cleaned)
            if line_item.strip()
        ]
        matched_biomes: list[tuple[str, str, str | None]] = []

        for line_item in lines:
            base, cond = _extract_parenthesized_condition(line_item)
            bm = re.search(r"\{\{BiomeLink\|([^|}]+)", base)
            if bm:
                matched_biomes.append((bm.group(1).strip(), base, cond))

        sibs: dict[str, NoiseSibling] = {}
        if len(matched_biomes) == 2:
            r1 = resolve_biome(matched_biomes[0][0])
            r2 = resolve_biome(matched_biomes[1][0])
            if r1 and r2:
                sibs[r1[0]] = NoiseSibling(id=r2[0], name=r2[1])
                sibs[r2[0]] = NoiseSibling(id=r1[0], name=r1[1])

        placed_count = 0
        for name, _base, cond in matched_biomes:
            resolved = resolve_biome(name)
            if resolved:
                b_id, _ = resolved
                groups_by_biome.setdefault(b_id, set()).add(group_name)
                sib = sibs.get(b_id)
                add_placement(
                    b_id,
                    NoisePlacement(
                        route="group",
                        group=group_name,
                        temperature=temp_str,
                        humidity=hum_str,
                        weirdness=cond if cond and ("W<" in cond or "W>" in cond) else None,
                        condition=cond if cond and not ("W<" in cond or "W>" in cond) else None,
                        sibling=sib,
                        temperature_levels=t_levels,
                        humidity_levels=h_levels,
                    ),
                )
                placed_count += 1
        return placed_count

    # Table 3: Beach biomes
    grid3 = parse_wikitable_to_grid(tables[3].group(0))
    t3_count = 0
    for r in range(1, len(grid3)):
        t_str_raw = grid3[r][0].text.replace("T=", "").strip()
        t_indices = [int(x) for x in re.findall(r"\d+", t_str_raw)]
        if len(t_indices) == 1:
            t_formatted = f"T={t_indices[0]} ({legend.temperature[t_indices[0]]})"
        else:
            t_s = legend.temperature[t_indices[0]].split("~")[0]
            t_e = legend.temperature[t_indices[-1]].split("~")[-1]
            t_formatted = f"T={t_str_raw} ({t_s}~{t_e})"
        # Beach placement does not read humidity at all -- the prose says the
        # biome "is related only to the temperature value" -- so every humidity
        # level qualifies rather than none.
        t3_count += extract_group_cell(
            grid3[r][1].text,
            "Beach biomes",
            t_formatted,
            "Any",
            t_levels=tuple(t_indices),
            h_levels=(0, 1, 2, 3, 4),
        )
    table_counts["beach"] = t3_count

    # Table 4: Badland biomes
    grid4 = parse_wikitable_to_grid(tables[4].group(0))
    t4_count = 0
    for r in range(1, len(grid4)):
        h_str_raw = grid4[r][0].text.replace("H=", "").strip()
        h_indices = [int(x) for x in re.findall(r"\d+", h_str_raw)]
        if len(h_indices) == 1:
            h_formatted = f"H={h_indices[0]} ({legend.humidity[h_indices[0]]})"
        else:
            h_s = legend.humidity[h_indices[0]].split("~")[0]
            h_e = legend.humidity[h_indices[-1]].split("~")[-1]
            h_formatted = f"H={h_str_raw} ({h_s}~{h_e})"
        t4_count += extract_group_cell(
            grid4[r][1].text,
            "Badland biomes",
            "T=4 (0.55~1.0)",
            h_formatted,
            t_levels=(4,),
            h_levels=tuple(h_indices),
        )
    table_counts["badland"] = t4_count

    # Table 5: Middle biomes
    grid5 = parse_wikitable_to_grid(tables[5].group(0))
    t5_count = 0
    for r in range(1, len(grid5)):
        h_level = r - 1
        h_formatted = f"H={h_level} ({legend.humidity[h_level]})"
        for c in range(1, 6):
            t_level = c - 1
            t_formatted = f"T={t_level} ({legend.temperature[t_level]})"
            t5_count += extract_group_cell(
                grid5[r][c].text,
                "Middle biomes",
                t_formatted,
                h_formatted,
                t_levels=(t_level,),
                h_levels=(h_level,),
            )
    table_counts["middle"] = t5_count

    # Table 6: Plateau biomes
    grid6 = parse_wikitable_to_grid(tables[6].group(0))
    t6_count = 0
    for r in range(1, len(grid6)):
        h_level = r - 1
        h_formatted = f"H={h_level} ({legend.humidity[h_level]})"
        for c in range(1, 6):
            t_level = c - 1
            t_formatted = f"T={t_level} ({legend.temperature[t_level]})"
            t6_count += extract_group_cell(
                grid6[r][c].text,
                "Plateau biomes",
                t_formatted,
                h_formatted,
                t_levels=(t_level,),
                h_levels=(h_level,),
            )
    table_counts["plateau"] = t6_count

    # Table 7: Shattered biomes
    grid7 = parse_wikitable_to_grid(tables[7].group(0))
    t7_count = 0
    t_headers = ["T=0~1 (-1.0~-0.15)", "T=2 (-0.15~0.2)", "T=3 (0.2~0.55)", "T=4 (0.55~1.0)"]
    h_headers = ["H=0~1 (-1.0~-0.1)", "H=2 (-0.1~0.1)", "H=3 (0.1~0.3)", "H=4 (0.3~1.0)"]
    # This table pairs its first two levels into one column and one row, so the
    # level tuples run alongside the headers rather than being derived from the
    # index the way the middle and plateau tables allow.
    t_header_levels: list[tuple[int, ...]] = [(0, 1), (2,), (3,), (4,)]
    h_header_levels: list[tuple[int, ...]] = [(0, 1), (2,), (3,), (4,)]
    for r in range(1, len(grid7)):
        h_formatted = h_headers[r - 1]
        for c in range(1, 5):
            t_formatted = t_headers[c - 1]
            t7_count += extract_group_cell(
                grid7[r][c].text,
                "Shattered biomes",
                t_formatted,
                h_formatted,
                t_levels=t_header_levels[c - 1],
                h_levels=h_header_levels[r - 1],
            )
    table_counts["shattered"] = t7_count

    # Attach group terrain placements to group biomes
    for b_id, g_names in groups_by_biome.items():
        for g_name in sorted(g_names):
            terrain_rows = group_terrain_placements.get(g_name, [])
            for tr in terrain_rows:
                add_placement(b_id, tr)

    biomes_without_placement: list[str] = []

    frozen_placements: dict[str, tuple[NoisePlacement, ...]] = {
        b_id: tuple(plist) for b_id, plist in placements_by_biome.items()
    }

    report = NoiseReport(
        unresolved_biome_names=tuple(sorted(unresolved_names)),
        biomes_without_placement=tuple(sorted(biomes_without_placement)),
        table_counts=table_counts,
        overworld_biomes_covered=len(frozen_placements),
    )

    return NoiseExtractionResult(
        placements_by_biome=frozen_placements,
        report=report,
        legend=legend,
    )
