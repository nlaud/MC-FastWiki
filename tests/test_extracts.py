"""The intro blurb reader, and the three quiet failures that it must make loud.

`pipeline.fetch.extracts` reads the one Tier B fact that no bucket holds: the
intro blurb of a wiki page. Phase 6 shows that blurb at the top of every entity,
so a fault here is visible on every window of the site.

Three of its rules exist because the live API fails without saying so, and each
one was checked against `https://minecraft.wiki/api.php` on 2026-08-28:

* 25 titles answer 25 pages and only 20 extracts. The five pages that lost their
  extract carry no key to say so. The answer holds `continue` and no
  `batchcomplete`, and that is the whole signal.
* The wiki rewrites a requested title twice, once by capitalizing it and once by
  following a redirect. The answered page carries the final title alone, so a
  reader that matched on the requested title would find nothing.
* A `|` inside a title splits that title into two pages.

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
from pipeline.fetch.extracts import (
    BATCH_SIZE,
    DEFAULT_TRANSPORT,
    INVALID_TITLE,
    MAX_REWRITE_HOPS,
    MISSING_PAGE,
    NO_EXTRACT,
    OFF_MAIN_NAMESPACE,
    ExtractReport,
    MissingExtract,
    PageExtract,
    build_extracts_url,
    fetch_page_extracts,
    parse_extracts_answer,
)
from pipeline.fetch.polite import WIKI_TRANSPORT, RateLimiter

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "wiki_extracts_answer.json"

# The titles that the fixture was captured for, in the order the module sorts
# them. `creeper` is normalized to `Creeper`, `Creepers` redirects to `Creeper`,
# and the third title names no page.
FIXTURE_TITLES = ("Creepers", "MC-FastWiki no such page 12345", "creeper")

# The source name that a test of the parser passes.
SOURCE = "test"


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_bucket.py`, and the reason is the same.
    The failure is a `RuntimeError` because `get_bytes` maps every `OSError` to
    a `FetchError`, so an `OSError` here would be caught by the code under test.
    The test would then pass while it read the live wiki.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def answer(pages: list[dict[str, Any]], **extra: Any) -> bytes:
    """Return the bytes of a good extracts answer that holds `pages`."""
    query: dict[str, Any] = {"pages": pages}
    for name in ("normalized", "redirects"):
        if name in extra:
            query[name] = extra.pop(name)
    document: dict[str, Any] = {"batchcomplete": True, "query": query}
    document.update(extra)
    return json.dumps(document).encode("utf-8")


def page(title: str, *, extract: str | None = None, page_id: int = 1) -> dict[str, Any]:
    """Return one answered page that holds a blurb."""
    return {
        "pageid": page_id,
        "ns": 0,
        "title": title,
        "extract": f"{title} is a block." if extract is None else extract,
    }


def titles_of(url: str) -> list[str]:
    """Return the titles that `url` asks for."""
    return parse_qs(urlsplit(url).query)["titles"][0].split("|")


class FakeWiki:
    """A wiki that answers a blurb for every title, and records every URL it was asked for."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return answer([page(title, page_id=index) for index, title in enumerate(titles_of(url), 1)])


# --- The URL builder -------------------------------------------------------


def test_the_url_names_every_parameter_that_the_extension_needs() -> None:
    """The request is the one that CLAUDE.md records, plus what the traps demand."""
    url = build_extracts_url(("Creeper", "Zombie"))
    assert url.startswith(f"{WIKI_API_URL}?")
    query = parse_qs(urlsplit(url).query)
    assert query["action"] == ["query"]
    assert query["prop"] == ["extracts"]
    assert query["exintro"] == ["1"]
    assert query["explaintext"] == ["1"]
    assert query["titles"] == ["Creeper|Zombie"]


def test_the_url_asks_for_format_version_two() -> None:
    """Version 1 keys `pages` by page ID and gives every missing page the key `-1`.

    Two missing titles in one batch would then collide, and one of them would
    vanish from the answer with nothing to show for it.
    """
    query = parse_qs(urlsplit(build_extracts_url(("Creeper",))).query)
    assert query["formatversion"] == ["2"]


