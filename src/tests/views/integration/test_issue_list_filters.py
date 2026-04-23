import pytest

from pxtx.core.models import Priority, Status
from tests.factories import IssueFactory, MilestoneFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_default_statuses_include_active_work(auth_client):
    want_open = IssueFactory(status=Status.OPEN, title="open-one")
    want_wip = IssueFactory(status=Status.WIP, title="wip-one")
    IssueFactory(status=Status.COMPLETED, title="done-one")
    IssueFactory(status=Status.WONTFIX, title="skipped-one")

    response = auth_client.get("/issues/")

    assert {i.pk for i in response.context["issues"]} == {want_open.pk, want_wip.pk}


@pytest.mark.django_db
def test_filter_by_status_replaces_default(auth_client):
    completed = IssueFactory(status=Status.COMPLETED)
    IssueFactory(status=Status.OPEN)

    response = auth_client.get("/issues/?status=completed")

    assert {i.pk for i in response.context["issues"]} == {completed.pk}


@pytest.mark.django_db
def test_empty_status_param_returns_nothing(auth_client):
    """An explicit empty ``status=`` widget value means the user cleared the
    selection — we show zero issues rather than falling back to the default."""
    IssueFactory(status=Status.OPEN)

    response = auth_client.get("/issues/?status=")

    assert list(response.context["issues"]) == []


@pytest.mark.django_db
def test_priority_filter_multi(auth_client):
    want = IssueFactory(priority=Priority.WANT, status=Status.OPEN)
    should = IssueFactory(priority=Priority.SHOULD, status=Status.OPEN)
    IssueFactory(priority=Priority.LOL, status=Status.OPEN)

    response = auth_client.get("/issues/?priority=1&priority=2")

    assert {i.pk for i in response.context["issues"]} == {want.pk, should.pk}


@pytest.mark.django_db
def test_milestone_filter_by_slug(auth_client):
    milestone = MilestoneFactory(slug="25-1")
    own = IssueFactory(milestone=milestone, status=Status.OPEN)
    IssueFactory(status=Status.OPEN)

    response = auth_client.get("/issues/?milestone=25-1")

    assert {i.pk for i in response.context["issues"]} == {own.pk}


@pytest.mark.django_db
def test_milestone_filter_null_finds_unassigned(auth_client):
    milestone = MilestoneFactory()
    IssueFactory(milestone=milestone, status=Status.OPEN)
    orphan = IssueFactory(status=Status.OPEN)

    response = auth_client.get("/issues/?milestone=null")

    assert {i.pk for i in response.context["issues"]} == {orphan.pk}


@pytest.mark.django_db
def test_assignee_filter_is_icontains(auth_client):
    mine = IssueFactory(assignee="claude/feature-x", status=Status.OPEN)
    IssueFactory(assignee="tobias", status=Status.OPEN)

    response = auth_client.get("/issues/?assignee=claude")

    assert {i.pk for i in response.context["issues"]} == {mine.pk}


@pytest.mark.django_db
def test_highlighted_only_toggle(auth_client):
    starred = IssueFactory(is_highlighted=True, status=Status.OPEN)
    IssueFactory(status=Status.OPEN)

    response = auth_client.get("/issues/?is_highlighted=on")

    assert {i.pk for i in response.context["issues"]} == {starred.pk}


@pytest.mark.django_db
def test_search_matches_title_description_and_comments(auth_client):
    from tests.factories import CommentFactory

    by_title = IssueFactory(title="needle here", status=Status.OPEN)
    by_desc = IssueFactory(description="contains needle", status=Status.OPEN)
    by_comment = IssueFactory(title="no match", status=Status.OPEN)
    CommentFactory(issue=by_comment, body="found needle in comments")
    IssueFactory(title="irrelevant", status=Status.OPEN)

    response = auth_client.get("/issues/?search=needle")

    assert {i.pk for i in response.context["issues"]} == {
        by_title.pk,
        by_desc.pk,
        by_comment.pk,
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("querystring", "first_field"),
    (
        ("sort=priority", "priority"),
        ("sort=priority&dir=desc", "-priority"),
        ("sort=updated", "-updated_at"),
        ("sort=updated&dir=asc", "updated_at"),
        ("sort=number", "-number"),
        ("sort=number&dir=asc", "number"),
        ("sort=title", "title"),
        ("sort=title&dir=desc", "-title"),
        ("sort=status", "status"),
        ("sort=effort", "effort_minutes"),
        ("sort=assignee", "assignee"),
        ("sort=milestone", "milestone__name"),
        # Unknown sort keys fall back to the default priority order.
        ("sort=nonsense", "priority"),
        # Unknown direction falls back to the column's default direction.
        ("sort=updated&dir=sideways", "-updated_at"),
    ),
)
def test_sort_option_applies_expected_order(auth_client, querystring, first_field):
    response = auth_client.get(f"/issues/?{querystring}")

    assert response.context["issues"].query.order_by[0] == first_field


