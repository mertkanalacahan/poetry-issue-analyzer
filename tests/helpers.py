"""Small helpers shared by the Team 5 tests."""
from datetime import datetime, timezone

from model import Event, Issue, State


def utc(year, month, day):
    """A timezone-aware UTC datetime."""
    return datetime(year, month, day, tzinfo=timezone.utc)


def event(event_type, when, author="someone", comment=None, label=None):
    """Build an Event without going through JSON."""
    e = Event(None)
    e.event_type = event_type
    e.event_date = when
    e.author = author
    e.comment = comment
    e.label = label
    return e


def issue(events, creator="reporter", state="open", labels=None,
          created=None, number=1, title="Test issue"):
    """Build an Issue without going through JSON."""
    i = Issue()
    i.number = number
    i.title = title
    i.url = f"https://github.com/python-poetry/poetry/issues/{number}"
    i.creator = creator
    i.state = State.open if state == "open" else State.closed
    i.labels = ["kind/bug"] if labels is None else labels
    i.created_date = created or utc(2024, 1, 1)
    i.updated_date = i.created_date
    i.events = events
    return i
