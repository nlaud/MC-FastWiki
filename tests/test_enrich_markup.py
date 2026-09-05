"""The wikitext primitives, and the edition filter that is the whole risk of Phase 2.

`pipeline.enrich.markup` is infobox-agnostic -- it knows about templates,
links, and edition markers, and nothing about `health` or `damage` -- so this
suite tests it the same way: nested template scanning, bracket-safe argument
splitting, and every one of the four edition marker forms the module docstring
names, including both halves of the region-versus-block rule that is the
correctness-critical part of the whole parser.

Every worked example here is quoted from the implementation brief, which
verified each one against the live wiki on 2026-08-30.
"""

import pytest

from pipeline.enrich.markup import (
    CONNECTING_WORDS,
    DIFFICULTY_WORDS,
    HORIZONTAL_RULE,
    REACHED_DEFAULT,
    REACHED_INHERITED_BLOCK,
    REACHED_INHERITED_REGION,
    REACHED_OWN_MARKER,
    Edition,
    HeadingKind,
    classify_heading,
    find_template,
    scope_editions,
    split_lines,
    split_template,
    strip_edition_markers,
    strip_markup,
)

# --- find_template: brace-depth scanning ------------------------------------


def test_find_template_finds_a_flat_call() -> None:
    found = find_template("Easy: {{hp|2.5}}", "hp")
    assert len(found) == 1
    assert found[0].text == "{{hp|2.5}}"


def test_find_template_finds_every_occurrence_in_document_order() -> None:
    """Creeper's `damage` holds nine `{{hp|...}}` calls; this pins the ordering."""
    text = "Easy: {{hp|22.5}}<br>Normal: {{hp|43}}<br>Hard: {{hp|64.5}}"
    found = find_template(text, "hp")
    assert [item.text for item in found] == ["{{hp|22.5}}", "{{hp|43}}", "{{hp|64.5}}"]


def test_find_template_is_case_insensitive_on_the_template_name() -> None:
    """`drop` and `Drop` name the same template (Zoglin, Allay, Copper Golem)."""
    assert find_template("{{Drop|Item|Lead}}", "drop")[0].text == "{{Drop|Item|Lead}}"
    assert find_template("{{drop|Item|Lead}}", "Drop")[0].text == "{{drop|Item|Lead}}"


def test_find_template_does_not_match_a_different_name() -> None:
    assert find_template("{{ItemLink|Raw Salmon}}", "drop") == ()


def test_find_template_handles_a_nested_template_as_one_span() -> None:
    """A regex cannot match this: a naive `\\{\\{[^{}]*\\}\\}` would stop at the inner `}}`."""
    found = find_template("{{hp|{{x|1}}}}", "hp")
    assert len(found) == 1
    assert found[0].text == "{{hp|{{x|1}}}}"


def test_find_template_reports_the_span_positions() -> None:
    found = find_template("xx{{hp|5}}yy", "hp")
    assert (found[0].start, found[0].end) == (2, 10)


# --- split_template: bracket-safe argument splitting ------------------------


def test_split_template_reads_the_name_and_one_positional_argument() -> None:
    parsed = split_template("{{hp|20}}")
    assert parsed.name == "hp"
    assert parsed.positional == ("20",)
    assert parsed.named == {}


def test_split_template_accepts_a_body_with_no_outer_braces() -> None:
    parsed = split_template("hp|20")
    assert parsed.name == "hp"
    assert parsed.positional == ("20",)


def test_split_template_reads_a_named_argument() -> None:
    """`{{hp|10|mob=1}}` -- Pig's health, an extra named argument."""
    parsed = split_template("{{hp|10|mob=1}}")
    assert parsed.positional == ("10",)
    assert parsed.named == {"mob": "1"}


def test_split_template_keeps_positional_order_around_a_named_argument() -> None:
    """`{{drop|Item|id=Raw Beef|Meat}}` -- Wolf's meat drop; `Meat` is the display text."""
    parsed = split_template("{{drop|Item|id=Raw Beef|Meat}}")
    assert parsed.positional == ("Item", "Meat")
    assert parsed.named == {"id": "Raw Beef"}


