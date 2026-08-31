"""The imageinfo reader, and the traps a `File:` title read shares with an article read.

`pipeline.fetch.imageinfo` reads the one fact `pipeline.enrich.sprite` cannot
carry: where a `File:` page's current upload actually lives, and the hash that
proves a later download is the same bytes. Two of its rules mirror
`pipeline.fetch.extracts` exactly, because both props sit under `action=query`
and share the same title-rewrite machinery; one is new to this reader.

* The batch cap is 50, not the 20 of `prop=extracts` -- checked live against
  `https://minecraft.wiki/api.php` on 2026-08-30.
* The wiki rewrites a requested title in the same two ways `prop=extracts`
  does, and the answered page carries only the final title.
* A file the wiki answers from outside namespace 6 is a miss, the file-page
  analogue of `prop=extracts`'s off-main-namespace redirect guard.

No test in this module opens a socket, and no test writes to the cache of the
repository. Every cache here is built on `tmp_path`.
"""

import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from pipeline.fetch import WIKI_API_URL, FetchError, get_bytes
from pipeline.fetch.cache import ContentCache
from pipeline.fetch.imageinfo import (
    BATCH_SIZE,
    DEFAULT_TRANSPORT,
    IIPROP,
    INVALID_TITLE,
    MISSING_FILE,
    NO_IMAGE_INFO,
    OFF_FILE_NAMESPACE,
    FileImage,
    ImageInfoReport,
    MissingImage,
    build_imageinfo_url,
    fetch_file_images,
    parse_imageinfo_answer,
)
from pipeline.fetch.polite import WIKI_TRANSPORT

SOURCE = "test"


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket, matching `tests/test_extracts.py`."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def answer(pages: list[dict[str, Any]], **extra: Any) -> bytes:
    """Return the bytes of a good imageinfo answer that holds `pages`."""
    query: dict[str, Any] = {"pages": pages}
    for name in ("normalized", "redirects"):
        if name in extra:
            query[name] = extra.pop(name)
    document: dict[str, Any] = {"batchcomplete": True, "query": query}
    document.update(extra)
    return json.dumps(document).encode("utf-8")


def page(
    title: str,
    *,
    sha1: str = "d4422a162a07edffea60d134d639c5bca3ab4d20",
    url: str | None = None,
    size: int = 222,
    width: int = 16,
    height: int = 16,
    mime: str = "image/png",
    page_id: int = 1,
    ns: int = 6,
) -> dict[str, Any]:
    """Return one answered page that holds an imageinfo entry."""
    return {
        "pageid": page_id,
        "ns": ns,
        "title": title,
        "imagerepository": "local",
        "imageinfo": [
            {
                "size": size,
                "width": width,
                "height": height,
                "url": url if url is not None else f"https://minecraft.wiki/images/{title}?d47d8",
                "descriptionurl": f"https://minecraft.wiki/w/{title}",
                "sha1": sha1,
                "mime": mime,
            }
        ],
    }


def titles_of(url: str) -> list[str]:
    """Return the titles that `url` asks for."""
    return parse_qs(urlsplit(url).query)["titles"][0].split("|")


class FakeWiki:
    """A wiki that answers an image for every title, and records every URL it was asked for."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return answer(
            [page(title, page_id=index) for index, title in enumerate(titles_of(url), 1)]
        )


# --- The URL builder ---------------------------------------------------------


def test_the_url_names_every_parameter_the_prop_needs() -> None:
    url = build_imageinfo_url(("File:A.png", "File:B.png"))
    assert url.startswith(f"{WIKI_API_URL}?")
    query = parse_qs(urlsplit(url).query)
    assert query["action"] == ["query"]
    assert query["prop"] == ["imageinfo"]
    assert query["iiprop"] == [IIPROP]
    assert query["titles"] == ["File:A.png|File:B.png"]


def test_the_url_asks_for_format_version_two() -> None:
    query = parse_qs(urlsplit(build_imageinfo_url(("File:A.png",))).query)
    assert query["formatversion"] == ["2"]


def test_the_url_asks_the_server_to_follow_a_redirect() -> None:
    query = parse_qs(urlsplit(build_imageinfo_url(("File:A.png",))).query)
    assert query["redirects"] == ["1"]


def test_the_batch_cap_is_fifty_not_the_extracts_cap_of_twenty() -> None:
    """Checked live: this prop's cap is the general `titles` ceiling, not an `iiprop` analogue."""
    assert BATCH_SIZE == 50


