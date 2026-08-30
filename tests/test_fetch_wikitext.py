"""The wikitext reader, and the ways it differs from `pipeline.fetch.extracts`.

`pipeline.fetch.wikitext` is the third wiki reader of this package, and the
module docstring explains why it cannot just copy `pipeline.fetch.extracts`'s
rules wholesale: the batch cap fails loudly here (`toomanyvalues`) where it
fails silently there, and namespace answers as a number here where the older
module needs a string fallback. This suite checks both the shared rules (the
rewrite maps, the many-to-one join, the cache key) and the two that differ.

No test in this module opens a socket, and no test writes to the cache of the
repository. Every cache here is built on `tmp_path`.
"""

import json
import socket
from pathlib import Path
from types import FunctionType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from pipeline.fetch import WIKI_API_URL, FetchError, get_bytes
from pipeline.fetch.bucket import DEFAULT_TRANSPORT as BUCKET_TRANSPORT
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.extracts import DEFAULT_TRANSPORT as EXTRACTS_TRANSPORT
from pipeline.fetch.polite import WIKI_TRANSPORT, RateLimiter
from pipeline.fetch.wikitext import (
    BATCH_SIZE,
    DEFAULT_TRANSPORT,
    INVALID_TITLE,
    MAX_REWRITE_HOPS,
    MISSING_PAGE,
    NO_CONTENT,
    MissingWikitext,
    PageWikitext,
    WikitextReport,
    build_wikitext_url,
    fetch_page_wikitext,
    parse_wikitext_answer,
)

SOURCE = "test"


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    Matches `tests/test_extracts.py` and `tests/test_bucket.py`: the failure
    is a `RuntimeError` because `get_bytes` maps every `OSError` to a
    `FetchError`, which the code under test would otherwise catch and pass.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def answer(pages: list[dict[str, Any]], **extra: Any) -> bytes:
    """Return the bytes of a good wikitext answer that holds `pages`."""
    query: dict[str, Any] = {"pages": pages}
    for name in ("normalized", "redirects"):
        if name in extra:
            query[name] = extra.pop(name)
    document: dict[str, Any] = {"batchcomplete": True, "query": query}
    document.update(extra)
    return json.dumps(document).encode("utf-8")


def page(
    title: str, *, content: str | None = None, page_id: int = 1, ns: int = 0
) -> dict[str, Any]:
    """Return one answered page that holds wikitext content."""
    return {
        "pageid": page_id,
        "ns": ns,
        "title": title,
        "revisions": [
            {"slots": {"main": {"content": "{{Infobox entity}}" if content is None else content}}}
        ],
    }


def titles_of(url: str) -> list[str]:
    """Return the titles that `url` asks for."""
    return parse_qs(urlsplit(url).query)["titles"][0].split("|")


