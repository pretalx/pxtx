import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.test import override_settings

from pxtx.core.management.commands import runperiodic as runperiodic_module
from pxtx.core.models import (
    ActivityLog,
    GithubRef,
    GithubRefKind,
    Issue,
    Source,
    Status,
)
from tests.factories import GithubIssueRefFactory

pytestmark = pytest.mark.integration


def _fake_response(payload):
    """Return a context-manager-friendly stand-in for an ``urlopen`` response."""
    mock = MagicMock()
    mock.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
    mock.__exit__.return_value = False
    return mock


def _patch_urlopen(monkeypatch, responses):
    """Patch urllib.request.urlopen, replaying one response per call."""
    calls = []
    iterator = iter(responses)

    def fake_urlopen(request, timeout=None):
        calls.append({"url": request.full_url, "headers": dict(request.header_items())})
        value = next(iterator)
        if isinstance(value, Exception):
            raise value
        return _fake_response(value)

    monkeypatch.setattr(runperiodic_module.urllib.request, "urlopen", fake_urlopen)
    return calls


def _issue_payload(number, **overrides):
    payload = {
        "number": number,
        "title": f"GH issue {number}",
        "body": f"Body for {number}",
        "state": "open",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_creates_ghost_issue_per_unlinked_github_issue(monkeypatch):
    _patch_urlopen(monkeypatch, [[_issue_payload(101), _issue_payload(102)]])

    out = io.StringIO()
    call_command("runperiodic", stdout=out)

    assert Issue.objects.count() == 2
    issues = list(Issue.objects.order_by("number"))
    assert [i.status for i in issues] == [Status.DRAFT, Status.DRAFT]
    assert [i.source for i in issues] == [Source.GITHUB, Source.GITHUB]
    assert [i.title for i in issues] == ["GH issue 101", "GH issue 102"]
    assert [i.description for i in issues] == ["Body for 101", "Body for 102"]

    refs = list(
        GithubRef.objects.order_by("number").values_list(
            "repo", "kind", "number", "title", "state"
        )
    )
    assert refs == [
        ("pretalx/pretalx", GithubRefKind.ISSUE, 101, "GH issue 101", "open"),
        ("pretalx/pretalx", GithubRefKind.ISSUE, 102, "GH issue 102", "open"),
    ]
    output = out.getvalue()
    assert "pretalx/pretalx: created 2 ghost issue(s)" in output
    assert "Done. 2 ghost issue(s) created." in output


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_emits_activity_log_with_periodic_actor(monkeypatch):
    _patch_urlopen(monkeypatch, [[_issue_payload(7)]])

    call_command("runperiodic", stdout=io.StringIO())

    create_log = ActivityLog.objects.get(action_type="pxtx.issue.create")
    assert create_log.actor == "periodic/github-sync"


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_skips_issues_already_linked_by_a_ref(monkeypatch):
    existing_issue = GithubIssueRefFactory(repo="pretalx/pretalx", number=42).issue
    _patch_urlopen(monkeypatch, [[_issue_payload(42), _issue_payload(43)]])

    out = io.StringIO()
    call_command("runperiodic", stdout=out)

    # One pre-existing issue plus one new draft.
    assert Issue.objects.count() == 2
    assert Issue.objects.filter(status=Status.DRAFT).count() == 1
    new_issue = Issue.objects.exclude(pk=existing_issue.pk).get()
    assert new_issue.source == Source.GITHUB
    assert list(new_issue.github_refs.values_list("number", flat=True)) == [43]
    assert "pretalx/pretalx: created 1 ghost issue(s)" in out.getvalue()


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_ignores_pull_requests_from_issues_endpoint(monkeypatch):
    _patch_urlopen(
        monkeypatch,
        [[_issue_payload(10, pull_request={"url": "..."}), _issue_payload(11)]],
    )

    call_command("runperiodic", stdout=io.StringIO())

    numbers = list(GithubRef.objects.values_list("number", flat=True))
    assert numbers == [11]


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_skips_payloads_without_number(monkeypatch):
    payload_without_number = _issue_payload(1)
    payload_without_number.pop("number")
    _patch_urlopen(monkeypatch, [[payload_without_number, _issue_payload(5)]])

    call_command("runperiodic", stdout=io.StringIO())

    assert list(GithubRef.objects.values_list("number", flat=True)) == [5]


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_uses_fallback_title_when_github_title_empty(monkeypatch):
    _patch_urlopen(monkeypatch, [[_issue_payload(12, title="", body="")]])

    call_command("runperiodic", stdout=io.StringIO())

    issue = Issue.objects.get()
    assert issue.title == "pretalx/pretalx#12"
    assert issue.description == ""


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_truncates_titles_longer_than_500_chars(monkeypatch):
    long_title = "x" * 600
    _patch_urlopen(monkeypatch, [[_issue_payload(13, title=long_title)]])

    call_command("runperiodic", stdout=io.StringIO())

    issue = Issue.objects.get()
    assert len(issue.title) == 500
    ref = GithubRef.objects.get()
    assert len(ref.title) == 500


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=[], GITHUB_TOKEN="")
def test_runperiodic_without_repos_does_nothing(monkeypatch):
    # No urlopen calls should happen — make it explode if it does.
    monkeypatch.setattr(
        runperiodic_module.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("should not call GitHub"),
    )

    out = io.StringIO()
    call_command("runperiodic", stdout=out)

    assert Issue.objects.count() == 0
    assert "No repos configured" in out.getvalue()


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_paginates_until_a_short_page(monkeypatch):
    first_page = [_issue_payload(n) for n in range(1, runperiodic_module.PAGE_SIZE + 1)]
    second_page = [_issue_payload(9999)]
    calls = _patch_urlopen(monkeypatch, [first_page, second_page])

    call_command("runperiodic", stdout=io.StringIO())

    assert Issue.objects.count() == runperiodic_module.PAGE_SIZE + 1
    assert [call["url"].rsplit("&page=", 1)[-1] for call in calls] == ["1", "2"]


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_stops_iterating_on_empty_page(monkeypatch):
    full_page = [_issue_payload(n) for n in range(1, runperiodic_module.PAGE_SIZE + 1)]
    # A full page followed by an empty one should stop after the empty one,
    # not request a third page.
    calls = _patch_urlopen(monkeypatch, [full_page, []])

    call_command("runperiodic", stdout=io.StringIO())

    assert len(calls) == 2
    assert Issue.objects.count() == runperiodic_module.PAGE_SIZE