def test_a_batch_at_the_cap_is_accepted() -> None:
    url = build_imageinfo_url(tuple(f"File:{index}.png" for index in range(BATCH_SIZE)))
    assert len(titles_of(url)) == BATCH_SIZE


def test_a_batch_above_the_cap_is_refused() -> None:
    with pytest.raises(FetchError, match=f"more than {BATCH_SIZE} titles"):
        build_imageinfo_url(tuple(f"File:{index}.png" for index in range(BATCH_SIZE + 1)))


def test_a_request_for_no_title_is_refused() -> None:
    with pytest.raises(FetchError, match="at least one title"):
        build_imageinfo_url(())


def test_a_repeated_title_is_refused() -> None:
    with pytest.raises(FetchError, match="repeats a title"):
        build_imageinfo_url(("File:A.png", "File:A.png"))


def test_a_title_that_holds_the_separator_is_refused() -> None:
    with pytest.raises(FetchError, match="boundary"):
        build_imageinfo_url(("File:Weird|Title.png",))


@pytest.mark.parametrize("title", ["", "   "])
def test_a_blank_title_is_refused(title: str) -> None:
    with pytest.raises(FetchError, match="cannot be blank"):
        build_imageinfo_url((title,))


def test_a_control_character_in_a_title_is_refused() -> None:
    with pytest.raises(FetchError, match="control character"):
        build_imageinfo_url(("File:A\nB.png",))


def test_a_title_needs_no_file_prefix_to_pass_the_url_builder() -> None:
    """The `File:` prefix is a fact the answer must carry, not a shape the request enforces."""
    url = build_imageinfo_url(("Not A File Title",))
    assert titles_of(url) == ["Not A File Title"]


# --- The answer parser --------------------------------------------------------


def test_a_good_answer_becomes_a_file_image() -> None:
    payload = answer([page("File:Invicon Raw Iron.png")])
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:Invicon Raw Iron.png",))

    assert report.images == (
        FileImage(
            title="File:Invicon Raw Iron.png",
            url="https://minecraft.wiki/images/File:Invicon Raw Iron.png?d47d8",
            sha1="d4422a162a07edffea60d134d639c5bca3ab4d20",
            size=222,
            width=16,
            height=16,
            mime="image/png",
        ),
    )
    assert report.missing == ()


def test_every_requested_title_appears_exactly_once() -> None:
    payload = answer([page("File:A.png"), page("File:B.png", page_id=2)])
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png", "File:B.png"))

    seen = [entry.title for entry in report.images] + [entry.title for entry in report.missing]
    assert sorted(seen) == ["File:A.png", "File:B.png"]


def test_a_missing_file_is_a_miss_and_not_a_failure() -> None:
    payload = answer([{"ns": 6, "title": "File:Nope.png", "missing": True, "imagerepository": ""}])
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:Nope.png",))

    assert report.missing == (MissingImage(title="File:Nope.png", reason=MISSING_FILE),)
    assert report.images == ()


def test_a_title_the_wiki_calls_invalid_is_a_miss() -> None:
    payload = answer([{"title": "File:<.png", "invalid": True}])
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:<.png",))

    assert report.missing[0].reason == INVALID_TITLE


def test_a_file_page_with_no_imageinfo_entry_is_a_miss() -> None:
    """A page that exists but answers no `imageinfo` list at all."""
    payload = answer([{"pageid": 1, "ns": 6, "title": "File:A.png", "imagerepository": "local"}])
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))

    assert report.missing[0].reason == NO_IMAGE_INFO


def test_a_file_page_with_an_empty_imageinfo_list_is_a_miss() -> None:
    payload = answer(
        [{"pageid": 1, "ns": 6, "title": "File:A.png", "imagerepository": "local", "imageinfo": []}]
    )
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))

    assert report.missing[0].reason == NO_IMAGE_INFO


def test_a_redirect_out_of_the_file_namespace_is_a_miss() -> None:
    """A `File:` title redirected somewhere else names a page this reader must not trust."""
    payload = answer(
        [page("Some Article", ns=0)],
        redirects=[{"from": "File:Weird.png", "to": "Some Article"}],
    )
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("File:Weird.png",))

    assert report.missing == (MissingImage(title="File:Weird.png", reason=OFF_FILE_NAMESPACE),)


