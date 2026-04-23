"""htmx-driven interactions on the issue detail view: highlight toggle,
inline description edit, comment create/edit, and the in-priority drag-
and-drop reorder on the list view."""

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
def test_reorder_moves_issue_to_given_index(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0, title="a")
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1, title="b")
    c = IssueFactory(priority=Priority.WANT, order_in_priority=2, title="c")

    response = auth_client.post(f"/issues/{b.number}/reorder/", data={"index": "0"})

    a.refresh_from_db()
    b.refresh_from_db()
    c.refresh_from_db()
    assert (b.order_in_priority, a.order_in_priority, c.order_in_priority) == (0, 1, 2)
    assert response.status_code == 200


@pytest.mark.django_db
def test_reorder_clamps_index_past_the_end(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)

    auth_client.post(f"/issues/{a.number}/reorder/", data={"index": "99"})

    a.refresh_from_db()
    b.refresh_from_db()
    assert (b.order_in_priority, a.order_in_priority) == (0, 1)


@pytest.mark.django_db
def test_reorder_clamps_negative_index_to_start(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)

    auth_client.post(f"/issues/{b.number}/reorder/", data={"index": "-5"})

    a.refresh_from_db()
    b.refresh_from_db()
    assert (b.order_in_priority, a.order_in_priority) == (0, 1)


@pytest.mark.django_db
def test_reorder_requires_index(auth_client):
    issue = IssueFactory()

    response = auth_client.post(f"/issues/{issue.number}/reorder/", data={})

    assert response.status_code == 400