def test_split_template_does_not_shred_a_nested_template_on_its_internal_pipe() -> None:
    """The trap the module docstring names: a naive `str.split('|')` would cut this apart."""
    parsed = split_template("{{drop|Item|{{note|x|y}}}}")
    assert parsed.positional == ("Item", "{{note|x|y}}")


def test_split_template_does_not_split_on_a_pipe_inside_a_wiki_link() -> None:
    parsed = split_template("{{x|[[Page|label]]|2}}")
    assert parsed.positional == ("[[Page|label]]", "2")


def test_split_template_does_not_split_on_a_pipe_inside_a_ref_block() -> None:
    parsed = split_template('{{x|1|<ref name="n">a|b</ref>}}')
    assert parsed.positional == ("1", '<ref name="n">a|b</ref>')


def test_split_template_reads_multiple_positional_arguments() -> None:
    parsed = split_template("{{only|be|ee|short=1}}")
    assert parsed.positional == ("be", "ee")
    assert parsed.named == {"short": "1"}


def test_split_template_does_not_read_an_argument_out_of_an_html_comment() -> None:
    """A commented-out field does not exist, so its pipe must not begin an argument.

    Taken from the live Evoker page, which carries `<!-- | speed = 0.5 -->`
    between two real fields. MediaWiki strips comments before expanding a
    template, so the page has no `speed` field at all; a split that ran first
    would invent one holding `0.5 -->`.
    """
    parsed = split_template("{{Infobox entity|size = 1<!-- | speed = 0.5 -->|spawn = Raids}}")
    assert set(parsed.named) == {"size", "spawn"}


def test_split_template_lets_a_live_field_win_over_a_commented_out_copy() -> None:
    """The reason the comment rule is a correctness guard and not tidying.

    A stale commented-out duplicate below a live field would otherwise be read
    second and overwrite it, answering a number an editor had already deleted.
    """
    parsed = split_template("{{Infobox entity|health = {{hp|20}}<!-- |health = {{hp|999}} -->}}")
    assert parsed.named["health"] == "{{hp|20}}"


def test_split_template_treats_an_unclosed_comment_as_running_to_the_end() -> None:
    """MediaWiki comments out the rest of the text after a `<!--` with no closer."""
    parsed = split_template("{{Infobox entity|health = {{hp|20}}<!-- |speed = 0.5}}")
    assert set(parsed.named) == {"health"}


# --- split_lines -------------------------------------------------------------


def test_split_lines_splits_on_br() -> None:
    assert split_lines("a<br>b") == ("a", "b")


@pytest.mark.parametrize("br", ["<br>", "<br/>", "<br />", "<BR>", "<Br/>"])
def test_split_lines_accepts_every_br_variant(br: str) -> None:
    assert split_lines(f"a{br}b") == ("a", "b")


def test_split_lines_splits_on_a_bare_newline() -> None:
    assert split_lines("a\nb") == ("a", "b")


def test_split_lines_drops_a_leading_list_marker() -> None:
    """`* {{Drop|Item|Axe}}` -- Copper Golem's list-marker separated usable items."""
    assert split_lines("* {{drop|Item|Axe}}") == ("{{drop|Item|Axe}}",)


def test_split_lines_drops_blank_lines() -> None:
    assert split_lines("a<br><br>b") == ("a", "b")


def test_split_lines_splits_on_hr_and_keeps_it_as_its_own_line() -> None:
    """`<hr>` is not `<br>`-adjacent in the source, and it must still become its own line.

    Cat's `health` field glues it directly onto the surrounding text with no
    `<br>` beside it at all.
    """
    assert split_lines("{{hp|10}}<hr>'''{{BE}}:'''") == (
        "{{hp|10}}",
        HORIZONTAL_RULE,
        "'''{{BE}}:'''",
    )


def test_split_lines_does_not_split_a_br_hidden_inside_a_comment() -> None:
    """Cat's `speed` field: `0.3<!--Walking: 0.24<br>Sprinting: 0.399-->`.

    A comment can hold its own `<br>`; splitting on it before the comment is
    gone would cut the comment in half and leave an unclosed `<!--` behind.
    """
    assert split_lines("0.3<!--Walking: 0.24<br>Sprinting: 0.399-->") == ("0.3",)


