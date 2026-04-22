import pytest

from pxtx.core.models import GithubRef
from tests.factories import GithubIssueRefFactory, IssueFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_create_issue_github_ref(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "issue", "repo": "pretalx/pretalx", "number": 42},
        format="json",
    )

    assert response.status_code == 201
    ref = GithubRef.objects.get()
    assert ref.issue == issue
    assert ref.number == 42


@pytest.mark.django_db
def test_create_commit_ref_requires_sha(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "commit", "repo": "pretalx/pretalx"},
        format="json",
    )

    assert response.status_code == 400
    assert "sha" in response.json()


@pytest.mark.django_db
def test_create_issue_ref_requires_number(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "issue", "repo": "pretalx/pretalx"},
        format="json",
    )

    assert response.status_code == 400
    assert "number" in response.json()


@pytest.mark.django_db
def test_create_ref_for_missing_issue_returns_404(token_client):
    response = token_client.post(
        "/api/v1/issues/9999/github-refs/",
        {"kind": "issue", "repo": "pretalx/pretalx", "number": 42},
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_create_duplicate_pr_ref_returns_existing_with_200(token_client):
    """Re-posting the same PR ref must not duplicate — agents link PRs
    repeatedly as they push commits, and the API should absorb that."""
    issue = IssueFactory()
    first = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "pr", "repo": "pretalx/pretalx", "number": 77},
        format="json",
    )
    assert first.status_code == 201

    second = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "pr", "repo": "pretalx/pretalx", "number": 77},
        format="json",
    )

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert GithubRef.objects.filter(issue=issue).count() == 1


@pytest.mark.django_db
def test_create_duplicate_commit_ref_dedupes_on_sha(token_client):
    issue = IssueFactory()
    payload = {"kind": "commit", "repo": "pretalx/pretalx", "sha": "a" * 40}
    first = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/", payload, format="json"
    )
    assert first.status_code == 201

    second = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/", payload, format="json"
    )

    assert second.status_code == 200
    assert GithubRef.objects.filter(issue=issue).count() == 1


@pytest.mark.django_db
def test_same_pr_number_different_repo_is_not_duplicate(token_client):
    """Dedupe is scoped to (kind, repo, number). Same PR number in a
    different repo is a different ref."""
    issue = IssueFactory()
    token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "pr", "repo": "pretalx/pretalx", "number": 77},
        format="json",
    )

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/github-refs/",
        {"kind": "pr", "repo": "pretalx/pretalx-plugin", "number": 77},
        format="json",
    )

    assert response.status_code == 201
    assert GithubRef.objects.filter(issue=issue).count() == 2


@pytest.mark.django_db
def test_delete_github_ref(token_client):
    issue = IssueFactory()
    ref = GithubIssueRefFactory(issue=issue)

    response = token_client.delete(
        f"/api/v1/issues/{issue.number}/github-refs/{ref.pk}/"
    )

    assert response.status_code == 204
    assert GithubRef.objects.count() == 0


@pytest.mark.django_db
def test_delete_github_ref_scoped_to_issue(token_client):
    """Deleting via /issues/<other>/github-refs/<id>/ should 404 when
    the ref does not belong to that issue."""
    issue_a = IssueFactory()
    issue_b = IssueFactory()
    ref_for_a = GithubIssueRefFactory(issue=issue_a)

    response = token_client.delete(
        f"/api/v1/issues/{issue_b.number}/github-refs/{ref_for_a.pk}/"
    )

    assert response.status_code == 404
    assert GithubRef.objects.filter(pk=ref_for_a.pk).exists()
