"""Rate limiting and retry, wrapped around one transport.

CLAUDE.md asks two things of every network read of this pipeline: keep the reads
rate-limited, and be a good citizen with the wiki API, which is a volunteer-run
service. This module is where both rules live, so that no fetcher has to
remember them.

The module hands back a `Transport`, which is the callable that every fetcher of
this repository already takes. So a fetcher gains politeness by being handed a
different callable, and its own code does not change:

    transport = polite_transport()
    rows = fetch_bucket_rows("droptable", ("item", "json"), revision=version_id,
                             transport=transport)

Build one transport for a whole build and pass it everywhere. One transport
holds one `RateLimiter`, and the limiter is the thing that spaces the requests
out. Two transports have two limiters, so they do not space each other, and the
service sees the sum of both.

Two rules decide what a retry does, and both exist to keep this project from
becoming a load on a service that hosts it for free.

A retry only happens for a fault that a retry can fix. That is a 429, a 5xx, or
a fault with no status at all: a timeout, a refused connection, a truncated
body. Every other 4xx gets no retry, because the answer to a bad URL or a
misspelled field does not change on the second ask, and a project that retries
one anyway sends four requests to be told the same thing four times.

The wait between two tries doubles, and it carries a random part. The doubling
backs off from a service that is already struggling. The random part matters for
a different reason: a build fetches many URLs in a row through one transport, so
an outage makes every one of them fail and retry together. Without the random
part they would all wait exactly the same amount and arrive together as well,
and a service that is recovering would meet the whole build at once.

A `Retry-After` header beats both. The server named a number, and a client that
knows better than the server it is asking is not a good citizen.
"""

import random
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from http import HTTPStatus

from pydantic import BaseModel, Field

from pipeline.fetch import FetchError, Transport, get_bytes

__all__ = [
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "MAX_WAIT_SECONDS",
    "Clock",
    "RateLimiter",
    "RetryPolicy",
    "Sleeper",
    "polite_transport",
    "retry_after_seconds",
]

# How long a caller waits between two requests, by default.
#
# The wiki API publishes no rate limit for a read, so this number is a courtesy
# and not a rule that anything enforces. A tenth of a second holds one client to
# ten requests a second, which is well under what a browser opening a wiki page
# already sends, and it still pulls the 5,000-row page limit of a bucket in a
# handful of requests. The number is an argument, so a stage that reads
# thousands of sprite files can slow itself down further.
DEFAULT_MIN_INTERVAL_SECONDS = 0.1

# A `Retry-After` of an hour is a real answer, and waiting an hour inside a
# build is not. A wait longer than this is clamped, and the tries run out
# instead, which fails the build with the fault of the server rather than with a
# timeout of CI that names nothing.
MAX_WAIT_SECONDS = 60.0

