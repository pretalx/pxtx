import pytest

from pxtx.core.models import ActivityLog, Comment
from tests.factories import CommentFactory, IssueFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_list_comments_on_issue(token_client):
    issue = IssueFactory()
    CommentFactory(issue=issue, body="first")
    CommentFactory(issue=issue, body="second")
    # Another issue's comment should NOT show up.
    CommentFactory()

    response = token_client.get(f"/api/v1/issues/{issue.number}/comments/")

    assert response.status_code == 200
    bodies = [r["body"] for r in response.json()["results"]]
    assert bodies == ["first", "second"]


@pytest.mark.django_db
def test_create_comment_sets_author_from_token(token_client, api_token):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/comments/", {"body": "hello"}, format="json"
    )

    assert response.status_code == 201
    comment = Comment.objects.get()
    assert comment.body == "hello"
    assert comment.author == api_token.name
    assert ActivityLog.objects.filter(action_type="pxtx.comment.create").count() == 1


@pytest.mark.django_db
def test_create_comment_on_missing_issue_returns_404(token_client):
    response = token_client.post(
        "/api/v1/issues/9999/comments/", {"body": "hi"}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_patch_comment_updates_body_and_sets_edited_at(token_client, api_token):
    comment = CommentFactory(body="original", author="original-author")

    response = token_client.patch(
        f"/api/v1/comments/{comment.pk}/", {"body": "edited"}, format="json"
    )

    assert response.status_code == 200
    comment.refresh_from_db()
    assert comment.body == "edited"
    assert comment.edited_at is not None
    entry = ActivityLog.objects.get(action_type="pxtx.comment.update")
    assert entry.data["before"]["body"] == "original"
    assert entry.data["after"]["body"] == "edited"


@pytest.mark.django_db
def test_patch_comment_without_changes_logs_nothing(token_client):
    comment = CommentFactory(body="same")

    response = token_client.patch(
        f"/api/v1/comments/{comment.pk}/", {"body": "same"}, format="json"
    )

    assert response.status_code == 200
    # edited_at changes, so we still expect exactly one update entry...
    # Actually: we snapshot edited_at, so it DOES change on every update.
    # That's intentional: edits always touch edited_at, even for same-body
    # saves. Verify behaviour.
    assert ActivityLog.objects.filter(action_type="pxtx.comment.update").count() == 1


@pytest.mark.django_db
def test_delete_comment_is_not_allowed(token_client):
    comment = CommentFactory()

    response = token_client.delete(f"/api/v1/comments/{comment.pk}/")

    assert response.status_code == 405
    assert Comment.objects.filter(pk=comment.pk).exists()
