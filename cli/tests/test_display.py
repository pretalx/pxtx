from __future__ import annotations

import pytest

from pxtx.display import (
    fmt_time,
    format_activity_row,
    format_effort,
    format_issue_detail,
    format_issue_row,
    format_milestone,
    format_milestone_row,
    format_priority,
)


def test_fmt_time_iso():
    assert fmt_time("2026-04-22T10:15:00+00:00") == "2026-04-22 10:15"


def test_fmt_time_z_suffix():
    assert fmt_time("2026-04-22T10:15:00Z") == "2026-04-22 10:15"


def test_fmt_time_none():
    assert fmt_time(None) == "-"


@pytest.mark.parametrize(
    ("value", "expected"),
    ((1, "want"), (2, "should"), (3, "could"), (4, "whatev"), (5, "lol"), (9, "9")),
)
def test_format_priority(value, expected):
    assert format_priority(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, "-"),
        (30, "<1h"),
        (90, "1-2h"),
        (240, "2-6h"),
        (480, "1d"),
        (960, ">1d"),
        (77, "77"),
    ),
)
def test_format_effort(value, expected):
    assert format_effort(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    ((None, "-"), ({"slug": "r1", "name": "Release 1"}, "r1"), ("r1", "r1"), ({}, "-")),
)
def test_format_milestone(value, expected):
    assert format_milestone(value) == expected


def test_format_issue_row_handles_missing_assignee():
    row = format_issue_row(
        {"slug": "PX-1", "status": "open", "priority": 2, "assignee": "", "title": "x"}
    )

    assert "PX-1" in row
    assert "open" in row
    assert "should" in row
    assert "-" in row
    assert "x" in row


def test_format_issue_detail_full():
    issue = {
        "slug": "PX-7",
        "title": "do a thing",
        "status": "blocked",
        "priority": 1,
        "effort_minutes": 90,
        "assignee": "claude/x",
        "milestone": {"slug": "r1", "name": "Release 1"},
        "created_at": "2026-04-22T10:00:00+00:00",
        "updated_at": "2026-04-22T10:05:00+00:00",
        "is_highlighted": True,
        "blocked_reason": "waiting",
        "description": "# header\n\nbody",
    }
    comments = [
        {"author": "tobias", "created_at": "2026-04-22T10:10:00+00:00", "body": "hi"}
    ]

    text = format_issue_detail(issue, comments)

    assert "PX-7: do a thing" in text
    assert "status: blocked" in text
    assert "priority: want" in text
    assert "effort: 1-2h" in text
    assert "milestone: r1" in text
    assert "*highlighted*" in text
    assert "blocked reason: waiting" in text
    assert "# header" in text
    assert "=== comments (1) ===" in text
    assert "[tobias · 2026-04-22 10:10]" in text


def test_format_issue_detail_minimal():
    issue = {
        "slug": "PX-1",
        "title": "bare",
        "status": "open",
        "priority": 3,
        "effort_minutes": None,
        "assignee": "",
        "milestone": None,
        "created_at": "2026-04-22T10:00:00+00:00",
        "updated_at": "2026-04-22T10:00:00+00:00",
    }

    text = format_issue_detail(issue)

    assert "milestone: -" in text
    assert "effort: -" in text
    assert "*highlighted*" not in text
    assert "blocked reason" not in text
    assert "=== comments" not in text


def test_format_milestone_row_missing_target():
    row = format_milestone_row({"slug": "r1", "name": "Release 1"})

    assert "r1" in row
    assert "-" in row
    assert "Release 1" in row


def test_format_milestone_row_with_target():
    row = format_milestone_row(
        {"slug": "r1", "name": "Release 1", "target_date": "2026-05-01"}
    )

    assert "2026-05-01" in row


def test_format_activity_row():
    row = format_activity_row(
        {
            "timestamp": "2026-04-22T10:00:00+00:00",
            "actor": "tester",
            "action_type": "pxtx.issue.create",
            "content_type": "issue",
            "object_id": 5,
        }
    )

    assert "2026-04-22 10:00" in row
    assert "tester" in row
    assert "pxtx.issue.create" in row
    assert "issue#5" in row


def test_format_activity_row_no_actor():
    row = format_activity_row(
        {
            "timestamp": "2026-04-22T10:00:00+00:00",
            "actor": "",
            "action_type": "pxtx.issue.create",
            "content_type": "issue",
            "object_id": 5,
        }
    )

    assert " - " in row