# What the limiter reads to tell the time, and what it calls to wait. A test
# passes its own pair, so a test of a retry policy takes no real time.
type Clock = Callable[[], float]
type Sleeper = Callable[[float], None]


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    """Return the `Retry-After` header of `value` in seconds, or `None`.

    RFC 9110 allows two forms, and a server picks either one. `Retry-After: 30`
    is a count of seconds. `Retry-After: Wed, 27 Aug 2026 07:28:00 GMT` is an
    HTTP date, and the wait is the distance from now to that date.

    A form that this function cannot read gives `None`, and the caller then uses
    its own calculated wait. An unreadable header is not worth failing a build
    over, and it is not worth guessing at either.

    `now` is the current time as a POSIX timestamp. It is an argument so that a
    test of the date form does not depend on the clock of the machine.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(int(text))
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            # RFC 9110 dates are GMT. A date that parses without a zone would
            # otherwise be read as local time, which moves the wait by hours.
            return None
        seconds = moment.timestamp() - (time.time() if now is None else now)
    # A negative wait means the date has passed, or the server sent a negative
    # count. Retry at once rather than treat the answer as unreadable.
    return max(0.0, min(seconds, MAX_WAIT_SECONDS))


class RateLimiter:
    """Hold a minimum interval between two requests of one caller.

    The limiter is stateful on purpose. It remembers when the next request may
    go out, so a caller that sends ten requests in a loop is spaced by the
    interval without counting anything itself.

    It measures with `time.monotonic` rather than with `time.time`. A wall clock
    steps backwards when NTP corrects it, and a limiter that reads one would
    then wait for that correction to pass before it sent anything.
    """

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL_SECONDS,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleeper = time.sleep,
    ) -> None:
        if min_interval < 0:
            raise ValueError(f"a rate limit interval cannot be negative: {min_interval!r}")
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None

    def wait(self) -> None:
        """Block until the next request may go out, then claim that slot."""
        now = self._clock()
        if self._next_allowed is not None and now < self._next_allowed:
            self._sleep(self._next_allowed - now)
            # The slot that was waited for, not a second reading of the clock.
            # A second reading would make the result depend on how long the
            # sleep overshot, and it would make a test depend on a fake sleep
            # moving a fake clock.
            now = self._next_allowed
        self._next_allowed = now + self.min_interval


class RetryPolicy(BaseModel, frozen=True):
    """How many times to retry a failed fetch, and how long to wait between tries.

    `attempts` counts every try, not the retries alone. So `attempts=1` disables
    retrying, and the default of 4 sends one request and up to three more.
    """

    attempts: int = Field(default=4, ge=1)
    first_wait_seconds: float = Field(default=1.0, gt=0)
    multiplier: float = Field(default=2.0, ge=1)
    max_wait_seconds: float = Field(default=MAX_WAIT_SECONDS, gt=0)
    # The random part, as a fraction of the calculated wait. A jitter of 0.25
    # spreads a wait of four seconds over four to five seconds.
    jitter: float = Field(default=0.25, ge=0)

    def should_retry(self, error: FetchError) -> bool:
        """Return whether a second try of the request that raised `error` is worth sending.

        A fault with no status happened below HTTP: a timeout, a refused
        connection, a body that ended early. Those are the faults a retry exists
        for, so a missing status is retryable.

        A 429 says outright that the client asked too fast. A 5xx is the server
        reporting its own fault. Both can pass.

        Every other status is the server answering the question that was asked.
        A 404, a 403, and a 400 all mean that the same request gets the same
        answer, so a retry only costs the service another request.
        """
        if error.status is None:
            return True
        if error.status == HTTPStatus.TOO_MANY_REQUESTS:
            return True
        return error.status >= HTTPStatus.INTERNAL_SERVER_ERROR

    def wait_seconds(self, attempt: int, *, error: FetchError, random_value: float) -> float:
        """Return how long to wait after try number `attempt` failed with `error`.

        `attempt` counts from 1, so the first failure waits
        `first_wait_seconds` and each later one waits the multiplier times more.

        `random_value` is a number in the range 0 to 1. It arrives as an
        argument rather than from `random.random` inside, so a test reads an
        exact number instead of a range.

        A readable `Retry-After` wins and takes no jitter. The server named a
        moment, and spreading clients around a moment the server chose is the
        job of the server, not of this client.

        The cap is applied last, after the jitter, because the jitter adds time
        rather than removing it. Capping the doubling alone would let a wait of
        `max_wait_seconds` come back as `max_wait_seconds * (1 + jitter)` --
        seventy-five seconds against a documented ceiling of sixty -- so a field
        named for a maximum would not be one. Every wait below the ceiling still
        carries its full random part, which is where the spreading is needed:
        those are the early tries, when a build's failed reads are still bunched
        together.
        """
        named = retry_after_seconds(error.retry_after)
        if named is not None:
            return min(named, self.max_wait_seconds)
        raw = self.first_wait_seconds * self.multiplier ** (attempt - 1)
        return min(raw * (1.0 + self.jitter * random_value), self.max_wait_seconds)


def polite_transport(
    inner: Transport = get_bytes,
    *,
    limiter: RateLimiter | None = None,
    policy: RetryPolicy | None = None,
    sleep: Sleeper = time.sleep,
    random_value: Callable[[], float] = random.random,
) -> Transport:
    """Return a `Transport` that rate-limits `inner` and retries what a retry can fix.

    The result is a plain `Transport`, so it goes wherever `get_bytes` goes.

    Every fault still arrives as `FetchError`, and the one that the caller sees
    is the last one. A caller therefore reads the same errors it read before,
    and it cannot tell from the exception whether a retry happened. That is the
    point: politeness is not a behaviour that a fetcher has to know about.

    Pass `sleep` and `random_value` to make a test deterministic. Both default
    to the real thing.
    """
    the_limiter = RateLimiter() if limiter is None else limiter
    the_policy = RetryPolicy() if policy is None else policy

    def fetch(url: str) -> bytes:
        for attempt in range(1, the_policy.attempts + 1):
            # Inside the loop, not before it. A retry is another request, and it
            # is spaced from the last one like any other.
            the_limiter.wait()
            try:
                return inner(url)
            except FetchError as error:
                if attempt == the_policy.attempts or not the_policy.should_retry(error):
                    raise
                sleep(the_policy.wait_seconds(attempt, error=error, random_value=random_value()))
        # Unreachable: `attempts` is at least 1, so the loop either returns or
        # raises. mypy cannot read that from the field constraint, and a bare
        # fall-through would return `None` from a function typed to return
        # bytes.
        raise FetchError(f"GET {url} was not attempted: the retry policy allows no try.")

    return fetch