def test_the_url_asks_the_server_to_follow_a_redirect() -> None:
    """Without `redirects`, a redirect page answers as itself and carries no blurb."""
    query = parse_qs(urlsplit(build_extracts_url(("Creepers",))).query)
    assert query["redirects"] == ["1"]


def test_the_url_names_the_exlimit_cap_even_for_a_short_batch() -> None:
    """The cap is what the server answers, so a short batch behaves like a full one."""
    query = parse_qs(urlsplit(build_extracts_url(("Creeper",))).query)
    assert query["exlimit"] == [str(BATCH_SIZE)]


def test_the_url_can_name_another_api() -> None:
    """A test and a mirror both need to point the reader elsewhere."""
    url = build_extracts_url(("Creeper",), api_url="https://example.test/api.php")
    assert url.startswith("https://example.test/api.php?")


def test_a_batch_at_the_cap_is_accepted() -> None:
    """The cap is the batch size, so the loop must be able to ask for it."""
    url = build_extracts_url(tuple(f"Page {index}" for index in range(BATCH_SIZE)))
    assert len(titles_of(url)) == BATCH_SIZE


def test_a_batch_above_the_cap_is_refused() -> None:
    """Checked live: 25 titles answer 25 pages and only 20 extracts.

    The five pages that lost their extract carry no key that says so, so the
    only honest place to refuse is before the request goes out.
    """
    with pytest.raises(FetchError, match=f"more than {BATCH_SIZE} titles"):
        build_extracts_url(tuple(f"Page {index}" for index in range(BATCH_SIZE + 1)))


def test_a_request_for_no_title_is_refused() -> None:
    """An empty `titles` parameter asks the API for nothing."""
    with pytest.raises(FetchError, match="at least one title"):
        build_extracts_url(())


def test_a_repeated_title_is_refused() -> None:
    """A batch of 20 with a repeat asks for 19 pages while the caller counted 20."""
    with pytest.raises(FetchError, match="repeats a title"):
        build_extracts_url(("Creeper", "Creeper"))


def test_a_title_that_holds_the_separator_is_refused() -> None:
    """Checked live: the API read `Weird|Title` as two separate pages."""
    with pytest.raises(FetchError, match="boundary"):
        build_extracts_url(("Weird|Title",))


@pytest.mark.parametrize("title", ["", "   "])
def test_a_blank_title_is_refused(title: str) -> None:
    """A blank title asks for nothing, and the answer would name no page."""
    with pytest.raises(FetchError, match="cannot be blank"):
        build_extracts_url((title,))


@pytest.mark.parametrize("title", ["a\nb", "a\rb", "a\x00b", "a\x7fb"])
def test_a_control_character_in_a_title_is_refused(title: str) -> None:
    """No wiki title holds one, so one is a sign that the caller built it wrongly."""
    with pytest.raises(FetchError, match="control character"):
        build_extracts_url((title,))


# --- The answer parser -----------------------------------------------------


def test_the_fixture_answers_the_blurb_of_a_live_page() -> None:
    """The fixture is a live answer, so the parser is pinned against a real one."""
    report = parse_extracts_answer(FIXTURE.read_bytes(), source=SOURCE, titles=FIXTURE_TITLES)
    blurbs = report.blurbs()
    assert blurbs["creeper"].startswith("A creeper is a common hostile mob")
    assert "\n\n" not in blurbs["creeper"][-2:]


def test_a_normalized_title_joins_back_to_the_title_that_was_asked_for() -> None:
    """`query.normalized` maps `creeper` to `Creeper`. The answer holds only `Creeper`."""
    report = parse_extracts_answer(FIXTURE.read_bytes(), source=SOURCE, titles=FIXTURE_TITLES)
    found = {entry.requested_title: entry.page_title for entry in report.extracts}
    assert found["creeper"] == "Creeper"