def test_split_lines_does_not_split_a_br_hidden_inside_a_ref() -> None:
    assert split_lines("Passive<ref>a<br>b</ref>") == ("Passive",)


# --- strip_markup --------------------------------------------------------------


def test_strip_markup_removes_bold() -> None:
    assert strip_markup("'''Regular:'''") == "Regular:"


def test_strip_markup_removes_italic() -> None:
    assert strip_markup("''Explosion varies.''") == "Explosion varies."


def test_strip_markup_removes_a_file_link_entirely() -> None:
    assert strip_markup("[[File:Wither (effect).png|16px]] Wither:") == "Wither:"


def test_strip_markup_removes_small_tags_but_keeps_their_content() -> None:
    assert strip_markup("<small>(baby only)</small>") == "(baby only)"


def test_strip_markup_removes_a_ref_block_entirely() -> None:
    text = 'Passive<ref group="note" name="passive">Can unintentionally hurt.</ref>'
    assert strip_markup(text) == "Passive"


def test_strip_markup_removes_an_html_comment() -> None:
    assert strip_markup("0.3<!--Walking: 0.24-->") == "0.3"


def test_strip_markup_resolves_a_piped_link_to_its_label() -> None:
    assert strip_markup("[[Tipped Arrow|Arrow of Slowness]]") == "Arrow of Slowness"


def test_strip_markup_resolves_a_bare_link_to_the_page_name() -> None:
    assert strip_markup("[[Peaceful]] mode") == "Peaceful mode"


def test_strip_markup_unescapes_html_entities() -> None:
    assert strip_markup("Bottle o&#39; Enchanting") == "Bottle o' Enchanting"


def test_strip_markup_collapses_whitespace() -> None:
    assert strip_markup("a   b\n\nc") == "a b c"


def test_strip_markup_leaves_a_generic_template_in_place() -> None:
    """`{{ItemLink|Bow}}` is not markup to this function -- a caller reads templates directly."""
    assert strip_markup("{{ItemLink|Bow}}: ") == "{{ItemLink|Bow}}:"


# --- strip_markup: the advancement-description options --------------------------


def test_strip_markup_removes_a_sup_footnote_with_its_content() -> None:
    """`Adventuring Time`: stripping only the tags leaves `55[until: ...]` on screen."""
    text = 'Visit 55<sup class="nowrap Inline-Template">[<i>until: Third Drop</i>]</sup> biomes'
    assert strip_markup(text) == "Visit 55 biomes"


def test_strip_markup_removes_a_category_tag() -> None:
    """The `Upcoming` marker template expands into one, and it is filing, not text."""
    assert strip_markup("56 biomes[[Category:Upcoming]]") == "56 biomes"


def test_strip_markup_removes_a_zero_width_space() -> None:
    """`_WHITESPACE` matches real whitespace only, so this survives every other pass."""
    assert strip_markup("55\u200b/56") == "55/56"


def test_strip_markup_keeps_links_when_asked() -> None:
    """Decision 13: the advancement renderer turns these into live entity links."""
    text = "Visit [[Badlands|Badlands]]"
    assert strip_markup(text, keep_links=True) == text


def test_strip_markup_flattens_a_list_into_running_prose() -> None:
    """`Adventuring Time`'s biome list, which the wiki writes as an `hlist`."""
    text = "<div>Visit these biomes:</div><div>\n* Badlands\n* Beach\n* Desert</div>"
    assert strip_markup(text, flatten_lists=True) == "Visit these biomes: Badlands, Beach, Desert"


def test_strip_markup_breaks_a_sentence_that_follows_a_flattened_list() -> None:
    """Without the break, `Adventuring Time` glues its last biome to the next sentence."""
    text = "<div>\n* Badlands\n* Wooded Badlands</div><div>The advancement is Overworld only.</div>"
    flattened = strip_markup(text, flatten_lists=True)
    assert flattened == "Badlands, Wooded Badlands. The advancement is Overworld only."


