"""One form of time for every log Assignment 5 compares: UTC, ISO 8601, to the
millisecond, such as 2026-10-30T14:02:07.513Z.

The checker orders events across files by these strings: a notification before a
run's first write, a stop before the first call it refused, no write after a stop.
Write every time in logs/ with now(), and read one with parse().

    from harness.clock import now, parse, seconds_between
    at = now()                                   # "2026-10-30T14:02:07.513Z"
    seconds_between(requested, effective)        # 1.204
"""

from __future__ import annotations

from datetime import datetime, timezone


def now() -> str:
    """This moment, as the logs write it."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse(stamp: str) -> datetime:
    """A time written by now() (or any ISO 8601 time; one with no zone is read as UTC)."""
    when = datetime.fromisoformat(str(stamp).strip().replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def seconds_between(earlier: str, later: str) -> float:
    """Seconds from one logged time to another, to the millisecond."""
    return round((parse(later) - parse(earlier)).total_seconds(), 3)
