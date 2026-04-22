"""htmx-driven interactions on the issue detail view: highlight toggle,
inline description edit, comment create/edit, and the in-priority reorder
button on the list view."""

import pytest

from pxtx.core.models import ActivityLog, Comment, Issue, Priority
from tests.factories import CommentFactory, IssueFactory

pytestmark = pytest.mark.integration


# ---- highlight toggle -------------------------------------------------------


@pytest.mark.django_db
def test_highlight_toggle_flips_the_flag(auth_client):
    issue = IssueFactory(is_highlighted=False)

    response = auth_client.post(f"/issues/{issue.number}/highlight/")

    issue.refresh_from_db()
    assert issue.is_highlighted is True
    assert response.status_code == 302
    assert response.url == f"/issues/{issue.number}/"


@pytest.mark.django_db
def test_highlight_toggle_htmx_returns_partial(auth_client):
    issue = IssueFactory(is_highlighted=False)

    response = auth_client.post(
        f"/issues/{issue.number}/highlight/", headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "★" in body
    assert "<nav" not in body


# ---- inline description edit ------------------------------------------------


@pytest.mark.django_db
def test_description_edit_get_returns_form(auth_client):
    issue = IssueFactory(description="original")

    response = auth_client.get(f"/issues/{issue.number}/description/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "<textarea" in body
    assert "original" in body


@pytest.mark.django_db
def test_description_edit_post_saves_and_returns_rendered_view(auth_client):
    issue = IssueFactory(description="before")

    response = auth_client.post(
        f"/issues/{issue.number}/description/", data={"description": "after **bold**"}
    )

    issue.refresh_from_db()
    assert issue.description == "after **bold**"
    assert response.status_code == 200
    assert "<strong>bold</strong>" in response.content.decode()


# ---- comment create ---------------------------------------------------------


@pytest.mark.django_db
def test_comment_create_saves_author_from_user(auth_client):
    from tests.factories import UserFactory

    user = UserFactory(username="rixx")
    auth_client.force_login(user)
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/comments/", data={"body": "a new comment"}
    )

    comment = Comment.objects.get(issue=issue)
    assert comment.author == "user/rixx"
    assert comment.body == "a new comment"
    assert response.status_code == 200


@pytest.mark.django_db
def test_comment_create_renders_updated_comments_section(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/comments/", data={"body": "hello world"}
    )

    body = response.content.decode()
    assert 'id="comments-section"' in body
    assert "hello world" in body


@pytest.mark.django_db
def test_comment_create_with_invalid_body_rerenders_with_errors(auth_client):
    issue = IssueFactory()

    response = auth_client.post(f"/issues/{issue.number}/comments/", data={"body": ""})

    assert response.status_code == 200
    assert Comment.objects.filter(issue=issue).count() == 0


# ---- comment edit -----------------------------------------------------------


@pytest.mark.django_db
def test_comment_edit_get_returns_form(auth_client):
    comment = CommentFactory(body="original body")

    response = auth_client.get(f"/comments/{comment.pk}/edit/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "original body" in body
    assert "<textarea" in body


@pytest.mark.django_db
def test_comment_edit_post_updates_body_and_marks_edited(auth_client):
    comment = CommentFactory(body="original")

    response = auth_client.post(
        f"/comments/{comment.pk}/edit/", data={"body": "updated"}
    )

    comment.refresh_from_db()
    assert comment.body == "updated"
    assert comment.edited_at is not None
    assert response.status_code == 200
    assert "updated" in response.content.decode()


@pytest.mark.django_db
def test_comment_edit_invalid_body_rerenders_form(auth_client):
    comment = CommentFactory(body="original")

    response = auth_client.post(f"/comments/{comment.pk}/edit/", data={"body": ""})

    comment.refresh_from_db()
    assert comment.body == "original"
    assert comment.edited_at is None
    assert response.status_code == 200
    body = response.content.decode()
    assert "<textarea" in body


# ---- reorder ---------------------------------------------------------------


@pytest.mark.django_db
def test_reorder_up_moves_issue_earlier(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0, title="a")
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1, title="b")
    c = IssueFactory(priority=Priority.WANT, order_in_priority=2, title="c")

    response = auth_client.post(
        f"/issues/{b.number}/reorder/", data={"direction": "up"}
    )

    a.refresh_from_db()
    b.refresh_from_db()
    c.refresh_from_db()
    assert (b.order_in_priority, a.order_in_priority, c.order_in_priority) == (0, 1, 2)
    assert response.status_code == 200


@pytest.mark.django_db
def test_reorder_down_at_end_is_noop(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)

    auth_client.post(f"/issues/{b.number}/reorder/", data={"direction": "down"})

    a.refresh_from_db()
    b.refresh_from_db()
    assert (a.order_in_priority, b.order_in_priority) == (0, 1)


@pytest.mark.django_db
def test_reorder_rejects_invalid_direction(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/reorder/", data={"direction": "sideways"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_reorder_does_not_emit_activity_log_entries(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)
    before = ActivityLog.objects.count()

    auth_client.post(f"/issues/{b.number}/reorder/", data={"direction": "up"})

    assert ActivityLog.objects.count() == before
    assert Issue.objects.filter(pk=a.pk, order_in_priority=1).exists()


@pytest.mark.django_db
def test_reorder_only_affects_same_priority_bucket(auth_client):
    want_a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    want_b = IssueFactory(priority=Priority.WANT, order_in_priority=1)
    should_a = IssueFactory(priority=Priority.SHOULD, order_in_priority=5)

    auth_client.post(f"/issues/{want_b.number}/reorder/", data={"direction": "up"})

    want_a.refresh_from_db()
    want_b.refresh_from_db()
    should_a.refresh_from_db()
    assert want_a.order_in_priority == 1
    assert want_b.order_in_priority == 0
    # Unrelated bucket is untouched even if it had gaps.
    assert should_a.order_in_priority == 5


# ---- issue detail context ---------------------------------------------------


@pytest.mark.django_db
def test_issue_detail_exposes_activity_log(auth_client):
    issue = IssueFactory()
    # The issue's own .create log entry should be included.

    response = auth_client.get(f"/issues/{issue.number}/")

    actions = {entry.action_type for entry in response.context["activity"]}
    assert "pxtx.issue.create" in actions
