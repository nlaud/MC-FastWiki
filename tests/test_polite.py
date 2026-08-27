"""The rate limiter and the retry policy that every wiki read goes through.

CLAUDE.md asks this pipeline to be a good citizen with the wiki API, which is a
volunteer-run service. `pipeline.fetch.polite` is where that rule is written
down, and this module pins each part of it: the spacing between two requests,
which faults earn a retry, which faults do not, and how long a retry waits.

The rule that carries the weight is the one about which faults are retryable. A
retry of a 404 or a misspelled field name sends the service three more requests
to be told the same thing three more times, and the fault it would cover -- a
timeout or a refused connection -- is exactly the one that carries no status.

No test in this module opens a socket, and no test in this module sleeps. Every
clock and every sleep is a callable that the test passes in, so a test of a
sixty-second backoff runs instantly and reads the exact number.
"""

import socket
import time

import pytest
from pydantic import ValidationError

from pipeline.fetch import FetchError
from pipeline.fetch.polite import (
    DEFAULT_MIN_INTERVAL_SECONDS,
    MAX_WAIT_SECONDS,
    RateLimiter,
    RetryPolicy,
    polite_transport,
    retry_after_seconds,
)

URL = "https://minecraft.wiki/api.php?action=bucket&format=json&query=x"
BODY = b'{"bucketQuery":"x","bucket":[]}'


@pytest.fixture(autouse=True)
def refuse_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that opens a socket.

    This is the fixture of `tests/test_mcmeta.py`, and that module holds the
    long form of the reason. The short form: the failure is a `RuntimeError`
    because `get_bytes` maps every `OSError` to a `FetchError`, so an `OSError`
    here would be caught by the code under test. The test would then pass while
    it read the live wiki.
    """

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("this test tried to reach the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


@pytest.fixture(autouse=True)
def refuse_a_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test of this module that sleeps for real.

    Every object here takes its sleep as an argument. A test that forgets to
    pass one would still pass, and it would pay the whole backoff in wall clock
    to do it: the default policy waits up to seven seconds, and a later change
    to the defaults could make that minutes. Failing is louder than being slow.
    """

    def refuse(seconds: float) -> None:
        raise RuntimeError(f"this test slept for {seconds} seconds")

    monkeypatch.setattr(time, "sleep", refuse)


class FakeClock:
    """A monotonic clock that only moves when a fake sleep moves it."""

    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def read(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_the_first_request_of_a_limiter_does_not_wait() -> None:
    """A limiter that has sent nothing has nothing to space the next request from."""
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock.read, sleep=clock.sleep)
    limiter.wait()
    assert clock.slept == []


def test_a_limiter_spaces_two_requests_by_the_interval() -> None:
    """The second request waits out the rest of the interval."""
    clock = FakeClock()
    limiter = RateLimiter(2.0, clock=clock.read, sleep=clock.sleep)
    limiter.wait()
    limiter.wait()
    assert clock.slept == [2.0]


def test_a_limiter_does_not_wait_when_the_caller_was_already_slow() -> None:
    """Time spent fetching counts against the interval.

    Otherwise a stage whose requests each take a second would be spaced by the
    interval on top of that second, and a whole build would run at half speed
    for no benefit to the service.
    """
    clock = FakeClock()
    limiter = RateLimiter(1.0, clock=clock.read, sleep=clock.sleep)
    limiter.wait()
    clock.now += 5.0
    limiter.wait()
    assert clock.slept == []


def test_a_limiter_keeps_spacing_over_many_requests() -> None:
    """The spacing is a rate, not a one-time delay."""
    clock = FakeClock()
    limiter = RateLimiter(0.5, clock=clock.read, sleep=clock.sleep)
    for _ in range(4):
        limiter.wait()
    assert clock.slept == [0.5, 0.5, 0.5]
    assert clock.now == pytest.approx(101.5)


def test_a_limiter_of_zero_never_waits() -> None:
    """An interval of zero is the way to turn the limiter off."""
    clock = FakeClock()
    limiter = RateLimiter(0.0, clock=clock.read, sleep=clock.sleep)
    for _ in range(3):
        limiter.wait()
    assert clock.slept == []


def test_a_negative_interval_is_refused() -> None:
    """A negative interval would set the next slot in the past, so it limits nothing."""
    with pytest.raises(ValueError, match="cannot be negative"):
        RateLimiter(-1.0)


def test_the_default_interval_is_the_documented_one() -> None:
    """The default of `RateLimiter` is the constant, not a second copy of a number."""
    assert RateLimiter().min_interval == DEFAULT_MIN_INTERVAL_SECONDS


