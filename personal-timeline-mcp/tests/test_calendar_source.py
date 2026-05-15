"""Tests for the .ics calendar reader."""
from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest
from personal_timeline.sources import calendar as cal

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_path() -> Path:
    return FIXTURES / "sample.ics"


def test_fixture_yields_five_events(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    assert len(events) == 5


def test_event_shape(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    standup = next(e for e in events if e.payload["uid"] == "evt1@example.com")
    assert standup.source == "calendar"
    assert standup.title == "Standup"
    assert standup.end_ts is not None
    assert standup.end_ts - standup.ts == 30 * 60
    assert "Zoom" in standup.body


def test_line_unfolding_joins_continuation(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    standup = next(e for e in events if e.payload["uid"] == "evt1@example.com")
    desc = standup.payload["description"]
    assert "continuation line" in desc
    # The literal "\n" escape decodes to a real newline.
    assert "Daily sync" in desc.split("\n")[0]


def test_date_only_event_treated_as_midnight_utc(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    birthday = next(e for e in events if e.payload["uid"] == "evt4@example.com")
    # 20260601 -> 2026-06-01T00:00:00Z
    from datetime import datetime
    expected = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
    assert birthday.ts == expected


def test_tzid_event_parses_with_floating_local(fixture_path: Path):
    """We don't yet apply TZID — parsed as floating local treated as UTC.
    Pins the v1 behavior so the choice is explicit."""
    events = list(cal.read_events(fixture_path))
    review = next(e for e in events if e.payload["uid"] == "evt3@example.com")
    from datetime import datetime
    expected = int(datetime(2026, 5, 15, 10, 0, tzinfo=UTC).timestamp())
    assert review.ts == expected


def test_escape_sequences_decoded(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    coffee = next(e for e in events if e.payload["uid"] == "evt5@example.com")
    # `\,` decodes to literal comma
    assert "side projects, including" in coffee.payload["description"]


def test_uid_used_as_source_id(fixture_path: Path):
    events = list(cal.read_events(fixture_path))
    uids = {e.source_id for e in events}
    assert {"evt1@example.com", "evt2@example.com", "evt5@example.com"} <= uids


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        list(cal.read_events("/does/not/exist.ics"))