def test_strip_markup_does_not_break_a_mid_sentence_continuation() -> None:
    """`Mine Stone` continues `in the inventory` after its list -- a period there is a fragment."""
    text = (
        "<div>Have one of these stones:</div><div>\n* Cobblestone</div>"
        "<div>in the inventory</div>"
    )
    assert (
        strip_markup(text, flatten_lists=True)
        == "Have one of these stones: Cobblestone in the inventory"
    )


def test_strip_markup_keeps_a_sentence_period_the_wiki_wrote() -> None:
    """The trailing-separator cleanup must not eat real punctuation."""
    text = "Have a [[crafting table]]."
    assert strip_markup(text, keep_links=True) == text


def test_strip_markup_leaves_lists_alone_by_default() -> None:
    """An infobox field's own lines are meaningful, so flattening is opt-in."""
    assert strip_markup("* Badlands\n* Beach") == "* Badlands * Beach"


# --- strip_edition_markers -----------------------------------------------------


def test_strip_edition_markers_removes_a_trailing_only_template() -> None:
    """Zombie's `health`: the `(leaders)` label survives once the marker is gone."""
    text = strip_edition_markers("{{hp|40}} to {{hp|100}} (leaders){{only|JE|short=1}}")
    assert text == "{{hp|40}} to {{hp|100}} (leaders)"


def test_strip_edition_markers_leaves_a_non_edition_template_alone() -> None:
    assert strip_edition_markers("{{ItemLink|Bow}}") == "{{ItemLink|Bow}}"


# --- classify_heading: the four marker forms ------------------------------


def test_a_template_heading_reduces_to_a_region() -> None:
    """`'''{{IN|BE}}:'''` -- Creeper's damage field."""
    result = classify_heading("'''{{IN|BE}}:'''")
    assert result.kind is HeadingKind.REGION
    assert result.edition is Edition.BEDROCK


def test_a_bare_template_heading_with_no_bold_is_also_a_region() -> None:
    """`{{BE}}:` -- Villager's damage field, no bold at all."""
    result = classify_heading("{{BE}}:")
    assert result.kind is HeadingKind.REGION
    assert result.edition is Edition.BEDROCK


def test_a_plain_text_heading_with_no_template_at_all_is_a_region() -> None:
    """`'''Bedrock:'''` -- the Bogged page, verified to carry no template."""
    result = classify_heading("'''Bedrock:'''")
    assert result.kind is HeadingKind.REGION
    assert result.edition is Edition.BEDROCK


def test_the_java_counterpart_positively_marks_a_keep() -> None:
    result = classify_heading("'''{{IN|Java}}:'''")
    assert result.kind is HeadingKind.REGION
    assert result.edition is Edition.JAVA


def test_je_short_form_is_read_as_java() -> None:
    assert classify_heading("'''{{JE}}:'''").edition is Edition.JAVA


def test_an_only_template_names_bedrock() -> None:
    """`{{only|bedrock}}` -- the inline suffix form, here on a line of its own."""
    result = classify_heading("Nothing:{{only|bedrock}}")
    assert result.kind is HeadingKind.BLOCK
    assert result.edition is Edition.BEDROCK


def test_an_only_template_with_be_and_ee_still_names_bedrock() -> None:
    """`{{only|be|ee|short=1}}` -- Education Edition folds into Bedrock; this project keeps
    neither.
    """
    assert classify_heading("X:{{only|be|ee|short=1}}").edition is Edition.BEDROCK


def test_an_only_template_naming_java_is_java() -> None:
    assert classify_heading("X:{{only|JE|short=1}}").edition is Edition.JAVA


# --- classify_heading: telling region apart from block ----------------------


def test_in_be_reduces_to_nothing_and_is_a_region() -> None:
    result = classify_heading("'''{{IN|BE}}:'''")
    assert result.kind is HeadingKind.REGION
    assert result.label == ""


def test_in_je_with_the_connecting_word_in_reduces_to_a_region() -> None:
    """`'''In {{JE}}:'''` -- Cow's size field. `in` is dropped as a connecting word."""
    result = classify_heading("'''In {{JE}}:'''")
    assert result.kind is HeadingKind.REGION


