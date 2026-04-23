import pytest

from pxtx.core.models import ActivityLog, Issue
from tests.factories import (
    CommentFactory,
    GithubIssueRefFactory,
    IssueFactory,
    IssueReferenceFactory,
    MilestoneFactory,
)

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_list_issues_returns_paginated_results(token_client):
    IssueFactory.create_batch(3)

    response = token_client.get("/api/v1/issues/")

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 3
    assert {r["slug"] for r in body["results"]} == {
        f"PX-{i.number}" for i in Issue.objects.all()
    }


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", (1, 3))
def test_list_issues_query_count_is_constant(
    token_client, django_assert_num_queries, item_count
):
    """Every issue in the list is fully populated — a comment, a GitHub ref,
    an outbound cross-reference, and an inbound one. If any of the four
    serialized collections slips back to a per-row query, the count diverges
    between item_count=1 and item_count=3 and this test breaks."""
    milestone = MilestoneFactory()
    for _ in range(item_count):
        issue = IssueFactory(milestone=milestone)
        CommentFactory(issue=issue)
        GithubIssueRefFactory(issue=issue)
        IssueReferenceFactory(from_issue=issue, to_issue=IssueFactory())
        IssueReferenceFactory(from_issue=IssueFactory(), to_issue=issue)

    with django_assert_num_queries(6):
        response = token_client.get("/api/v1/issues/")

    assert response.status_code == 200
    body = response.json()
    # item_count issues + 2*item_count "other side" issues from the ref setup.
    assert len(body["results"]) == 3 * item_count


@pytest.mark.django_db
def test_list_filters_by_status_csv(token_client):
    open_issue = IssueFactory(status="open")
    wip_issue = IssueFactory(status="wip")
    IssueFactory(status="completed")

    response = token_client.get("/api/v1/issues/?status=open,wip")

    assert response.status_code == 200
    results = response.json()["results"]
    assert {r["number"] for r in results} == {open_issue.number, wip_issue.number}


@pytest.mark.django_db
def test_list_filters_by_priority(token_client):
    want = IssueFactory(priority=1)
    IssueFactory(priority=3)

    response = token_client.get("/api/v1/issues/?priority=1")

    assert [r["number"] for r in response.json()["results"]] == [want.number]


@pytest.mark.django_db
def test_list_filters_by_milestone_slug(token_client):
    milestone = MilestoneFactory(slug="release-1")
    in_milestone = IssueFactory(milestone=milestone)
    IssueFactory()

    response = token_client.get("/api/v1/issues/?milestone=release-1")

    assert [r["number"] for r in response.json()["results"]] == [in_milestone.number]


@pytest.mark.django_db
def test_list_filters_by_missing_milestone(token_client):
    milestone = MilestoneFactory()
    IssueFactory(milestone=milestone)
    unassigned = IssueFactory()

    response = token_client.get("/api/v1/issues/?milestone=null")

    assert [r["number"] for r in response.json()["results"]] == [unassigned.number]


@pytest.mark.django_db
def test_list_filters_by_assignee_icontains(token_client):
    matching = IssueFactory(assignee="claude/feature-x")
    IssueFactory(assignee="someone-else")

    response = token_client.get("/api/v1/issues/?assignee=claude")

    assert [r["number"] for r in response.json()["results"]] == [matching.number]


@pytest.mark.django_db
def test_list_filters_by_highlighted_toggle(token_client):
    star = IssueFactory(is_highlighted=True)
    IssueFactory(is_highlighted=False)

    response = token_client.get("/api/v1/issues/?is_highlighted=true")

    assert [r["number"] for r in response.json()["results"]] == [star.number]


@pytest.mark.django_db
def test_list_filters_by_source(token_client):
    gh = IssueFactory(source="github")
    IssueFactory(source="manual")

    response = token_client.get("/api/v1/issues/?source=github")

    assert [r["number"] for r in response.json()["results"]] == [gh.number]


@pytest.mark.django_db
def test_list_filters_by_search_matches_description(token_client):
    match = IssueFactory(title="normal", description="has haystack in it")
    IssueFactory(title="also normal", description="no match here")

    response = token_client.get("/api/v1/issues/?search=haystack")

    assert [r["number"] for r in response.json()["results"]] == [match.number]


@pytest.mark.django_db
def test_list_filters_by_search_matches_issue_number(token_client):
    issues = [IssueFactory(title=f"issue {i}") for i in range(5)]
    target = issues[2]

    response = token_client.get(f"/api/v1/issues/?search={target.number}")

    assert target.number in [r["number"] for r in response.json()["results"]]


@pytest.mark.django_db
def test_retrieve_issue_by_number_not_pk(token_client):
    issue = IssueFactory()
    # Bump pk/number apart to make sure number-based lookup is used.
    response = token_client.get(f"/api/v1/issues/{issue.number}/")

    assert response.status_code == 200
    assert response.json()["slug"] == f"PX-{issue.number}"


@pytest.mark.django_db
def test_create_issue_logs_create_activity(token_client, api_token):
    response = token_client.post(
        "/api/v1/issues/", {"title": "new thing", "priority": 2}, format="json"
    )

    assert response.status_code == 201
    issue = Issue.objects.get(number=response.json()["number"])
    entry = ActivityLog.objects.get(action_type="pxtx.issue.create")
    assert entry.actor == api_token.name
    assert entry.object_id == issue.pk