def test_a_page_with_no_ns_at_all_is_off_namespace() -> None:
    """Unlike `prop=extracts`, this module has no bare-title fallback to fall back to."""
    manual = json.dumps(
        {
            "batchcomplete": True,
            "query": {
                "pages": [
                    {
                        "pageid": 1,
                        "title": "File:A.png",
                        "imageinfo": [
                            {
                                "size": 1,
                                "width": 1,
                                "height": 1,
                                "url": "https://minecraft.wiki/images/A.png",
                                "sha1": "d4422a162a07edffea60d134d639c5bca3ab4d20",
                                "mime": "image/png",
                            }
                        ],
                    }
                ]
            },
        }
    ).encode("utf-8")
    report = parse_imageinfo_answer(manual, source=SOURCE, titles=("File:A.png",))
    assert report.missing == (MissingImage(title="File:A.png", reason=OFF_FILE_NAMESPACE),)


def test_a_rewritten_title_joins_back_to_the_title_that_was_asked_for() -> None:
    payload = answer(
        [page("File:Creeper.png")],
        normalized=[{"from": "file:creeper.png", "to": "File:Creeper.png"}],
    )
    report = parse_imageinfo_answer(payload, source=SOURCE, titles=("file:creeper.png",))
    assert report.images[0].title == "file:creeper.png"