def test_adult_in_bedrock_leaves_a_variant_name_and_is_a_block() -> None:
    """`'''Adult {{IN|Bedrock}}:'''` -- Zombie's size field."""
    result = classify_heading("'''Adult {{IN|Bedrock}}:'''")
    assert result.kind is HeadingKind.BLOCK
    assert result.edition is Edition.BEDROCK
    assert result.label == "Adult"


def test_adult_in_je_leaves_a_variant_name_and_is_a_block() -> None:
    """`'''Adult in {{JE}}:'''` -- Chicken's size field."""
    result = classify_heading("'''Adult in {{JE}}:'''")
    assert result.kind is HeadingKind.BLOCK
    assert result.label == "Adult"


def test_while_jumping_with_a_trailing_only_suffix_is_a_block() -> None:
    """`'''While jumping:'''{{only|java|short=1}}` -- Goat's size field."""
    result = classify_heading("'''While jumping:'''{{only|java|short=1}}")
    assert result.kind is HeadingKind.BLOCK
    assert result.edition is Edition.JAVA
    assert result.label == "While jumping"


def test_while_digging_emerging_with_an_embedded_only_is_a_block() -> None:
    """`'''While digging/emerging{{only|JE|short=1}}:'''` -- Warden's size field."""
    result = classify_heading("'''While digging/emerging{{only|JE|short=1}}:'''")
    assert result.kind is HeadingKind.BLOCK
    assert result.label == "While digging/emerging"


def test_a_heading_naming_two_editions_at_once_is_unparseable() -> None:
    """A contradiction is reported, not guessed at either way."""
    result = classify_heading("'''{{IN|Java}}{{IN|Bedrock}}:'''")
    assert result.kind is HeadingKind.UNPARSEABLE


# --- classify_heading: what is not a heading --------------------------------


def test_a_value_line_is_not_a_heading() -> None:
    assert classify_heading("Easy: {{hp|2.5}}").kind is HeadingKind.NOT_A_HEADING


def test_a_bare_value_with_no_label_is_not_a_heading() -> None:
    assert classify_heading("{{hp|20}}").kind is HeadingKind.NOT_A_HEADING


@pytest.mark.parametrize("label", ["Easy:", "Normal:", "Hard:", "Easy and Normal:"])
def test_a_difficulty_label_alone_is_not_a_heading(label: str) -> None:
    """The Hoglin case: a lone difficulty label must never clear a block scope."""
    result = classify_heading(label)
    assert result.kind is HeadingKind.NOT_A_HEADING


def test_a_variant_label_alone_is_an_unmarked_heading_not_a_difficulty_word() -> None:
    result = classify_heading("'''Baby:'''")
    assert result.kind is HeadingKind.UNMARKED
    assert result.label == "Baby"


def test_a_heading_with_a_trailing_parenthetical_aside_is_still_a_heading() -> None:
    """`'''Ranged:''' (ignores [[armor]] and [[Protection]])` -- Warden's damage field."""
    result = classify_heading("'''Ranged:''' (ignores [[armor]] and [[Protection]])")
    assert result.kind is HeadingKind.UNMARKED
    assert result.label == "Ranged"


def test_connecting_words_are_exactly_in_the_on_for() -> None:
    assert frozenset({"in", "the", "on", "for"}) == CONNECTING_WORDS


def test_difficulty_words_are_exactly_easy_normal_hard() -> None:
    assert frozenset({"easy", "normal", "hard"}) == DIFFICULTY_WORDS


# --- scope_editions: the region rule (12 page-fields that must not leak) ----


def test_a_region_persists_across_a_subordinate_variant_heading() -> None:
    """Creeper's damage: `'''Regular:'''` under `'''{{IN|BE}}:'''` does not clear the region."""
    lines = [
        "'''{{IN|BE}}:'''",
        "'''Regular:'''",
        "Easy: {{hp|14.75}}",
    ]
    scopes = scope_editions(lines)
    assert scopes[0].edition is Edition.BEDROCK
    assert scopes[0].reached == REACHED_OWN_MARKER
    assert scopes[1].edition is Edition.BEDROCK
    assert scopes[2].edition is Edition.BEDROCK
    assert scopes[2].reached == REACHED_INHERITED_REGION