@pytest.mark.django_db
def test_can_reorder_only_when_sorting_by_priority_ascending(auth_client):
    response = auth_client.get("/issues/")
    assert response.context["can_reorder"] is True

    response = auth_client.get("/issues/?sort=updated")
    assert response.context["can_reorder"] is False

    # Reordering only makes sense for the default priority+ascending state —
    # a descending priority sort would fight the bucketed ``order_in_priority``.
    response = auth_client.get("/issues/?sort=priority&dir=desc")
    assert response.context["can_reorder"] is False


@pytest.mark.django_db
def test_sort_headers_track_active_column_and_direction(auth_client):
    response = auth_client.get("/issues/?sort=title&dir=desc")

    headers = response.context["sort_headers"]
    assert set(headers) == {
        "number",
        "title",
        "status",
        "priority",
        "effort",
        "milestone",
        "updated",
    }
    assert headers["title"]["active"] is True
    assert headers["title"]["direction"] == "desc"
    # Clicking the active header toggles to the opposite direction.
    assert "dir=asc" in headers["title"]["querystring"]
    # An inactive header links to its own default direction.
    assert headers["updated"]["active"] is False
    assert "sort=updated" in headers["updated"]["querystring"]
    assert "dir=desc" in headers["updated"]["querystring"]


@pytest.mark.django_db
def test_sort_header_querystring_preserves_filters(auth_client):
    response = auth_client.get("/issues/?status=open&assignee=claude&sort=updated")

    querystring = response.context["sort_headers"]["title"]["querystring"]
    assert "status=open" in querystring
    assert "assignee=claude" in querystring
    assert "sort=title" in querystring


@pytest.mark.django_db
def test_quick_filters_only_shown_when_matching_issues_exist(auth_client):
    response = auth_client.get("/issues/")
    assert response.context["quick_filters"] == []

    IssueFactory(is_highlighted=True, status=Status.OPEN)
    IssueFactory(status=Status.WIP)
    IssueFactory(status=Status.BLOCKED, blocked_reason="x")
    IssueFactory(status=Status.DRAFT)
    IssueFactory(priority=Priority.WANT, status=Status.OPEN)

    response = auth_client.get("/issues/")
    labels = {qf["label"] for qf in response.context["quick_filters"]}
    assert labels == {"★ highlighted", "🔥 want", "🔧 wip", "🚧 blocked", "📥 draft"}
    # Nothing is applied yet, so no chip is marked active.
    assert all(qf["active"] is False for qf in response.context["quick_filters"])


@pytest.mark.django_db
def test_quick_filter_active_when_its_params_match_current_request(auth_client):
    IssueFactory(status=Status.WIP)
    IssueFactory(status=Status.BLOCKED, blocked_reason="x")

    response = auth_client.get("/issues/?status=wip")
    active = {qf["label"]: qf["active"] for qf in response.context["quick_filters"]}

    assert active["🔧 wip"] is True
    assert active["🚧 blocked"] is False


@pytest.mark.django_db
def test_htmx_request_returns_table_partial(auth_client):
    IssueFactory(status=Status.OPEN, title="visible-row")

    response = auth_client.get("/issues/", headers={"HX-Request": "true"})

    assert response.status_code == 200
    body = response.content.decode()
    # Partial does not include the page chrome.
    assert "<nav" not in body
    assert "visible-row" in body


@pytest.mark.django_db
def test_full_request_includes_filter_form(auth_client):
    response = auth_client.get("/issues/")

    body = response.content.decode()
    assert 'class="issue-filters"' in body
    assert 'name="search"' in body