def test_the_limiter_reads_a_monotonic_clock_by_default() -> None:
    """A wall clock steps backwards when NTP corrects it, and a limiter must not."""
    limiter = RateLimiter()
    assert limiter._clock is time.monotonic


@pytest.mark.parametrize("status", [None, 429, 500, 502, 503, 504])
def test_a_retryable_fault_is_retried(status: int | None) -> None:
    """A fault below HTTP, a 429, and every 5xx can pass on a second try."""
    assert RetryPolicy().should_retry(FetchError("failed", status=status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 418])
def test_a_client_fault_other_than_429_is_not_retried(status: int) -> None:
    """The answer to a bad request does not change, so a retry only costs the service.

    This is the rule that keeps a misspelled field name from turning into four
    requests. The Bucket API answers such a query with HTTP 200 rather than a
    4xx, so the guard that catches it is in `parse_bucket_answer`; this one
    catches the bad URL and the missing page.
    """
    assert RetryPolicy().should_retry(FetchError("failed", status=status)) is False


def test_the_wait_doubles_with_each_try() -> None:
    """The backoff backs off. A random value of zero shows the base wait alone."""
    policy = RetryPolicy(jitter=0.0)
    error = FetchError("failed", status=503)
    waits = [policy.wait_seconds(attempt, error=error, random_value=0.0) for attempt in (1, 2, 3)]
    assert waits == [1.0, 2.0, 4.0]


def test_the_wait_carries_a_random_part() -> None:
    """A build whose reads all fail together must not retry them all together."""
    policy = RetryPolicy(jitter=0.25)
    error = FetchError("failed", status=503)
    assert policy.wait_seconds(1, error=error, random_value=0.0) == pytest.approx(1.0)
    assert policy.wait_seconds(1, error=error, random_value=1.0) == pytest.approx(1.25)


def test_the_wait_is_capped() -> None:
    """A doubling wait would reach hours. The tries run out first instead."""
    policy = RetryPolicy(attempts=20, jitter=0.0)
    error = FetchError("failed", status=503)
    assert policy.wait_seconds(19, error=error, random_value=0.0) == MAX_WAIT_SECONDS


def test_the_cap_holds_when_the_wait_carries_its_random_part() -> None:
    """The jitter adds time, so the cap has to be applied after it and not before.

    Capping the doubling alone lets the default policy return
    `MAX_WAIT_SECONDS * 1.25`, which is seventy-five seconds against a ceiling
    the module documents as sixty. A field named for a maximum has to be one.
    """
    policy = RetryPolicy(attempts=20)
    error = FetchError("failed", status=503)
    waits = [
        policy.wait_seconds(attempt, error=error, random_value=1.0) for attempt in range(1, 20)
    ]
    assert max(waits) == MAX_WAIT_SECONDS
    # Below the ceiling the random part is still there in full, which is where
    # the spreading is needed: the early tries, while a build's failed reads are
    # still bunched together.
    assert waits[0] == pytest.approx(1.25)


def test_a_retry_after_header_beats_the_calculated_wait() -> None:
    """The server named a number, and a client that knows better is not a good citizen."""
    policy = RetryPolicy(jitter=0.25)
    error = FetchError("failed", status=429, retry_after="30")
    assert policy.wait_seconds(1, error=error, random_value=1.0) == pytest.approx(30.0)


def test_a_retry_after_header_is_capped_too() -> None:
    """An hour is a real answer from a server and a build-breaking one to obey."""
    policy = RetryPolicy()
    error = FetchError("failed", status=429, retry_after="3600")
    assert policy.wait_seconds(1, error=error, random_value=0.0) == MAX_WAIT_SECONDS


def test_a_retry_after_date_is_read_as_a_distance_from_now() -> None:
    """RFC 9110 allows an HTTP date there, and some servers send one."""
    # 2026-08-27T07:00:30Z, read from a `now` of 2026-08-27T07:00:00Z.
    now = 1787814000.0
    assert retry_after_seconds("Thu, 27 Aug 2026 07:00:30 GMT", now=now) == pytest.approx(30.0)


def test_a_retry_after_date_in_the_past_waits_no_time() -> None:
    """A date that has gone by means retry now, not retry never."""
    now = 1787814000.0
    assert retry_after_seconds("Thu, 27 Aug 2026 06:00:00 GMT", now=now) == 0.0


