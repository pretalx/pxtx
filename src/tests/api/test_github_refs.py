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