def test_a_region_persists_across_two_subordinate_headings() -> None:
    """Cow's size: `'''In {{BE}}:'''` opens a region that both `Adult` and `Baby` inherit."""
    lines = [
        "'''In {{BE}}:'''",
        "'''Adult:'''",
        "Height: 1.3 blocks",
        "'''Baby:'''",
        "Height: 0.65 blocks",
    ]
    scopes = scope_editions(lines)
    assert all(scope.edition is Edition.BEDROCK for scope in scopes)


def test_only_another_standalone_heading_or_hr_clears_a_region() -> None:
    lines = ["'''{{IN|BE}}:'''", "'''Regular:'''", HORIZONTAL_RULE, "'''Melee:'''"]
    scopes = scope_editions(lines)
    assert scopes[1].edition is Edition.BEDROCK
    assert scopes[2].edition is None  # the <hr> line itself
    assert scopes[3].edition is None  # cleared, default keep


def test_another_standalone_heading_replaces_the_region_outright() -> None:
    lines = ["'''{{IN|JE}}:'''", "Easy: {{hp|22.5}}", "'''{{IN|BE}}:'''", "Easy: {{hp|14.75}}"]
    scopes = scope_editions(lines)
    assert scopes[1].edition is Edition.JAVA
    assert scopes[3].edition is Edition.BEDROCK


# --- scope_editions: the block rule (11 page-fields that must keep the reset) -


def test_an_unmarked_heading_clears_a_block_scope() -> None:
    """Zombie's size: the unmarked `'''Baby:'''` heading must clear the Bedrock block."""
    lines = [
        "'''Adult {{IN|Java}}:'''",
        "Height: 1.95 blocks",
        "'''Adult {{IN|Bedrock}}:'''",
        "Height: 1.9 blocks",
        "'''Baby:'''",
        "Height: 0.98 blocks",
    ]
    scopes = scope_editions(lines)
    assert scopes[1].edition is Edition.JAVA
    assert scopes[1].reached == REACHED_INHERITED_BLOCK
    assert scopes[3].edition is Edition.BEDROCK
    assert scopes[5].edition is None
    assert scopes[5].reached == REACHED_DEFAULT


def test_hoglin_damage_a_lone_difficulty_label_does_not_clear_the_block() -> None:
    """The case that would have broken under a naive 'any heading clears the scope' rule."""
    lines = [
        "'''Adult in {{BE}}:'''",
        "Easy:",
        "{{hp|2.5}} to {{hp|5.5}}",
    ]
    scopes = scope_editions(lines)
    assert scopes[0].edition is Edition.BEDROCK
    assert scopes[1].edition is Edition.BEDROCK
    assert scopes[2].edition is Edition.BEDROCK


# --- scope_editions: the inline suffix form ---------------------------------


def test_an_inline_suffix_on_an_ordinary_line_scopes_only_that_line() -> None:
    """Sheep's Bedrock-only dye drops carry no heading at all."""
    lines = ["{{drop|item|Bone Meal}}{{only|be|ee|short=1}}", "{{drop|Item|Lead}}"]
    scopes = scope_editions(lines)
    assert scopes[0].edition is Edition.BEDROCK
    assert scopes[0].reached == REACHED_OWN_MARKER
    assert scopes[1].edition is None


def test_an_inline_java_suffix_and_bedrock_suffix_split_a_knockback_pair() -> None:
    """`70%{{only|java|short=1}}<br>75%{{only|bedrock|short=1}}` from the implementation brief."""
    scopes = scope_editions(["70%{{only|java|short=1}}", "75%{{only|bedrock|short=1}}"])
    assert scopes[0].edition is Edition.JAVA
    assert scopes[1].edition is Edition.BEDROCK


# --- scope_editions: an unmarked field never gets filtered ------------------


def test_a_field_with_no_edition_marker_anywhere_is_never_filtered() -> None:
    """The ordinary case: most fields carry no edition information at all."""
    scopes = scope_editions(["{{hp|20}}"])
    assert scopes[0].edition is None
    assert scopes[0].reached == REACHED_DEFAULT