@pytest.mark.parametrize("value", [None, "", "   ", "soon", "not a date", "Thu, 99 Xxx 2026"])
def test_an_unreadable_retry_after_falls_back_to_the_calculated_wait(value: str | None) -> None:
    """A header this function cannot read is not worth guessing at or failing on."""
    assert retry_after_seconds(value) is None


def test_a_retry_after_without_a_time_zone_is_refused() -> None:
    """A date with no zone would be read as local time, which moves the wait by hours."""
    assert retry_after_seconds("Thu, 27 Aug 2026 07:00:30") is None


def test_a_policy_must_allow_at_least_one_try() -> None:
    """Zero tries would send no request and return nothing."""
    with pytest.raises(ValidationError):
        RetryPolicy(attempts=0)


def test_a_polite_transport_returns_the_body_of_a_good_read() -> None:
    """The wrapper is a `Transport`, so it hands back exactly what the inner one read."""
    seen: list[str] = []

    def inner(url: str) -> bytes:
        seen.append(url)
        return BODY

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(0.0, clock=clock.read, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    assert transport(URL) == BODY
    assert seen == [URL]


def test_a_polite_transport_retries_a_server_fault_and_then_succeeds() -> None:
    """Three tries: two 503s and one body."""
    calls: list[str] = []

    def inner(url: str) -> bytes:
        calls.append(url)
        if len(calls) < 3:
            raise FetchError("failed", status=503)
        return BODY

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(0.0, clock=clock.read, sleep=clock.sleep),
        policy=RetryPolicy(jitter=0.0),
        sleep=clock.sleep,
        random_value=lambda: 0.0,
    )
    assert transport(URL) == BODY
    assert len(calls) == 3
    assert clock.slept == [1.0, 2.0]


def test_a_polite_transport_gives_up_after_the_last_try() -> None:
    """The error that the caller sees is the last one, and no try is silently dropped."""
    calls: list[str] = []

    def inner(url: str) -> bytes:
        calls.append(url)
        raise FetchError(f"failed try {len(calls)}", status=500)

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(0.0, clock=clock.read, sleep=clock.sleep),
        policy=RetryPolicy(attempts=3, jitter=0.0),
        sleep=clock.sleep,
        random_value=lambda: 0.0,
    )
    with pytest.raises(FetchError, match="failed try 3"):
        transport(URL)
    assert len(calls) == 3
    # Two waits for three tries. A wait after the last try would delay the
    # failure without ever using it.
    assert clock.slept == [1.0, 2.0]


def test_a_polite_transport_does_not_retry_a_404() -> None:
    """One request, one failure, and nothing more sent to the service."""
    calls: list[str] = []

    def inner(url: str) -> bytes:
        calls.append(url)
        raise FetchError("not found", status=404)

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(0.0, clock=clock.read, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    with pytest.raises(FetchError, match="not found"):
        transport(URL)
    assert len(calls) == 1
    assert clock.slept == []


def test_a_polite_transport_spaces_a_retry_like_any_other_request() -> None:
    """A retry is another request. The rate limit applies to it too."""
    calls: list[str] = []

    def inner(url: str) -> bytes:
        calls.append(url)
        if len(calls) < 2:
            raise FetchError("failed", status=503)
        return BODY

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(5.0, clock=clock.read, sleep=clock.sleep),
        policy=RetryPolicy(jitter=0.0),
        sleep=clock.sleep,
        random_value=lambda: 0.0,
    )
    assert transport(URL) == BODY
    # One second of backoff, and then four more to fill the five-second slot.
    assert clock.slept == [1.0, 4.0]


def test_one_transport_spaces_every_url_it_reads() -> None:
    """The limiter belongs to the transport, so one transport is one rate.

    This is the reason to build one `polite_transport` for a whole build. Two
    transports hold two limiters, and the service sees the sum of both.
    """
    clock = FakeClock()
    transport = polite_transport(
        lambda url: BODY,
        limiter=RateLimiter(1.0, clock=clock.read, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    transport(URL)
    transport(URL + "&offset=5000")
    assert clock.slept == [1.0]


def test_a_non_fetch_error_is_not_retried() -> None:
    """Only a `FetchError` describes an upstream fault. Anything else is a bug here."""
    calls: list[str] = []

    def inner(url: str) -> bytes:
        calls.append(url)
        raise ValueError("a bug in the parser, not a fault of the service")

    clock = FakeClock()
    transport = polite_transport(
        inner,
        limiter=RateLimiter(0.0, clock=clock.read, sleep=clock.sleep),
        sleep=clock.sleep,
    )
    with pytest.raises(ValueError, match="a bug in the parser"):
        transport(URL)
    assert len(calls) == 1
