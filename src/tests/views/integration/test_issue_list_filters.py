import pytest

from pxtx.core.models import Priority, Source, Status
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
def test_source_filter(auth_client):
    gh = IssueFactory(source=Source.GITHUB, status=Status.OPEN)
    IssueFactory(source=Source.MANUAL, status=Status.OPEN)

    response = auth_client.get("/issues/?source=github")

    assert {i.pk for i in response.context["issues"]} == {gh.pk}


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
    ("sort", "first_field"),
    (
        ("priority", "priority"),
        ("updated", "-updated_at"),
        ("created", "-created_at"),
        ("milestone", "milestone__name"),
        ("nonsense", "priority"),
    ),
)
def test_sort_option_applies_expected_order(auth_client, sort, first_field):
    response = auth_client.get(f"/issues/?sort={sort}")

    assert response.context["issues"].query.order_by[0] == first_field


@pytest.mark.django_db
def test_can_reorder_only_when_sorting_by_priority(auth_client):
    response = auth_client.get("/issues/")
    assert response.context["can_reorder"] is True

    response = auth_client.get("/issues/?sort=updated")
    assert response.context["can_reorder"] is False


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
