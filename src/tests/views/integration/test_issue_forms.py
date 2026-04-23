import pytest

from pxtx.core.models import ActivityLog, Issue, Priority, Source, Status
from tests.factories import IssueFactory, MilestoneFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_create_form_requires_login(client):
    response = client.get("/issues/new/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_create_form_renders_with_sensible_defaults(auth_client):
    response = auth_client.get("/issues/new/")

    assert response.status_code == 200
    form = response.context["form"]
    assert form.initial["priority"] == Priority.KOENNTE
    assert form.initial["status"] == Status.OPEN
    assert form.initial["source"] == Source.MANUAL
    assert response.context["form_title"] == "New issue"
    assert response.context["blocked_reason_visible"] is False


@pytest.mark.django_db
def test_create_issue_succeeds_and_redirects_to_detail(auth_client):
    milestone = MilestoneFactory(slug="25-1")
    response = auth_client.post(
        "/issues/new/",
        data={
            "title": "new issue title",
            "description": "some description",
            "priority": Priority.WILL,
            "effort_minutes": 90,
            "status": Status.OPEN,
            "blocked_reason": "",
            "milestone": milestone.pk,
            "is_highlighted": "on",
            "source": Source.MANUAL,
        },
    )

    issue = Issue.objects.get(title="new issue title")
    assert response.status_code == 302
    assert response.url == f"/issues/{issue.number}/"
    assert issue.assignee == ""
    assert issue.is_highlighted is True
    assert issue.milestone == milestone


@pytest.mark.django_db
def test_create_form_has_no_assignee_field(auth_client):
    response = auth_client.get("/issues/new/")

    assert response.status_code == 200
    assert "assignee" not in response.context["form"].fields
    body = response.content.decode()
    assert 'name="assignee"' not in body


@pytest.mark.django_db
def test_create_ignores_posted_assignee(auth_client):
    auth_client.post(
        "/issues/new/",
        data={
            "title": "no assignee for you",
            "description": "",
            "priority": Priority.KOENNTE,
            "status": Status.OPEN,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "smuggled-in",
            "source": Source.MANUAL,
        },
    )

    issue = Issue.objects.get(title="no assignee for you")
    assert issue.assignee == ""


@pytest.mark.django_db
def test_create_issue_logs_activity_with_user_actor(auth_client):
    from tests.factories import UserFactory

    user = UserFactory(username="rixx")
    auth_client.force_login(user)

    auth_client.post(
        "/issues/new/",
        data={
            "title": "new one",
            "description": "",
            "priority": Priority.KOENNTE,
            "status": Status.OPEN,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "",
            "source": Source.MANUAL,
        },
    )

    issue = Issue.objects.get(title="new one")
    actors = {log.actor for log in ActivityLog.objects.filter(object_id=issue.pk)}
    assert actors == {"user/rixx"}


@pytest.mark.django_db
def test_create_form_blocked_status_requires_reason(auth_client):
    response = auth_client.post(
        "/issues/new/",
        data={
            "title": "blocked one",
            "description": "",
            "priority": Priority.KOENNTE,
            "status": Status.BLOCKED,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "",
            "source": Source.MANUAL,
        },
    )

    assert response.status_code == 200
    form = response.context["form"]
    assert "blocked_reason" in form.errors
    assert Issue.objects.filter(title="blocked one").exists() is False
    # The blocked-reason field is now visible in the re-rendered form.
    assert response.context["blocked_reason_visible"] is True


@pytest.mark.django_db
def test_create_form_keeps_reason_when_status_is_blocked(auth_client):
    response = auth_client.post(
        "/issues/new/",
        data={
            "title": "truly blocked",
            "description": "",
            "priority": Priority.KOENNTE,
            "status": Status.BLOCKED,
            "blocked_reason": "waiting for upstream fix",
            "milestone": "",
            "assignee": "",
            "source": Source.MANUAL,
        },
    )

    issue = Issue.objects.get(title="truly blocked")
    assert issue.blocked_reason == "waiting for upstream fix"
    assert response.status_code == 302


@pytest.mark.django_db
def test_create_form_blocks_reason_cleared_when_status_not_blocked(auth_client):
    auth_client.post(
        "/issues/new/",
        data={
            "title": "not blocked",
            "description": "",
            "priority": Priority.KOENNTE,
            "status": Status.OPEN,
            "blocked_reason": "stray reason",
            "milestone": "",
            "assignee": "",
            "source": Source.MANUAL,
        },
    )

    issue = Issue.objects.get(title="not blocked")
    assert issue.blocked_reason == ""


@pytest.mark.django_db
def test_edit_form_prefills_from_existing_issue(auth_client):
    issue = IssueFactory(title="original title", assignee="ex-owner")

    response = auth_client.get(f"/issues/{issue.number}/edit/")

    assert response.status_code == 200
    assert response.context["form"].instance == issue
    assert response.context["form_title"] == f"Edit {issue.slug}"


@pytest.mark.django_db
def test_edit_form_saves_changes_and_redirects(auth_client):
    issue = IssueFactory(title="before", assignee="")

    response = auth_client.post(
        f"/issues/{issue.number}/edit/",
        data={
            "title": "after",
            "description": "",
            "priority": issue.priority,
            "status": issue.status,
            "blocked_reason": "",
            "milestone": "",
            "assignee": "new-owner",
            "source": issue.source,
        },
    )

    assert response.status_code == 302
    assert response.url == f"/issues/{issue.number}/"
    issue.refresh_from_db()
    assert issue.title == "after"
    assert issue.assignee == "new-owner"


@pytest.mark.django_db
def test_edit_form_with_blocked_status_shows_reason_field(auth_client):
    issue = IssueFactory(status=Status.BLOCKED, blocked_reason="waiting")

    response = auth_client.get(f"/issues/{issue.number}/edit/")

    assert response.context["blocked_reason_visible"] is True


@pytest.mark.django_db
def test_blocked_reason_field_visibility_depends_on_status(auth_client):
    shown = auth_client.get("/issues/blocked-reason/?status=blocked")
    hidden = auth_client.get("/issues/blocked-reason/?status=open")

    assert "hidden" not in shown.content.decode().split("form-field")[1].split(">")[0]
    assert "hidden" in hidden.content.decode().split("form-field")[1].split(">")[0]


@pytest.mark.django_db
def test_edit_form_effort_select_has_enhanced_markers(auth_client):
    """The edit form renders effort through ``EnhancedSelect`` — the same
    widget the modal form and the inline-editable table cell use. The JS in
    ``choices-init.js`` keys off ``class="enhanced"`` plus
    ``data-badge-type`` to apply the badge styling and the textContent-based
    label re-seed that fixes options like ``<1h`` / ``>1d``. Pin the contract
    here so a widget regression fails this test before it reaches the UI."""
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/edit/")

    body = response.content.decode()
    import re

    match = re.search(r'<select name="effort_minutes"[^>]*>', body)
    assert match, "effort_minutes select not found on edit form"
    tag = match.group(0)
    assert 'class="enhanced"' in tag
    assert 'data-badge-type="effort"' in tag
    # The literal entity-escaped option labels are what Choices.js then
    # re-seeds from textContent on the client. If Django stops escaping we
    # want to know — the JS fix hinges on this shape.
    assert "&lt;1h" in body
    assert "&gt;1d" in body