def test_an_answer_that_carries_a_continue_key_is_refused() -> None:
    payload = json.dumps(
        {"continue": {"iistart": "x"}, "query": {"pages": [page("File:A.png")]}}
    ).encode("utf-8")
    with pytest.raises(FetchError, match="did not answer every title"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_an_answer_with_no_batchcomplete_is_refused() -> None:
    payload = json.dumps({"query": {"pages": [page("File:A.png")]}}).encode("utf-8")
    with pytest.raises(FetchError, match="batchcomplete"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_an_api_error_is_raised_and_never_read_as_no_images() -> None:
    payload = json.dumps(
        {"error": {"code": "badvalue", "info": "Unrecognized value for parameter."}}
    ).encode("utf-8")
    with pytest.raises(FetchError, match="badvalue"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_a_body_that_is_not_json_names_its_source() -> None:
    with pytest.raises(FetchError, match=SOURCE):
        parse_imageinfo_answer(b"<html>503</html>", source=SOURCE, titles=("File:A.png",))


def test_an_answer_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(FetchError, match="not an API answer"):
        parse_imageinfo_answer(b"[]", source=SOURCE, titles=("File:A.png",))


def test_an_answer_with_no_query_object_is_refused() -> None:
    payload = json.dumps({"batchcomplete": True}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'query' object"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_an_answer_whose_pages_are_not_a_list_is_refused() -> None:
    payload = json.dumps({"batchcomplete": True, "query": {"pages": {}}}).encode("utf-8")
    with pytest.raises(FetchError, match="no 'pages' list"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_a_page_that_is_not_an_object_is_refused() -> None:
    payload = answer(["File:A.png"])  # type: ignore[list-item]
    with pytest.raises(FetchError, match="page 0"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_a_page_with_no_title_is_refused() -> None:
    payload = answer([{"pageid": 1, "ns": 6, "imageinfo": []}])
    with pytest.raises(FetchError, match="no title"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_a_requested_title_that_the_answer_never_names_is_refused() -> None:
    payload = answer([page("File:B.png")])
    with pytest.raises(FetchError, match=re.escape("answered no page for 'File:A.png'")):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


def test_an_imageinfo_entry_with_no_url_is_a_shape_fault() -> None:
    """A page this module was told holds imageinfo, missing a key it always carries, is a fault."""
    payload = answer(
        [
            {
                "pageid": 1,
                "ns": 6,
                "title": "File:A.png",
                "imageinfo": [{"size": 1, "width": 1, "height": 1, "sha1": "a" * 40, "mime": "x"}],
            }
        ]
    )
    with pytest.raises(FetchError, match="no 'url'"):
        parse_imageinfo_answer(payload, source=SOURCE, titles=("File:A.png",))


# --- `FileImage` validation ----------------------------------------------------


def test_a_sha1_that_is_not_forty_hex_characters_is_refused() -> None:
    with pytest.raises(FetchError, match="sha1"):
        FileImage(
            title="File:A.png",
            url="https://minecraft.wiki/images/A.png",
            sha1="not-a-hash",
            size=1,
            width=1,
            height=1,
            mime="image/png",
        )


@pytest.mark.parametrize("field", ["size", "width", "height"])
def test_a_non_positive_dimension_is_refused(field: str) -> None:
    values: dict[str, Any] = {
        "title": "File:A.png",
        "url": "https://minecraft.wiki/images/A.png",
        "sha1": "d4422a162a07edffea60d134d639c5bca3ab4d20",
        "size": 1,
        "width": 1,
        "height": 1,
        "mime": "image/png",
    }
    values[field] = 0
    with pytest.raises(FetchError, match="positive"):
        FileImage(**values)


# --- The batch loop and cache --------------------------------------------------


def test_one_batch_of_titles_costs_one_request(tmp_path: Path) -> None:
    wiki = FakeWiki()
    report = fetch_file_images(
        ["File:A.png", "File:B.png"], revision="26.2", cache=ContentCache(tmp_path), transport=wiki
    )
    assert len(wiki.urls) == 1
    assert set(report.by_title) == {"File:A.png", "File:B.png"}


def test_more_titles_than_one_batch_are_cut_into_batches(tmp_path: Path) -> None:
    wiki = FakeWiki()
    wanted = [f"File:{index:02d}.png" for index in range(5)]
    report = fetch_file_images(
        wanted, revision="26.2", cache=ContentCache(tmp_path), transport=wiki, batch_size=2
    )
    assert [len(titles_of(url)) for url in wiki.urls] == [2, 2, 1]
    assert sorted(report.by_title) == wanted


def test_the_titles_are_deduplicated_and_sorted_before_they_are_cut(tmp_path: Path) -> None:
    first = FakeWiki()
    second = FakeWiki()
    fetch_file_images(
        ["File:B.png", "File:A.png", "File:B.png"],
        revision="26.2",
        cache=ContentCache(tmp_path / "a"),
        transport=first,
        batch_size=2,
    )
    fetch_file_images(
        ["File:A.png", "File:B.png"],
        revision="26.2",
        cache=ContentCache(tmp_path / "b"),
        transport=second,
        batch_size=2,
    )
    assert first.urls == second.urls


def test_no_title_reads_no_wiki(tmp_path: Path) -> None:
    wiki = FakeWiki()
    report = fetch_file_images([], revision="26.2", cache=ContentCache(tmp_path), transport=wiki)
    assert report == ImageInfoReport()
    assert wiki.urls == []


def test_a_batch_size_above_the_cap_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match=f"1 to {BATCH_SIZE} titles"):
        fetch_file_images(
            ["File:A.png"],
            revision="26.2",
            cache=ContentCache(tmp_path),
            transport=FakeWiki(),
            batch_size=BATCH_SIZE + 1,
        )


def test_a_read_that_names_no_transport_uses_the_polite_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = FakeWiki()
    monkeypatch.setattr("pipeline.fetch.imageinfo.DEFAULT_TRANSPORT", wiki)
    report = fetch_file_images(["File:A.png"], revision="26.2", cache=ContentCache(tmp_path))
    assert len(wiki.urls) == 1
    assert "File:A.png" in report.by_title


def test_the_default_transport_is_the_shared_wiki_transport() -> None:
    """One host, one rate. See `pipeline.fetch.polite` for why a fourth limiter would be wrong."""
    assert DEFAULT_TRANSPORT is WIKI_TRANSPORT
    assert DEFAULT_TRANSPORT is not get_bytes


def test_a_second_read_of_one_revision_sends_no_request(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    first = fetch_file_images(["File:A.png"], revision="26.2", cache=cache, transport=wiki)
    second = fetch_file_images(["File:A.png"], revision="26.2", cache=cache, transport=wiki)
    assert first == second
    assert len(wiki.urls) == 1


def test_the_cache_key_carries_the_revision(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    fetch_file_images(["File:A.png"], revision="26.2", cache=cache, transport=FakeWiki())
    keys = json.loads((tmp_path / "index.json").read_bytes())
    assert keys
    assert all(key.startswith("imageinfo/26.2/https://") for key in keys)


def test_a_new_revision_reads_the_wiki_again(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    wiki = FakeWiki()
    fetch_file_images(["File:A.png"], revision="26.2", cache=cache, transport=wiki)
    fetch_file_images(["File:A.png"], revision="2026-08-30", cache=cache, transport=wiki)
    assert len(wiki.urls) == 2


def test_a_bad_answer_is_never_stored(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)

    def refuse(url: str) -> bytes:
        return b"<html>503</html>"

    with pytest.raises(FetchError):
        fetch_file_images(["File:A.png"], revision="26.2", cache=cache, transport=refuse)
    assert not (tmp_path / "index.json").exists()


@pytest.mark.parametrize("revision", ["", "26.2/extra", "a b", ".hidden"])
def test_a_revision_that_is_not_a_plain_token_is_refused(tmp_path: Path, revision: str) -> None:
    with pytest.raises(FetchError, match="cache revision"):
        fetch_file_images(
            ["File:A.png"], revision=revision, cache=ContentCache(tmp_path), transport=FakeWiki()
        )
