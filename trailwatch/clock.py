"""Where "today" comes from.

Readings carry a plain date with no timezone, and the staleness rule compares them against the
current day. `date.today()` answers in whatever timezone the machine happens to be set to, so the
same database could call a reading stale on one server and current on another, and the boundary
would move when a host's configuration changed. UTC is the one answer that does not depend on
where the process is running.

Everything that needs the current date takes it from here, and every caller can pass its own date
instead, which is what the tests do.
"""
import datetime as dt


def today():
    return dt.datetime.now(dt.UTC).date()