@pytest.mark.django_db
def test_create_issue_accepts_blocked_with_reason(token_client):
    response = token_client.post(
        "/api/v1/issues/",
        {"title": "x", "status": "blocked", "blocked_reason": "waiting"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "blocked"
    assert response.json()["blocked_reason"] == "waiting"


@pytest.mark.django_db
def test_transition_between_non_blocked_states(token_client):
    """Going from wip → completed shouldn't touch blocked_reason on either
    side — covers the branch where neither old nor new status is blocked."""
    issue = IssueFactory(status="wip", blocked_reason="")

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/completed/", {}, format="json"
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.status == "completed"
    assert issue.blocked_reason == ""


@pytest.mark.django_db
def test_create_issue_rejects_blocked_without_reason(token_client):
    response = token_client.post(
        "/api/v1/issues/", {"title": "x", "status": "blocked"}, format="json"
    )

    assert response.status_code == 400
    assert "blocked_reason" in response.json()


@pytest.mark.django_db
def test_patch_updates_fields_and_logs_update(token_client, api_token):
    issue = IssueFactory(title="old", priority=3)

    response = token_client.patch(
        f"/api/v1/issues/{issue.number}/",
        {"title": "new", "priority": 1},
        format="json",
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.title == "new"
    assert issue.priority == 1
    entry = ActivityLog.objects.get(action_type="pxtx.issue.update")
    assert entry.actor == api_token.name
    assert entry.data["before"]["title"] == "old"
    assert entry.data["after"]["title"] == "new"


@pytest.mark.django_db
def test_patch_without_changes_skips_logging(token_client):
    issue = IssueFactory(title="same")

    token_client.patch(
        f"/api/v1/issues/{issue.number}/", {"title": "same"}, format="json"
    )

    assert ActivityLog.objects.filter(action_type="pxtx.issue.update").count() == 0


@pytest.mark.django_db
def test_patch_rejects_status_field_with_400(token_client):
    issue = IssueFactory(status="open")

    response = token_client.patch(
        f"/api/v1/issues/{issue.number}/", {"status": "wip"}, format="json"
    )

    assert response.status_code == 400
    assert "status" in response.json()
    issue.refresh_from_db()
    assert issue.status == "open"


@pytest.mark.django_db
@pytest.mark.parametrize("target", ("open", "wip", "completed", "wontfix", "draft"))
def test_status_action_transitions_and_logs(token_client, api_token, target):
    # Start from a status that is different from every target under test so
    # the transition always represents a real change (no-op transitions skip
    # logging because BaseModel.save compares before/after snapshots).
    issue = IssueFactory(status="blocked", blocked_reason="stale")

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/{target}/", {}, format="json"
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.status == target
    entry = ActivityLog.objects.get(action_type=f"pxtx.issue.status.{target}")
    assert entry.actor == api_token.name


@pytest.mark.django_db
def test_blocked_action_requires_reason(token_client):
    issue = IssueFactory(status="open")

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/blocked/", {}, format="json"
    )

    assert response.status_code == 400
    assert "blocked_reason" in response.json()
    issue.refresh_from_db()
    assert issue.status == "open"


@pytest.mark.django_db
def test_blocked_action_stores_reason(token_client):
    issue = IssueFactory(status="open")

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/blocked/",
        {"blocked_reason": "waiting on upstream"},
        format="json",
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.status == "blocked"
    assert issue.blocked_reason == "waiting on upstream"


@pytest.mark.django_db
def test_transition_out_of_blocked_clears_reason(token_client):
    issue = IssueFactory(status="blocked", blocked_reason="stuck")

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/wip/", {}, format="json"
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.blocked_reason == ""


@pytest.mark.django_db
def test_put_is_not_allowed(token_client):
    issue = IssueFactory()

    response = token_client.put(
        f"/api/v1/issues/{issue.number}/", {"title": "x"}, format="json"
    )

    assert response.status_code == 405


@pytest.mark.django_db
def test_detail_includes_github_refs_and_references(token_client):
    issue = IssueFactory(title="main")
    other = IssueFactory(title="other")

    GithubIssueRefFactory(issue=issue, number=42)
    IssueReferenceFactory(from_issue=issue, to_issue=other)

    response = token_client.get(f"/api/v1/issues/{issue.number}/")

    body = response.json()
    assert len(body["github_refs"]) == 1
    assert body["github_refs"][0]["number"] == 42
    assert body["references_out"] == [
        {
            "number": other.number,
            "slug": f"PX-{other.number}",
            "title": "other",
            "status": other.status,
        }
    ]
    assert body["references_in"] == []


@pytest.mark.django_db
def test_detail_references_in_shows_inbound_edges(token_client):
    target = IssueFactory()
    source = IssueFactory()

    IssueReferenceFactory(from_issue=source, to_issue=target)

    response = token_client.get(f"/api/v1/issues/{target.number}/")

    body = response.json()
    assert [r["number"] for r in body["references_in"]] == [source.number]
    assert body["references_out"] == []