def test_a_redirected_title_joins_back_and_keeps_both_names() -> None:
    """`Creepers` redirects to `Creeper`.

    Both titles are kept because a redirect can move a title to a page about
    something else: `Invalid` redirects to `Bug tracker` on this wiki, and only
    the answered title shows that move.
    """
    report = parse_extracts_answer(FIXTURE.read_bytes(), source=SOURCE, titles=FIXTURE_TITLES)
    redirected = next(entry for entry in report.extracts if entry.requested_title == "Creepers")
    assert redirected.page_title == "Creeper"
    assert redirected.page_id == 628


def test_a_page_the_wiki_does_not_hold_is_a_miss_and_not_a_failure() -> None:
    """One bad title must not stop a build of 1,658 entities.

    CLAUDE.md still asks for the report, so the miss names its reason.
    """
    report = parse_extracts_answer(FIXTURE.read_bytes(), source=SOURCE, titles=FIXTURE_TITLES)
    assert report.misses == (
        MissingExtract(
            requested_title="MC-FastWiki no such page 12345",
            page_title="MC-FastWiki no such page 12345",
            reason=MISSING_PAGE,
        ),
    )


def test_every_requested_title_appears_exactly_once() -> None:
    """The answer is read against the request, which is what makes a lost page loud."""
    report = parse_extracts_answer(FIXTURE.read_bytes(), source=SOURCE, titles=FIXTURE_TITLES)
    seen = [entry.requested_title for entry in report.extracts]
    seen += [entry.requested_title for entry in report.misses]
    assert sorted(seen) == sorted(FIXTURE_TITLES)


