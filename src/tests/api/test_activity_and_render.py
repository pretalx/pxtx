import pytest

from pxtx.core.models import ActivityLog
from tests.factories import IssueFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_activity_list_returns_entries(token_client):
    issue = IssueFactory()
    issue.title = "edited"
    issue.save(actor="tester")

    response = token_client.get("/api/v1/activity/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) >= 1
    assert {r["action_type"] for r in body["results"]} >= {"pxtx.issue.update"}


@pytest.mark.django_db
def test_activity_list_filters_by_content_type(token_client):
    issue = IssueFactory()
    issue.title = "edited"
    issue.save(actor="tester")

    response = token_client.get("/api/v1/activity/?content_type=issue")

    assert response.status_code == 200
    assert all(r["content_type"] == "issue" for r in response.json()["results"])


@pytest.mark.django_db
def test_activity_list_unknown_content_type_returns_empty(token_client):
    IssueFactory()

    response = token_client.get("/api/v1/activity/?content_type=not-a-model")

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.django_db
def test_activity_list_filters_by_issue_number(token_client):
    """``?issue=<number>`` must translate through Issue.pk so it hits the
    correct ActivityLog rows even if number/pk diverge."""
    target = IssueFactory()
    target.title = "edited"
    target.save(actor="tester")
    other = IssueFactory()
    other.title = "elsewhere"
    other.save(actor="tester")

    response = token_client.get(f"/api/v1/activity/?issue={target.number}")

    assert response.status_code == 200
    results = response.json()["results"]
    assert {r["object_id"] for r in results} == {target.pk}


@pytest.mark.django_db
def test_activity_list_filters_by_issue_number_unknown_returns_empty(token_client):
    issue = IssueFactory()
    issue.title = "edited"
    issue.save(actor="tester")

    response = token_client.get("/api/v1/activity/?issue=9999")

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.django_db
def test_activity_list_filters_by_since_timestamp(token_client):
    """Entries older than ``since`` must be excluded; newer ones kept."""
    from datetime import timedelta

    from django.utils import timezone

    from pxtx.core.models import ActivityLog

    old = IssueFactory()
    old.title = "old"
    old.save(actor="tester")
    new = IssueFactory()
    new.title = "new"
    new.save(actor="tester")

    cutoff = timezone.now() - timedelta(minutes=5)
    # Backdate the old entries so the ``since`` filter has something to exclude.
    ActivityLog.objects.filter(object_id=old.pk).update(
        timestamp=cutoff - timedelta(hours=1)
    )

    response = token_client.get("/api/v1/activity/", {"since": cutoff.isoformat()})

    assert response.status_code == 200
    object_ids = {r["object_id"] for r in response.json()["results"]}
    assert new.pk in object_ids
    assert old.pk not in object_ids


@pytest.mark.django_db
def test_activity_list_filters_by_actor(token_client):
    issue_a = IssueFactory()
    issue_a.title = "a"
    issue_a.save(actor="alice")
    issue_b = IssueFactory()
    issue_b.title = "b"
    issue_b.save(actor="bob")

    response = token_client.get("/api/v1/activity/?actor=alice")

    actors = {r["actor"] for r in response.json()["results"]}
    assert actors == {"alice"}


@pytest.mark.django_db
def test_activity_post_creates_custom_entry(token_client, api_token):
    issue = IssueFactory()

    response = token_client.post(
        "/api/v1/activity/",
        {
            "action_type": "pxtx.claude.ran-tests",
            "issue": issue.number,
            "data": {"passed": 42},
        },
        format="json",
    )

    assert response.status_code == 201
    entry = ActivityLog.objects.get(action_type="pxtx.claude.ran-tests")
    assert entry.object_id == issue.pk
    assert entry.actor == api_token.name
    assert entry.data == {"passed": 42}


@pytest.mark.django_db
def test_activity_post_requires_existing_issue(token_client):
    response = token_client.post(
        "/api/v1/activity/",
        {"action_type": "pxtx.claude.note", "issue": 9999},
        format="json",
    )

    assert response.status_code == 400
    assert "issue" in response.json()


@pytest.mark.django_db
def test_render_returns_html(token_client):
    response = token_client.post(
        "/api/v1/render/", {"text": "# Hello\n\n**bold**"}, format="json"
    )

    assert response.status_code == 200
    html = response.json()["html"]
    assert "<h1>" in html
    assert "<strong>bold</strong>" in html


@pytest.mark.django_db
def test_render_empty_text_returns_empty_html(token_client):
    response = token_client.post("/api/v1/render/", {"text": ""}, format="json")

    assert response.status_code == 200
    assert response.json()["html"] == ""