@pytest.mark.django_db
def test_reorder_rejects_non_integer_index(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/reorder/", data={"index": "nope"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_reorder_to_current_position_is_a_noop(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)

    response = auth_client.post(f"/issues/{a.number}/reorder/", data={"index": "0"})

    a.refresh_from_db()
    b.refresh_from_db()
    assert (a.order_in_priority, b.order_in_priority) == (0, 1)
    assert response.status_code == 200


@pytest.mark.django_db
def test_reorder_does_not_emit_activity_log_entries(auth_client):
    a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    b = IssueFactory(priority=Priority.WANT, order_in_priority=1)
    before = ActivityLog.objects.count()

    auth_client.post(f"/issues/{b.number}/reorder/", data={"index": "0"})

    assert ActivityLog.objects.count() == before
    assert Issue.objects.filter(pk=a.pk, order_in_priority=1).exists()


@pytest.mark.django_db
def test_reorder_only_affects_same_priority_bucket(auth_client):
    want_a = IssueFactory(priority=Priority.WANT, order_in_priority=0)
    want_b = IssueFactory(priority=Priority.WANT, order_in_priority=1)
    should_a = IssueFactory(priority=Priority.SHOULD, order_in_priority=5)

    auth_client.post(f"/issues/{want_b.number}/reorder/", data={"index": "0"})

    want_a.refresh_from_db()
    want_b.refresh_from_db()
    should_a.refresh_from_db()
    assert want_a.order_in_priority == 1
    assert want_b.order_in_priority == 0
    # Unrelated bucket is untouched even if it had gaps.
    assert should_a.order_in_priority == 5


@pytest.mark.django_db
def test_reorder_places_highlighted_issues_ahead_of_non_highlighted(auth_client):
    """Siblings are ordered the way the list displays them, so dragging a
    non-highlighted issue to ``index=0`` lands it after any highlighted
    issues in the bucket (which display first)."""
    starred = IssueFactory(
        priority=Priority.WANT, is_highlighted=True, order_in_priority=0
    )
    plain_a = IssueFactory(priority=Priority.WANT, order_in_priority=1)
    plain_b = IssueFactory(priority=Priority.WANT, order_in_priority=2)

    auth_client.post(f"/issues/{plain_b.number}/reorder/", data={"index": "0"})

    starred.refresh_from_db()
    plain_a.refresh_from_db()
    plain_b.refresh_from_db()
    # Starred stays first, the dragged issue slots in next, plain_a last.
    assert starred.order_in_priority == 0
    assert plain_b.order_in_priority == 1
    assert plain_a.order_in_priority == 2


# ---- inline cell edit -------------------------------------------------------


@pytest.mark.django_db
def test_inline_cell_get_returns_select_with_current_selected(auth_client):
    issue = IssueFactory(priority=Priority.WANT)

    response = auth_client.get(f"/issues/{issue.number}/cell/priority/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "<select" in body
    # The current value is rendered as selected so the user sees their state.
    assert '<option value="1" selected>' in body


@pytest.mark.django_db
def test_inline_cell_get_rejects_unknown_field(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/cell/nope/")

    assert response.status_code == 400


@pytest.mark.django_db
def test_inline_cell_post_updates_priority_and_logs(auth_client):
    from pxtx.core.models import ActivityLog

    issue = IssueFactory(priority=Priority.COULD)
    before = ActivityLog.objects.count()

    response = auth_client.post(
        f"/issues/{issue.number}/cell/priority/", data={"value": "1"}
    )

    issue.refresh_from_db()
    assert issue.priority == Priority.WANT
    assert response.status_code == 200
    assert 'class="prio prio-1"' in response.content.decode()
    assert ActivityLog.objects.count() == before + 1


@pytest.mark.django_db
def test_inline_cell_post_updates_status_emits_status_log(auth_client):
    from pxtx.core.models import ActivityLog, Status

    issue = IssueFactory(status=Status.OPEN)

    auth_client.post(f"/issues/{issue.number}/cell/status/", data={"value": "wip"})

    issue.refresh_from_db()
    assert issue.status == Status.WIP.value
    assert ActivityLog.objects.filter(action_type="pxtx.issue.status.wip").exists()


@pytest.mark.django_db
def test_inline_cell_post_sets_effort_to_null(auth_client):
    from pxtx.core.models import Effort

    issue = IssueFactory(effort_minutes=Effort.SMALL)

    response = auth_client.post(
        f"/issues/{issue.number}/cell/effort/", data={"value": ""}
    )

    issue.refresh_from_db()
    assert issue.effort_minutes is None
    assert response.status_code == 200
    # Blank effort renders as an em-dash, not a badge.
    body = response.content.decode()
    assert "—" in body
    assert "badge effort-" not in body


@pytest.mark.django_db
def test_inline_cell_post_rejects_value_not_in_choices(auth_client):
    issue = IssueFactory(priority=Priority.COULD)

    response = auth_client.post(
        f"/issues/{issue.number}/cell/priority/", data={"value": "42"}
    )

    issue.refresh_from_db()
    assert issue.priority == Priority.COULD
    assert response.status_code == 400


@pytest.mark.django_db
def test_inline_cell_post_rejects_unknown_field(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/cell/nope/", data={"value": "1"}
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_inline_cell_post_blocked_without_reason_redirects_to_edit(auth_client):
    """Going blocked without a reason is the same guard the kanban enforces —
    the user is redirected to the edit form (via HX-Redirect) instead of
    silently persisting an empty ``blocked_reason``."""
    from pxtx.core.models import Status

    issue = IssueFactory(status=Status.OPEN, blocked_reason="")

    response = auth_client.post(
        f"/issues/{issue.number}/cell/status/", data={"value": "blocked"}
    )

    issue.refresh_from_db()
    assert issue.status == Status.OPEN.value
    assert response.status_code == 204
    assert response["HX-Redirect"] == f"/issues/{issue.number}/edit/"


@pytest.mark.django_db
def test_inline_cell_post_blocked_with_existing_reason_is_saved(auth_client):
    """If the issue already has a reason, setting status=blocked inline is
    allowed (same semantics as the kanban column drop)."""
    from pxtx.core.models import Status

    issue = IssueFactory(status=Status.OPEN, blocked_reason="waiting on review")

    response = auth_client.post(
        f"/issues/{issue.number}/cell/status/", data={"value": "blocked"}
    )

    issue.refresh_from_db()
    assert issue.status == Status.BLOCKED.value
    assert response.status_code == 200


@pytest.mark.django_db
def test_inline_cell_reordering_within_blocked_does_not_require_new_reason(auth_client):
    """A blocked issue that already has a reason can be re-saved as blocked
    inline (a no-op, but it must not trip the blocked-without-reason guard)."""
    from pxtx.core.models import Status

    issue = IssueFactory(status=Status.BLOCKED, blocked_reason="")
    # ``blocked_reason`` was emptied post-creation; the guard must only fire
    # when transitioning *into* blocked, not when the issue is already there.

    response = auth_client.post(
        f"/issues/{issue.number}/cell/status/", data={"value": "blocked"}
    )

    issue.refresh_from_db()
    assert issue.status == Status.BLOCKED.value
    assert response.status_code == 200


# ---- issue detail context ---------------------------------------------------


@pytest.mark.django_db
def test_issue_detail_exposes_activity_log(auth_client):
    issue = IssueFactory()
    # The issue's own .create log entry should be included.

    response = auth_client.get(f"/issues/{issue.number}/")

    actions = {entry.action_type for entry in response.context["activity"]}
    assert "pxtx.issue.create" in actions


# ---- modal edit -------------------------------------------------------------


@pytest.mark.django_db
def test_modal_edit_get_returns_form_fragment_without_chrome(auth_client):
    issue = IssueFactory(title="modal me")

    response = auth_client.get(f"/issues/{issue.number}/modal-edit/")

    assert response.status_code == 200
    body = response.content.decode()
    # Fragment: no site nav, but a form with issue slug and the title value.
    assert "<nav" not in body
    assert issue.slug in body
    assert 'value="modal me"' in body
    assert 'hx-post="/issues/' in body


@pytest.mark.django_db
def test_modal_edit_renders_title_and_description_in_read_only_view(auth_client):
    """The title and description sections start in view mode — the form input
    is in the DOM (for submission) but the rendered view is what the user
    sees first. Markdown in the description is rendered to HTML."""
    issue = IssueFactory(title="shiny title", description="hello **world**")

    response = auth_client.get(f"/issues/{issue.number}/modal-edit/")

    body = response.content.decode()
    # Title is rendered as a heading in the view, not just as an input value.
    assert ">shiny title</h2>" in body
    # Description is rendered from markdown, so the ** is processed.
    assert "<strong>world</strong>" in body
    # The view containers are marked up for the click-to-edit JS to find.
    assert "inline-edit-title" in body
    assert "inline-edit-description" in body
    # Neither section starts in editing mode for a freshly-loaded issue.
    assert "inline-edit-title editing" not in body
    assert "inline-edit-description editing" not in body


@pytest.mark.django_db
def test_modal_edit_placeholder_when_description_is_empty(auth_client):
    issue = IssueFactory(description="")

    response = auth_client.get(f"/issues/{issue.number}/modal-edit/")

    body = response.content.decode()
    assert "No description. Click to add one." in body


@pytest.mark.django_db
def test_modal_edit_opens_title_editing_on_validation_error(auth_client):
    """Title is required. When the server re-renders the fragment with a
    title error, the title wrapper must carry the ``editing`` class so the
    user lands directly on the input without having to click first."""
    issue = IssueFactory(title="present", description="desc")

    response = auth_client.post(
        f"/issues/{issue.number}/modal-edit/",
        data={
            "title": "",  # blank → required error on title
            "description": "desc",
            "priority": issue.priority,
            "status": issue.status,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "",
            "source": issue.source,
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "inline-edit-title editing" in body
    # Sanity: the error message is visible too.
    assert "This field is required" in body


@pytest.mark.django_db
def test_modal_edit_get_renders_blocked_reason_field_when_blocked(auth_client):
    from pxtx.core.models import Status

    issue = IssueFactory(status=Status.BLOCKED, blocked_reason="waiting")

    response = auth_client.get(f"/issues/{issue.number}/modal-edit/")

    assert response.status_code == 200
    body = response.content.decode()
    # The wrap container should not carry the hidden class for a blocked issue.
    wrap = body.split('id="blocked-reason-wrap"')[1].split(">")[0]
    assert "hidden" not in wrap


@pytest.mark.django_db
def test_modal_edit_post_saves_and_signals_close(auth_client):
    issue = IssueFactory(title="before", assignee="")

    response = auth_client.post(
        f"/issues/{issue.number}/modal-edit/",
        data={
            "title": "after",
            "description": "",
            "priority": issue.priority,
            "status": issue.status,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "modal-owner",
            "source": issue.source,
        },
    )

    assert response.status_code == 204
    # Client listens for this event to close the dialog + refresh the list.
    assert response["HX-Trigger"] == "pxtx:issue-saved"
    issue.refresh_from_db()
    assert issue.title == "after"
    assert issue.assignee == "modal-owner"


@pytest.mark.django_db
def test_modal_edit_post_logs_activity_with_user_actor(auth_client):
    from tests.factories import UserFactory

    user = UserFactory(username="rixx")
    auth_client.force_login(user)
    issue = IssueFactory(title="before")
    before = ActivityLog.objects.filter(object_id=issue.pk).count()

    auth_client.post(
        f"/issues/{issue.number}/modal-edit/",
        data={
            "title": "after",
            "description": "",
            "priority": issue.priority,
            "status": issue.status,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "",
            "source": issue.source,
        },
    )

    new_logs = ActivityLog.objects.filter(object_id=issue.pk).order_by("-timestamp")
    assert new_logs.count() > before
    assert new_logs.first().actor == "user/rixx"


@pytest.mark.django_db
def test_modal_edit_post_with_errors_rerenders_form_without_trigger(auth_client):
    from pxtx.core.models import Status

    issue = IssueFactory(status=Status.OPEN)

    response = auth_client.post(
        f"/issues/{issue.number}/modal-edit/",
        data={
            "title": "still here",
            "description": "",
            "priority": issue.priority,
            "status": Status.BLOCKED,  # without a reason — should fail.
            "blocked_reason": "",
            "milestone": "",
            "assignee": "",
            "source": issue.source,
        },
    )

    assert response.status_code == 200
    assert "HX-Trigger" not in response
    issue.refresh_from_db()
    assert issue.status == Status.OPEN.value
    body = response.content.decode()
    assert "A reason is required" in body


@pytest.mark.django_db
def test_modal_edit_requires_login(client):
    issue = IssueFactory()

    response = client.get(f"/issues/{issue.number}/modal-edit/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_issue_list_rows_link_to_modal_edit(auth_client):
    issue = IssueFactory()

    response = auth_client.get("/issues/")

    body = response.content.decode()
    assert f'hx-get="/issues/{issue.number}/modal-edit/"' in body
    assert 'hx-target="#issue-modal"' in body


@pytest.mark.django_db
def test_kanban_cards_link_to_modal_edit(auth_client):
    from tests.factories import MilestoneFactory

    milestone = MilestoneFactory(slug="rel-1")
    issue = IssueFactory(milestone=milestone)

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    body = response.content.decode()
    assert f'hx-get="/issues/{issue.number}/modal-edit/"' in body
    assert 'hx-target="#issue-modal"' in body