def test_an_answer_that_carries_a_continue_key_is_refused() -> None:
    """The trap this parser exists for.

    Checked live: 25 titles answer 25 pages, 20 extracts, a `continue` key, and
    no `batchcomplete`. Nothing marks the five pages that lost their extract, so
    a reader that trusted the page list would record five entities with no blurb
    and say nothing.
    """
    payload = json.dumps(
        {"continue": {"excontinue": 21}, "query": {"pages": [page("Creeper")]}}
    ).encode("utf-8")
    with pytest.raises(FetchError, match="did not answer every title"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_an_answer_with_no_batchcomplete_is_refused() -> None:
    """The other half of the same signal. An unfinished batch cannot be read."""
    payload = json.dumps({"query": {"pages": [page("Creeper")]}}).encode("utf-8")
    with pytest.raises(FetchError, match="batchcomplete"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_an_api_error_is_raised_and_never_read_as_no_blurbs() -> None:
    """MediaWiki answers a bad parameter with an `error` object at HTTP 200."""
    payload = json.dumps(
        {"error": {"code": "badvalue", "info": "Unrecognized value for parameter."}}
    ).encode("utf-8")
    with pytest.raises(FetchError, match="badvalue"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_body_that_is_not_json_names_its_source() -> None:
    """An HTML error page from a proxy must fail with the URL that read it."""
    with pytest.raises(FetchError, match=SOURCE):
        parse_extracts_answer(b"<html>503</html>", source=SOURCE, titles=("Creeper",))


def test_an_answer_that_is_not_an_object_is_refused() -> None:
    """A body that is JSON and is not an answer must not read as no blurbs."""
    with pytest.raises(FetchError, match="not an API answer"):
        parse_extracts_answer(b"[]", source=SOURCE, titles=("Creeper",))


def test_an_answer_with_no_query_object_is_refused() -> None:
    """A finished batch that holds no `query` holds no pages either."""
    payload = json.dumps({"batchcomplete": True}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'query' object"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_an_answer_whose_pages_are_not_a_list_is_refused() -> None:
    """Format version 1 answers an object here, so this guard also catches a lost parameter."""
    payload = json.dumps({"batchcomplete": True, "query": {"pages": {"628": {}}}}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'pages' list"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_page_that_is_not_an_object_is_refused() -> None:
    """A caller reads a page as a mapping, so a page that is not one must not reach it."""
    payload = answer(["Creeper"])  # type: ignore[list-item]
    with pytest.raises(FetchError, match="page 0"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_page_with_no_title_is_refused() -> None:
    """The title is the only join between a page and the request that asked for it."""
    payload = answer([{"pageid": 1, "extract": "A creeper is a mob."}])
    with pytest.raises(FetchError, match="no title"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_requested_title_that_the_answer_never_names_is_refused() -> None:
    """This API echoes every title it was given, rewritten or not.

    A title with no page and no rewrite means the body answers some other
    request, so nothing in it can be joined to this one.
    """
    payload = answer([page("Zombie")])
    with pytest.raises(FetchError, match="answered no page for 'Creeper'"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))


def test_a_rewrite_chain_of_two_steps_is_followed() -> None:
    """A request can be normalized and then redirected. `creepers` is both."""
    payload = answer(
        [page("Creeper")],
        normalized=[{"from": "creepers", "to": "Creepers"}],
        redirects=[{"from": "Creepers", "to": "Creeper"}],
    )
    report = parse_extracts_answer(payload, source=SOURCE, titles=("creepers",))
    assert report.extracts[0].page_title == "Creeper"


def test_a_rewrite_that_loops_is_refused() -> None:
    """A circular map names no page, and a walk that followed it would not end."""
    payload = answer(
        [page("Creeper")],
        normalized=[{"from": "A", "to": "B"}],
        redirects=[{"from": "B", "to": "A"}],
    )
    with pytest.raises(FetchError, match="in a circle"):
        parse_extracts_answer(payload, source=SOURCE, titles=("A",))


def test_a_rewrite_chain_of_exactly_the_hop_limit_is_followed() -> None:
    """`MAX_REWRITE_HOPS` counts hops, so a chain of that many must resolve.

    A hop and a look are not the same step: following four hops takes four reads
    of the map to move the title and a fifth to see that it has stopped moving.
    A walk bounded by `range(MAX_REWRITE_HOPS)` runs out on the look, so it
    follows three hops while the constant says four, and it refuses this answer
    with a message claiming the title was rewritten more than four times when it
    was rewritten exactly four. The chain resolves, so the refusal would lose a
    blurb the wiki answered and stop the whole batch to do it.
    """
    hops = MAX_REWRITE_HOPS
    chain = [{"from": f"T{index}", "to": f"T{index + 1}"} for index in range(hops)]
    payload = answer([page(f"T{hops}")], normalized=chain)
    report = parse_extracts_answer(payload, source=SOURCE, titles=("T0",))
    assert report.extracts[0].page_title == f"T{hops}"


def test_a_rewrite_chain_longer_than_the_hop_limit_is_refused() -> None:
    """The wiki rewrites twice at most, so a longer chain is not an answer to trust."""
    hops = MAX_REWRITE_HOPS + 2
    chain = [{"from": f"T{index}", "to": f"T{index + 1}"} for index in range(hops)]
    payload = answer([page(f"T{hops}")], normalized=chain)
    with pytest.raises(FetchError, match="more than"):
        parse_extracts_answer(payload, source=SOURCE, titles=("T0",))


def test_a_rewrite_entry_with_no_from_and_to_pair_is_refused() -> None:
    """A malformed rewrite would break a join in silence, so it breaks the read instead."""
    payload = answer([page("Creeper")], redirects=[{"from": "Creepers"}])
    with pytest.raises(FetchError, match="'from' and 'to'"):
        parse_extracts_answer(payload, source=SOURCE, titles=("Creepers",))


def test_a_title_the_wiki_calls_invalid_is_a_miss() -> None:
    """A title that cannot exist answers `invalid`, not `missing`."""
    payload = answer([{"title": "<", "invalid": True, "invalidreason": "bad title"}])
    report = parse_extracts_answer(payload, source=SOURCE, titles=("<",))
    assert report.misses[0].reason == INVALID_TITLE
    assert report.extracts == ()


def test_a_page_that_holds_no_extract_is_a_miss() -> None:
    """CLAUDE.md: an empty scrape result is a failure to report, not an empty value."""
    payload = answer([{"pageid": 1, "title": "Creeper"}])
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.misses[0].reason == NO_EXTRACT


def test_an_extract_of_whitespace_alone_is_a_miss() -> None:
    """A live blurb ends with two newlines, so a blank one is whitespace, not an empty string."""
    payload = answer([page("Creeper", extract="\n\n")])
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.misses[0].reason == NO_EXTRACT


def test_a_redirect_out_of_the_main_namespace_is_a_miss() -> None:
    """A blurb the wiki answered from a sandbox must not ship as the entity's own.

    `redirects=1` lets the wiki decide which page answers a request. One edit
    turns `Bricks` into a redirect to `User:Someone/Bricks draft`, and the
    answer then carries that sandbox's lead paragraph under the requested title
    with nothing in the page to say the namespace changed. CLAUDE.md draws this
    line for the Bucket tables and gives the reason -- a row from a user or
    translation page is well-formed, so nothing downstream can tell -- and it
    asks for the filter at the pipeline stage rather than at render time.
    """
    payload = answer(
        [
            {
                "pageid": 9,
                "ns": 2,
                "title": "User:Someone/Bricks draft",
                "extract": "My draft of the bricks page.",
            }
        ],
        redirects=[{"from": "Bricks", "to": "User:Someone/Bricks draft"}],
    )
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Bricks",))
    assert report.extracts == ()
    assert report.misses == (
        MissingExtract(
            requested_title="Bricks",
            page_title="User:Someone/Bricks draft",
            reason=OFF_MAIN_NAMESPACE,
        ),
    )


def test_a_redirect_out_of_the_main_namespace_is_caught_with_no_ns_field() -> None:
    """`ns` decides it when the answer carries one, and the colon test when it does not.

    CLAUDE.md writes that fallback down: a main-namespace title holds no colon,
    so that is the test. Without it an answer that omitted `ns` would take the
    same sandbox blurb.
    """
    payload = answer(
        [{"pageid": 9, "title": "Minecraft Wiki:Projects", "extract": "A wiki project page."}],
        redirects=[{"from": "Bricks", "to": "Minecraft Wiki:Projects"}],
    )
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Bricks",))
    assert report.misses[0].reason == OFF_MAIN_NAMESPACE


def test_a_redirect_inside_the_main_namespace_still_answers_its_blurb() -> None:
    """The ordinary redirect must not be caught by the namespace test.

    `Creepers` redirects to `Creeper`, which is what `redirects=1` is for. Both
    are namespace 0, so nothing was moved out of the articles.
    """
    payload = answer(
        [{"pageid": 628, "ns": 0, "title": "Creeper", "extract": "A creeper is a mob."}],
        redirects=[{"from": "Creepers", "to": "Creeper"}],
    )
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Creepers",))
    assert report.misses == ()
    assert report.extracts[0].extract == "A creeper is a mob."


def test_a_title_that_names_a_namespace_itself_is_answered() -> None:
    """A caller that asks for a namespaced page by name got what it asked for.

    Nothing was moved, so there is nothing to refuse. The guard is about a
    redirect carrying a request out of the main namespace, not about which
    titles a caller may name.
    """
    payload = answer(
        [
            {
                "pageid": 9,
                "ns": 4,
                "title": "Minecraft Wiki:Projects",
                "extract": "A wiki project page.",
            }
        ]
    )
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Minecraft Wiki:Projects",))
    assert report.misses == ()
    assert report.extracts[0].extract == "A wiki project page."


def test_a_page_with_no_page_id_still_answers_its_blurb() -> None:
    """The blurb is the payload. The page ID is a detail this project does not key on."""
    payload = answer([{"title": "Creeper", "extract": "A creeper is a mob."}])
    report = parse_extracts_answer(payload, source=SOURCE, titles=("Creeper",))
    assert report.extracts[0] == PageExtract(
        requested_title="Creeper",
        page_title="Creeper",
        page_id=None,
        extract="A creeper is a mob.",
    )


# --- The batch loop --------------------------------------------------------


def test_one_batch_of_titles_costs_one_request(tmp_path: Path) -> None:
    """A batch is one request, because the batch size is the `exlimit` cap."""
    wiki = FakeWiki()
    report = fetch_page_extracts(
        ["Creeper", "Zombie"], revision="26.2", cache=ContentCache(tmp_path), transport=wiki
    )
    assert len(wiki.urls) == 1
    assert report.blurbs() == {"Creeper": "Creeper is a block.", "Zombie": "Zombie is a block."}


def test_more_titles_than_one_batch_are_cut_into_batches(tmp_path: Path) -> None:
    """Every title must reach a request, and no request may exceed the cap."""
    wiki = FakeWiki()
    wanted = [f"Page {index:02d}" for index in range(5)]
    report = fetch_page_extracts(
        wanted, revision="26.2", cache=ContentCache(tmp_path), transport=wiki, batch_size=2
    )
    assert [len(titles_of(url)) for url in wiki.urls] == [2, 2, 1]
    assert sorted(report.blurbs()) == wanted


def test_the_titles_are_deduplicated_and_sorted_before_they_are_cut(tmp_path: Path) -> None:
    """One set of titles must produce one set of URLs, whatever order the caller used.

    Without this a rebuild that listed the same entities in another order would
    miss every cache entry and read the whole wiki again.
    """
    first = FakeWiki()
    second = FakeWiki()
    fetch_page_extracts(
        ["Zombie", "Creeper", "Zombie"],
        revision="26.2",
        cache=ContentCache(tmp_path / "a"),
        transport=first,
        batch_size=2,
    )
    fetch_page_extracts(
        ["Creeper", "Zombie"],
        revision="26.2",
        cache=ContentCache(tmp_path / "b"),
        transport=second,
        batch_size=2,
    )
    assert first.urls == second.urls
    assert titles_of(first.urls[0]) == ["Creeper", "Zombie"]


def test_no_title_reads_no_wiki(tmp_path: Path) -> None:
    """An empty request is an empty report, not a request for every page."""
    wiki = FakeWiki()
    report = fetch_page_extracts([], revision="26.2", cache=ContentCache(tmp_path), transport=wiki)
    assert report == ExtractReport()
    assert wiki.urls == []


def test_the_misses_of_every_batch_reach_the_report(tmp_path: Path) -> None:
    """A miss in the last batch must not be dropped when the reports are merged."""

    def wiki(url: str) -> bytes:
        return answer([{"title": title, "missing": True} for title in titles_of(url)])

    report = fetch_page_extracts(
        ["Creeper", "Zombie", "Slime"],
        revision="26.2",
        cache=ContentCache(tmp_path),
        transport=wiki,
        batch_size=2,
    )
    assert len(report.misses) == 3
    assert report.extracts == ()


def test_a_batch_size_above_the_cap_is_refused(tmp_path: Path) -> None:
    """The caller cannot raise the batch past what the extension will answer."""
    with pytest.raises(FetchError, match=f"1 to {BATCH_SIZE} titles"):
        fetch_page_extracts(
            ["Creeper"],
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=FakeWiki(),
            batch_size=BATCH_SIZE + 1,
        )


def test_a_read_that_names_no_transport_uses_the_polite_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE.md asks that every network fetch be rate-limited, so the default must be.

    One blurb read of the whole registry is 83 requests. A default of the bare
    `get_bytes` would send them as fast as the socket allows, and nothing would
    fail or warn about it.
    """
    wiki = FakeWiki()
    monkeypatch.setattr("pipeline.fetch.extracts.DEFAULT_TRANSPORT", wiki)
    report = fetch_page_extracts(["Creeper"], revision="26.2", cache=ContentCache(tmp_path))
    assert len(wiki.urls) == 1
    assert report.blurbs() == {"Creeper": "Creeper is a block."}


def test_the_default_transport_is_not_the_bare_get_bytes() -> None:
    """The default is the wrapped transport, and it is one object, not one per call."""
    assert DEFAULT_TRANSPORT is not get_bytes
    assert isinstance(DEFAULT_TRANSPORT, FunctionType)
    held = DEFAULT_TRANSPORT.__closure__ or ()
    assert any(isinstance(cell.cell_contents, RateLimiter) for cell in held)


def test_both_wiki_readers_default_to_one_shared_transport() -> None:
    """One host, one rate. Two module-level defaults would be two limiters.

    `pipeline.fetch.bucket` and this module read two actions of one endpoint,
    `WIKI_API_URL`, and a rate limit belongs to the host and not to the action.
    `pipeline.fetch.polite` says why two objects cannot do this job: two
    transports hold two limiters and do not space each other. A
    `polite_transport()` built in each reader therefore lets a build that takes
    both defaults send twice the intended rate at a volunteer-run service, while
    each reader reads its own limiter and believes it is keeping to one.

    It would also undo the reason those defaults exist at all. Each is built at
    import so that politeness is not something a caller has to remember, and
    with two of them politeness *across* the readers goes straight back to being
    remembered at every call site.
    """
    assert DEFAULT_TRANSPORT is WIKI_TRANSPORT
    assert BUCKET_TRANSPORT is WIKI_TRANSPORT


def test_the_batch_size_is_the_exlimit_cap() -> None:
    """The cap is named once, not copied into the signature."""
    assert BATCH_SIZE == 20


# --- The cache key ---------------------------------------------------------


def test_a_second_read_of_one_revision_sends_no_request(tmp_path: Path) -> None:
    """The whole point of the cache: a rebuild of one version reads no network."""
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    first = fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    second = fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    assert first == second
    assert len(wiki.urls) == 1


def test_the_cache_key_carries_the_revision(tmp_path: Path) -> None:
    """The key must be readable as `extracts/<revision>/<url>`.

    A key of the URL alone would be the bug this rule exists to stop, and it
    would look exactly like this test passing.
    """
    cache = ContentCache(tmp_path)
    fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=FakeWiki())
    keys = json.loads((tmp_path / "index.json").read_bytes())
    assert keys
    assert all(key.startswith("extracts/26.2/https://") for key in keys)


def test_a_new_revision_reads_the_wiki_again(tmp_path: Path) -> None:
    """The wiki is edited every day, so a rewritten blurb must be able to land."""
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    fetch_page_extracts(["Creeper"], revision="2026-08-28", cache=cache, transport=wiki)
    assert len(wiki.urls) == 2
    assert wiki.urls[0] == wiki.urls[1]


def test_a_bad_answer_is_never_stored(tmp_path: Path) -> None:
    """A body that failed the parser must not be read back on the next build."""
    cache = ContentCache(tmp_path)

    def refuse(url: str) -> bytes:
        return b"<html>503</html>"

    with pytest.raises(FetchError):
        fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=refuse)
    assert not (tmp_path / "index.json").exists()


def test_a_stored_body_that_is_not_an_answer_is_fetched_again(tmp_path: Path) -> None:
    """A proxy page that reached the store must cost one request, not every build."""
    cache = ContentCache(tmp_path)
    url = build_extracts_url(("Creeper",))
    cache.write(f"extracts/26.2/{url}", b"<html>503</html>")
    wiki = FakeWiki()
    report = fetch_page_extracts(["Creeper"], revision="26.2", cache=cache, transport=wiki)
    assert report.blurbs() == {"Creeper": "Creeper is a block."}
    assert len(wiki.urls) == 1


@pytest.mark.parametrize("revision", ["", "26.2/extra", "a b", ".hidden", "26.2\n", "-x"])
def test_a_revision_that_is_not_a_plain_token_is_refused(tmp_path: Path, revision: str) -> None:
    """A revision names a cache generation, so a separator in one would collide two."""
    with pytest.raises(FetchError, match="cache revision"):
        fetch_page_extracts(
            ["Creeper"], revision=revision, cache=ContentCache(tmp_path), transport=FakeWiki()
        )


@pytest.mark.parametrize("revision", ["26.2", "26.3-snapshot-9", "2026-08-28", "wiki_2026_08"])
def test_a_version_and_a_date_both_name_a_revision(tmp_path: Path, revision: str) -> None:
    """A build passes the Minecraft version. A wiki-only refresh passes a date."""
    report = fetch_page_extracts(
        ["Creeper"], revision=revision, cache=ContentCache(tmp_path), transport=FakeWiki()
    )
    assert report.blurbs() == {"Creeper": "Creeper is a block."}