@pytest.mark.django_db
@override_settings(
    GITHUB_WATCH_REPOS=["pretalx/pretalx", "pretalx/pretalx-public-voting"],
    GITHUB_TOKEN="",
)
def test_runperiodic_polls_each_configured_repo(monkeypatch):
    _patch_urlopen(monkeypatch, [[_issue_payload(1)], [_issue_payload(2)]])

    out = io.StringIO()
    call_command("runperiodic", stdout=out)

    repos = sorted(GithubRef.objects.values_list("repo", flat=True))
    assert repos == ["pretalx/pretalx", "pretalx/pretalx-public-voting"]
    assert "pretalx/pretalx: created 1 ghost issue(s)" in out.getvalue()
    assert "pretalx/pretalx-public-voting: created 1 ghost issue(s)" in out.getvalue()


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_repo_argument_overrides_settings(monkeypatch):
    _patch_urlopen(monkeypatch, [[_issue_payload(77)]])

    call_command("runperiodic", "--repo", "other/repo", stdout=io.StringIO())

    assert list(GithubRef.objects.values_list("repo", flat=True)) == ["other/repo"]


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_logs_and_skips_on_http_error(monkeypatch, caplog):
    # The "pxtx" root logger runs with propagate=False in settings, so
    # caplog's handler (installed on the root logger) never sees records.
    # Re-enable propagation at that hop for the duration of the test.
    monkeypatch.setattr(logging.getLogger("pxtx"), "propagate", True)
    error = urllib.error.HTTPError(
        url="https://api.github.com/...",
        code=403,
        msg="rate limited",
        hdrs=None,
        fp=None,
    )
    _patch_urlopen(monkeypatch, [error])

    with caplog.at_level("ERROR", logger=runperiodic_module.logger.name):
        call_command("runperiodic", stdout=io.StringIO())

    assert Issue.objects.count() == 0
    assert any(
        "403" in record.getMessage() and "pretalx/pretalx" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_logs_and_skips_on_url_error(monkeypatch, caplog):
    monkeypatch.setattr(logging.getLogger("pxtx"), "propagate", True)
    _patch_urlopen(monkeypatch, [urllib.error.URLError("dns boom")])

    with caplog.at_level("ERROR", logger=runperiodic_module.logger.name):
        call_command("runperiodic", stdout=io.StringIO())

    assert Issue.objects.count() == 0
    assert any("dns boom" in record.getMessage() for record in caplog.records)


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="secret-pat")
def test_runperiodic_sends_bearer_token_when_configured(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [[]])

    call_command("runperiodic", stdout=io.StringIO())

    assert calls[0]["headers"].get("Authorization") == "Bearer secret-pat"


@pytest.mark.django_db
@override_settings(GITHUB_WATCH_REPOS=["pretalx/pretalx"], GITHUB_TOKEN="")
def test_runperiodic_omits_authorization_header_when_token_empty(monkeypatch):
    calls = _patch_urlopen(monkeypatch, [[]])

    call_command("runperiodic", stdout=io.StringIO())

    assert "Authorization" not in calls[0]["headers"]
    # Sanity-check the rest of the header set that we always send.
    assert calls[0]["headers"]["User-agent"] == runperiodic_module.USER_AGENT
    assert calls[0]["headers"]["Accept"] == "application/vnd.github+json"