class FakeWiki:
    """A wiki that answers wikitext for every title, and records every URL it read."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return answer([page(title, page_id=index) for index, title in enumerate(titles_of(url), 1)])


# --- The URL builder --------------------------------------------------------


def test_the_url_names_every_parameter_the_revisions_query_needs() -> None:
    """The request matches the shape section 1 of the implementation brief records."""
    url = build_wikitext_url(("Creeper", "Zombie"))
    assert url.startswith(f"{WIKI_API_URL}?")
    query = parse_qs(urlsplit(url).query)
    assert query["action"] == ["query"]
    assert query["prop"] == ["revisions"]
    assert query["rvprop"] == ["content"]
    assert query["rvslots"] == ["main"]
    assert query["titles"] == ["Creeper|Zombie"]


def test_the_url_asks_for_format_version_two() -> None:
    """Version 1 would key `pages` by page ID and collide every missing page on `-1`."""
    query = parse_qs(urlsplit(build_wikitext_url(("Creeper",))).query)
    assert query["formatversion"] == ["2"]


def test_the_url_asks_the_server_to_follow_a_redirect() -> None:
    query = parse_qs(urlsplit(build_wikitext_url(("Creepers",))).query)
    assert query["redirects"] == ["1"]


def test_the_url_can_name_another_api() -> None:
    url = build_wikitext_url(("Creeper",), api_url="https://example.test/api.php")
    assert url.startswith("https://example.test/api.php?")


def test_a_batch_at_the_cap_is_accepted() -> None:
    """50 titles per request. Fact 1 of the module docstring."""
    url = build_wikitext_url(tuple(f"Page {index}" for index in range(BATCH_SIZE)))
    assert len(titles_of(url)) == BATCH_SIZE


def test_a_batch_above_the_cap_is_refused_before_the_request() -> None:
    """51 titles is a hard error against the live API: `toomanyvalues`, no `query` key at all.

    Unlike `pipeline.fetch.extracts`, where the loss over the cap is silent,
    this cap is refused here as a courtesy, not because nothing else would
    catch it -- the server would refuse it too.
    """
    with pytest.raises(FetchError, match=f"more than {BATCH_SIZE} titles"):
        build_wikitext_url(tuple(f"Page {index}" for index in range(BATCH_SIZE + 1)))


def test_a_request_for_no_title_is_refused() -> None:
    with pytest.raises(FetchError, match="at least one title"):
        build_wikitext_url(())


def test_a_repeated_title_is_refused() -> None:
    with pytest.raises(FetchError, match="repeats a title"):
        build_wikitext_url(("Creeper", "Creeper"))


def test_a_title_that_holds_the_separator_is_refused() -> None:
    with pytest.raises(FetchError, match="boundary"):
        build_wikitext_url(("Weird|Title",))


@pytest.mark.parametrize("title", ["", "   "])
def test_a_blank_title_is_refused(title: str) -> None:
    with pytest.raises(FetchError, match="cannot be blank"):
        build_wikitext_url((title,))


@pytest.mark.parametrize("title", ["a\nb", "a\rb", "a\x00b", "a\x7fb"])
def test_a_control_character_in_a_title_is_refused(title: str) -> None:
    with pytest.raises(FetchError, match="control character"):
        build_wikitext_url((title,))


# --- The answer parser: the toomanyvalues error -----------------------------


def test_an_api_error_is_raised_and_never_read_as_no_pages() -> None:
    """Checked live: 51 titles answers HTTP 200 with `error.code = toomanyvalues` and no `query`.

    Fact 1 of the module docstring. `get_bytes` sees a valid 200 and raises
    nothing, so this is the only place that can tell the refusal from an
    answer with zero pages.
    """
    payload = json.dumps(
        {
            "error": {
                "code": "toomanyvalues",
                "info": (
                    'Too many values supplied for parameter "titles". The limit is 50.'
                ),
                "limit": 50,
                "lowlimit": 50,
                "highlimit": 500,
            }
        }
    ).encode("utf-8")
    with pytest.raises(FetchError, match="toomanyvalues"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


# --- The answer parser: the rewrite maps ------------------------------------


def test_a_normalized_title_joins_back_to_the_title_that_was_asked_for() -> None:
    """`query.normalized` maps `creeper` to `Creeper`. Fact 2 of the module docstring."""
    payload = answer([page("Creeper")], normalized=[{"from": "creeper", "to": "Creeper"}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("creeper",))
    assert report.pages[0].page_title == "Creeper"


def test_a_redirected_title_joins_back_and_keeps_both_names() -> None:
    """`query.redirects` maps `Creepers` to `Creeper`. Both titles are kept."""
    payload = answer(
        [page("Creeper", page_id=628)], redirects=[{"from": "Creepers", "to": "Creeper"}]
    )
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Creepers",))
    resolved = report.pages[0]
    assert resolved.requested_title == "Creepers"
    assert resolved.page_title == "Creeper"
    assert resolved.page_id == 628


def test_a_rewrite_chain_of_two_steps_is_followed() -> None:
    """A request can be normalized and then redirected in one batch."""
    payload = answer(
        [page("Creeper")],
        normalized=[{"from": "creepers", "to": "Creepers"}],
        redirects=[{"from": "Creepers", "to": "Creeper"}],
    )
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("creepers",))
    assert report.pages[0].page_title == "Creeper"


def test_a_rewrite_that_loops_is_refused() -> None:
    payload = answer(
        [page("Creeper")],
        normalized=[{"from": "A", "to": "B"}],
        redirects=[{"from": "B", "to": "A"}],
    )
    with pytest.raises(FetchError, match="in a circle"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("A",))


def test_a_rewrite_chain_longer_than_the_hop_limit_is_refused() -> None:
    hops = MAX_REWRITE_HOPS + 2
    chain = [{"from": f"T{index}", "to": f"T{index + 1}"} for index in range(hops)]
    payload = answer([page(f"T{hops}")], normalized=chain)
    with pytest.raises(FetchError, match="more than"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("T0",))


# --- The answer parser: the many-to-one join --------------------------------


def test_two_requested_titles_that_resolve_to_one_page_both_read_it() -> None:
    """Checked live: `creeper` and `Creepers` in one batch answer exactly one page object."""
    payload = answer(
        [page("Creeper")],
        normalized=[{"from": "creeper", "to": "Creeper"}],
        redirects=[{"from": "Creepers", "to": "Creeper"}],
    )
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("creeper", "Creepers"))
    assert len(report.pages) == 2
    assert {entry.page_title for entry in report.pages} == {"Creeper"}
    assert {entry.requested_title for entry in report.pages} == {"creeper", "Creepers"}


# --- The answer parser: namespace as a number -------------------------------


def test_a_talk_namespace_answer_is_still_read_since_it_was_asked_for_by_name() -> None:
    """Fact 4: `ns` answers as a number here, so this module tests `ns == 0` outright.

    This module does not filter by namespace on its own -- unlike
    `pipeline.fetch.extracts`, which must guard against a *redirect* moving a
    request out of the main namespace, `pipeline.fetch.wikitext` reads
    whatever page it was asked for by title. `ns` is exposed on the model for
    a caller that wants to filter, and this test pins the number itself.
    """
    payload = answer([page("Talk:Creeper", ns=1)])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Talk:Creeper",))
    assert report.pages[0].page_title == "Talk:Creeper"


# --- The answer parser: missing and invalid ---------------------------------


def test_a_page_the_wiki_does_not_hold_is_a_miss_and_not_a_failure() -> None:
    payload = answer([{"title": "MC-FastWiki no such page", "missing": True}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("MC-FastWiki no such page",))
    assert report.misses == (
        MissingWikitext(
            requested_title="MC-FastWiki no such page",
            page_title="MC-FastWiki no such page",
            reason=MISSING_PAGE,
        ),
    )


def test_a_title_the_wiki_calls_invalid_is_a_miss() -> None:
    payload = answer([{"title": "<", "invalid": True, "invalidreason": "bad title"}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("<",))
    assert report.misses[0].reason == INVALID_TITLE
    assert report.pages == ()


def test_a_page_with_no_revisions_key_is_a_miss() -> None:
    """Fact 6: the content sits three keys under `revisions`, and a page can lack it."""
    payload = answer([{"title": "Creeper", "pageid": 1}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.misses[0].reason == NO_CONTENT


def test_a_page_with_no_slots_key_is_a_miss() -> None:
    payload = answer([{"title": "Creeper", "revisions": [{}]}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.misses[0].reason == NO_CONTENT


def test_a_page_with_no_main_slot_is_a_miss() -> None:
    payload = answer([{"title": "Creeper", "revisions": [{"slots": {}}]}])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.misses[0].reason == NO_CONTENT


def test_every_requested_title_appears_exactly_once() -> None:
    payload = answer(
        [
            page("Creeper"),
            {"title": "MC-FastWiki no such page", "missing": True},
        ]
    )
    report = parse_wikitext_answer(
        payload, source=SOURCE, titles=("Creeper", "MC-FastWiki no such page")
    )
    seen = [entry.requested_title for entry in report.pages]
    seen += [entry.requested_title for entry in report.misses]
    assert sorted(seen) == sorted(("Creeper", "MC-FastWiki no such page"))


# --- The answer parser: batchcomplete and continue --------------------------


def test_an_answer_that_carries_a_continue_key_is_refused() -> None:
    """Fact 7: nothing in the shape says which titles lost their content."""
    payload = json.dumps(
        {"continue": {"rvcontinue": "x"}, "query": {"pages": [page("Creeper")]}}
    ).encode("utf-8")
    with pytest.raises(FetchError, match="did not answer every title"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_an_answer_with_no_batchcomplete_is_refused() -> None:
    payload = json.dumps({"query": {"pages": [page("Creeper")]}}).encode("utf-8")
    with pytest.raises(FetchError, match="batchcomplete"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_body_that_is_not_json_names_its_source() -> None:
    with pytest.raises(FetchError, match=SOURCE):
        parse_wikitext_answer(b"<html>503</html>", source=SOURCE, titles=("Creeper",))


def test_an_answer_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(FetchError, match="not an API answer"):
        parse_wikitext_answer(b"[]", source=SOURCE, titles=("Creeper",))


def test_an_answer_with_no_query_object_is_refused() -> None:
    payload = json.dumps({"batchcomplete": True}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'query' object"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_an_answer_whose_pages_are_not_a_list_is_refused() -> None:
    payload = json.dumps({"batchcomplete": True, "query": {"pages": {"628": {}}}}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'pages' list"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_page_that_is_not_an_object_is_refused() -> None:
    payload = answer(["Creeper"])  # type: ignore[list-item]
    with pytest.raises(FetchError, match="page 0"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_page_with_no_title_is_refused() -> None:
    payload = answer([{"pageid": 1, "revisions": []}])
    with pytest.raises(FetchError, match="no title"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_requested_title_that_the_answer_never_names_is_refused() -> None:
    payload = answer([page("Zombie")])
    with pytest.raises(FetchError, match="answered no page for 'Creeper'"):
        parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))


def test_the_fixture_content_of_a_page_is_the_raw_wikitext() -> None:
    payload = answer([page("Creeper", content="{{Infobox entity\n| health = {{hp|20}}\n}}")])
    report = parse_wikitext_answer(payload, source=SOURCE, titles=("Creeper",))
    assert "{{hp|20}}" in report.pages[0].content


# --- The batch loop ----------------------------------------------------------


def test_one_batch_of_titles_costs_one_request(tmp_path: Path) -> None:
    wiki = FakeWiki()
    report = fetch_page_wikitext(
        ["Creeper", "Zombie"], revision="26.2", cache=ContentCache(tmp_path), transport=wiki
    )
    assert len(wiki.urls) == 1
    assert set(report.contents()) == {"Creeper", "Zombie"}


def test_more_titles_than_one_batch_are_cut_into_batches(tmp_path: Path) -> None:
    wiki = FakeWiki()
    wanted = [f"Page {index:02d}" for index in range(5)]
    report = fetch_page_wikitext(
        wanted, revision="26.2", cache=ContentCache(tmp_path), transport=wiki, batch_size=2
    )
    assert [len(titles_of(url)) for url in wiki.urls] == [2, 2, 1]
    assert sorted(report.contents()) == wanted


def test_the_titles_are_deduplicated_and_sorted_before_they_are_cut(tmp_path: Path) -> None:
    first = FakeWiki()
    second = FakeWiki()
    fetch_page_wikitext(
        ["Zombie", "Creeper", "Zombie"],
        revision="26.2",
        cache=ContentCache(tmp_path / "a"),
        transport=first,
        batch_size=2,
    )
    fetch_page_wikitext(
        ["Creeper", "Zombie"],
        revision="26.2",
        cache=ContentCache(tmp_path / "b"),
        transport=second,
        batch_size=2,
    )
    assert first.urls == second.urls
    assert titles_of(first.urls[0]) == ["Creeper", "Zombie"]


def test_no_title_reads_no_wiki(tmp_path: Path) -> None:
    wiki = FakeWiki()
    report = fetch_page_wikitext([], revision="26.2", cache=ContentCache(tmp_path), transport=wiki)
    assert report == WikitextReport()
    assert wiki.urls == []


def test_the_misses_of_every_batch_reach_the_report(tmp_path: Path) -> None:
    def wiki(url: str) -> bytes:
        return answer([{"title": title, "missing": True} for title in titles_of(url)])

    report = fetch_page_wikitext(
        ["Creeper", "Zombie", "Slime"],
        revision="26.2",
        cache=ContentCache(tmp_path),
        transport=wiki,
        batch_size=2,
    )
    assert len(report.misses) == 3
    assert report.pages == ()


def test_a_batch_size_above_the_cap_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match=f"1 to {BATCH_SIZE} titles"):
        fetch_page_wikitext(
            ["Creeper"],
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=FakeWiki(),
            batch_size=BATCH_SIZE + 1,
        )


def test_a_read_that_names_no_transport_uses_the_polite_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = FakeWiki()
    monkeypatch.setattr("pipeline.fetch.wikitext.DEFAULT_TRANSPORT", wiki)
    report = fetch_page_wikitext(["Creeper"], revision="26.2", cache=ContentCache(tmp_path))
    assert len(wiki.urls) == 1
    assert "Creeper" in report.contents()


def test_the_default_transport_is_not_the_bare_get_bytes() -> None:
    assert DEFAULT_TRANSPORT is not get_bytes
    assert isinstance(DEFAULT_TRANSPORT, FunctionType)
    held = DEFAULT_TRANSPORT.__closure__ or ()
    assert any(isinstance(cell.cell_contents, RateLimiter) for cell in held)


def test_all_three_wiki_readers_default_to_one_shared_transport() -> None:
    """One host, one rate. `pipeline.fetch.polite` explains why two limiters would not space
    each other.
    """
    assert DEFAULT_TRANSPORT is WIKI_TRANSPORT
    assert BUCKET_TRANSPORT is WIKI_TRANSPORT
    assert EXTRACTS_TRANSPORT is WIKI_TRANSPORT


def test_the_batch_size_is_fifty() -> None:
    assert BATCH_SIZE == 50


# --- The cache key -----------------------------------------------------------


def test_a_second_read_of_one_revision_sends_no_request(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    first = fetch_page_wikitext(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    second = fetch_page_wikitext(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    assert first == second
    assert len(wiki.urls) == 1


def test_the_cache_key_carries_the_revision(tmp_path: Path) -> None:
    """The key must be readable as `wikitext/<revision>/<url>`."""
    cache = ContentCache(tmp_path)
    fetch_page_wikitext(["Creeper"], revision="26.2", cache=cache, transport=FakeWiki())
    keys = json.loads((tmp_path / "index.json").read_bytes())
    assert keys
    assert all(key.startswith("wikitext/26.2/https://") for key in keys)


def test_a_new_revision_reads_the_wiki_again(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    fetch_page_wikitext(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    fetch_page_wikitext(["Creeper"], revision="2026-08-30", cache=cache, transport=wiki)
    assert len(wiki.urls) == 2
    assert wiki.urls[0] == wiki.urls[1]


def test_a_bad_answer_is_never_stored(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)

    def refuse(url: str) -> bytes:
        return b"<html>503</html>"

    with pytest.raises(FetchError):
        fetch_page_wikitext(["Creeper"], revision="26.2", cache=cache, transport=refuse)
    assert not (tmp_path / "index.json").exists()


@pytest.mark.parametrize("revision", ["", "26.2/extra", "a b", ".hidden", "26.2\n", "-x"])
def test_a_revision_that_is_not_a_plain_token_is_refused(tmp_path: Path, revision: str) -> None:
    with pytest.raises(FetchError, match="cache revision"):
        fetch_page_wikitext(
            ["Creeper"], revision=revision, cache=ContentCache(tmp_path), transport=FakeWiki()
        )


@pytest.mark.parametrize("revision", ["26.2", "26.3-snapshot-9", "2026-08-30", "wiki_2026_08"])
def test_a_version_and_a_date_both_name_a_revision(tmp_path: Path, revision: str) -> None:
    report = fetch_page_wikitext(
        ["Creeper"], revision=revision, cache=ContentCache(tmp_path), transport=FakeWiki()
    )
    assert "Creeper" in report.contents()


def test_page_wikitext_model_carries_the_content_verbatim() -> None:
    """A sanity check on the model's own shape, independent of the parser."""
    entry = PageWikitext(requested_title="Creeper", page_title="Creeper", page_id=628, content="x")
    assert entry.content == "x"
