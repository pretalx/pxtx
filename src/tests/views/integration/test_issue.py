import pytest

from pxtx.core.models import Status
from tests.factories import (
    CommentFactory,
    GithubIssueRefFactory,
    IssueFactory,
    IssueReferenceFactory,
    MilestoneFactory,
)

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_issue_list_requires_login(client):
    response = client.get("/issues/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_issue_list_renders_empty_state(auth_client):
    response = auth_client.get("/issues/")

    assert response.status_code == 200
    assert list(response.context["issues"]) == []
    assert "No issues match these filters." in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", (1, 3))
def test_issue_list_lists_all_issues_with_constant_query_count(
    auth_client, django_assert_num_queries, item_count
):
    milestone = MilestoneFactory()
    issues = [IssueFactory(milestone=milestone) for _ in range(item_count)]

    # Baseline query count depends on filter metadata lookups (milestones,
    # quick-filter counts), not on the number of issues — the point is that
    # it's constant across item_count = 1 and 3.
    with django_assert_num_queries(11):
        response = auth_client.get("/issues/")

    assert response.status_code == 200
    assert set(response.context["issues"]) == set(issues)


@pytest.mark.django_db
def test_issue_list_shows_comment_count(auth_client):
    chatty = IssueFactory(title="chatty")
    quiet = IssueFactory(title="quiet")
    CommentFactory(issue=chatty)
    CommentFactory(issue=chatty)

    response = auth_client.get("/issues/")

    assert response.status_code == 200
    issues = {i.number: i for i in response.context["issues"]}
    assert issues[chatty.number].comment_count == 2
    assert issues[quiet.number].comment_count == 0
    assert "💬 2" in response.content.decode()


@pytest.mark.django_db
def test_issue_detail_returns_404_for_unknown_number(auth_client):
    response = auth_client.get("/issues/999999/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_issue_detail_requires_login(client):
    issue = IssueFactory()

    response = client.get(f"/issues/{issue.number}/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_issue_detail_renders_issue_metadata(auth_client):
    milestone = MilestoneFactory(name="25.1", slug="25-1")
    issue = IssueFactory(
        title="Crash on startup",
        description="When you start it crashes.",
        assignee="claude-x",
        milestone=milestone,
    )

    response = auth_client.get(f"/issues/{issue.number}/")

    assert response.status_code == 200
    assert response.context["issue"] == issue
    body = response.content.decode()
    assert "Crash on startup" in body
    assert "When you start it crashes." in body
    assert "claude-x" in body
    assert "25.1" in body


@pytest.mark.django_db
def test_issue_detail_shows_blocked_reason_only_when_blocked(auth_client):
    issue = IssueFactory(
        status=Status.BLOCKED, blocked_reason="Waiting for upstream fix."
    )

    response = auth_client.get(f"/issues/{issue.number}/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Waiting for upstream fix." in body


@pytest.mark.django_db
def test_issue_detail_hides_blocked_reason_when_not_blocked(auth_client):
    issue = IssueFactory(status=Status.OPEN, blocked_reason="secret-hidden-reason")

    response = auth_client.get(f"/issues/{issue.number}/")

    assert response.status_code == 200
    # The dedicated "Blocked" panel is skipped when status != blocked.
    assert '<h2 class="spaced">Blocked</h2>' not in response.content.decode()


@pytest.mark.django_db
def test_issue_detail_lists_github_refs_and_comments(auth_client):
    issue = IssueFactory()
    ref = GithubIssueRefFactory(issue=issue, title="Upstream bug")
    comment = CommentFactory(issue=issue, body="checking now", author="claude-y")

    response = auth_client.get(f"/issues/{issue.number}/")

    assert list(response.context["github_refs"]) == [ref]
    assert list(response.context["comments"]) == [comment]
    body = response.content.decode()
    assert "Upstream bug" in body
    assert "checking now" in body
    assert "claude-y" in body


@pytest.mark.django_db
def test_issue_detail_merges_references_in_both_directions_without_duplicates(
    auth_client,
):
    main = IssueFactory(title="main")
    other = IssueFactory(title="other")
    third = IssueFactory(title="third")
    IssueReferenceFactory(from_issue=main, to_issue=other)
    IssueReferenceFactory(from_issue=third, to_issue=main)
    # A symmetric reference should still surface "other" only once if both
    # directions exist; the sidebar treats a link as one logical edge.
    IssueReferenceFactory(from_issue=other, to_issue=main)

    response = auth_client.get(f"/issues/{main.number}/")

    related = response.context["related_issues"]
    assert {i.pk for i in related} == {other.pk, third.pk}
    assert len(related) == 2


@pytest.mark.django_db
def test_issue_detail_renders_empty_collections(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/")

    assert response.status_code == 200
    assert response.context["github_refs"] == []
    assert response.context["comments"] == []
    assert response.context["related_issues"] == []
    body = response.content.decode()
    assert "No comments." in body
    assert "No description." in body
