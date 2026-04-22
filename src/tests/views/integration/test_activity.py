import datetime as dt

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from freezegun import freeze_time

from pxtx.core.models import ActivityLog, Issue, Status
from pxtx.core.views.activity import HEATMAP_WEEKS
from tests.factories import CommentFactory, IssueFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_activity_requires_login(client):
    response = client.get("/activity/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_activity_renders_empty_state(auth_client):
    response = auth_client.get("/activity/")

    assert response.status_code == 200
    assert response.context["entries"] == []
    assert "No activity matches these filters." in response.content.decode()


@pytest.mark.django_db
def test_activity_lists_entries_newest_first(auth_client):
    first = IssueFactory(title="first")
    second = IssueFactory(title="second")
    # Force a distinct timestamp on the older entry so ordering is unambiguous.
    ActivityLog.objects.filter(object_id=first.pk).update(
        timestamp=timezone.now() - dt.timedelta(hours=1)
    )

    response = auth_client.get("/activity/")

    assert response.status_code == 200
    entries = response.context["entries"]
    assert [e.object_id for e in entries] == [second.pk, first.pk]
    body = response.content.decode()
    assert f"PX-{second.number}" in body
    assert "second" in body


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", (1, 3))
def test_activity_list_query_count_is_constant(
    auth_client, django_assert_num_queries, item_count
):
    for _ in range(item_count):
        issue = IssueFactory()
        CommentFactory(issue=issue)

    # Query count should not scale with the number of log entries — content
    # types and targets are bulk-resolved. Baseline covers session auth,
    # paginator count, list fetch, issue bulk, comment bulk, and heatmap
    # aggregates.
    with django_assert_num_queries(8):
        response = auth_client.get("/activity/")

    assert response.status_code == 200
    assert len(response.context["entries"]) >= item_count


@pytest.mark.django_db
def test_activity_filters_by_actor(auth_client):
    alice_issue = IssueFactory()
    alice_issue.title = "alice-edit"
    alice_issue.save(actor="alice")
    bob_issue = IssueFactory()
    bob_issue.title = "bob-edit"
    bob_issue.save(actor="bob")

    response = auth_client.get("/activity/?actor=alice")

    actors = {e.actor for e in response.context["entries"]}
    assert actors == {"alice"}


@pytest.mark.django_db
def test_activity_filters_by_action_type_substring(auth_client):
    issue = IssueFactory()
    issue.status = Status.COMPLETED
    issue.save(actor="tester")

    response = auth_client.get("/activity/?action_type=status.completed")

    types = {e.action_type for e in response.context["entries"]}
    assert types == {"pxtx.issue.status.completed"}


@pytest.mark.django_db
def test_activity_filters_by_content_type(auth_client):
    issue = IssueFactory()
    CommentFactory(issue=issue)

    response = auth_client.get("/activity/?content_type=comment")

    issue_ct_id = ContentType.objects.get_for_model(Issue).id
    assert all(e.content_type_id != issue_ct_id for e in response.context["entries"])
    assert response.context["entries"], "at least one comment entry expected"


@pytest.mark.django_db
def test_activity_filters_by_since(auth_client):
    old = IssueFactory(title="old")
    new = IssueFactory(title="new")
    ActivityLog.objects.filter(object_id=old.pk).update(
        timestamp=timezone.now() - dt.timedelta(days=10)
    )

    cutoff = (timezone.localdate() - dt.timedelta(days=2)).isoformat()
    response = auth_client.get(f"/activity/?since={cutoff}")

    object_ids = {e.object_id for e in response.context["entries"]}
    assert new.pk in object_ids
    assert old.pk not in object_ids


@pytest.mark.django_db
def test_activity_ignores_invalid_since(auth_client):
    IssueFactory()

    response = auth_client.get("/activity/?since=not-a-date")

    # Malformed dates shouldn't crash or wipe the feed — silently drop the filter.
    assert response.status_code == 200
    assert len(response.context["entries"]) >= 1


@pytest.mark.django_db
def test_activity_attaches_issue_target_to_comment_entries(auth_client):
    issue = IssueFactory(title="host")
    CommentFactory(issue=issue)

    response = auth_client.get("/activity/?content_type=comment")

    entries = response.context["entries"]
    assert entries, "expected at least one comment log entry"
    assert all(e.target_issue == issue for e in entries)
    assert all(e.target_comment is not None for e in entries)


@pytest.mark.django_db
def test_activity_leaves_unknown_content_type_targets_empty(auth_client):
    """Log entries whose content_type isn't Issue/Comment shouldn't crash
    rendering — they just render without a linked target."""
    ct = ContentType.objects.create(app_label="other", model="widget")
    entry = ActivityLog.objects.create(
        content_type=ct, object_id=99, action_type="pxtx.other.update", actor="x"
    )

    response = auth_client.get("/activity/")

    assert response.status_code == 200
    found = [e for e in response.context["entries"] if e.pk == entry.pk]
    assert len(found) == 1
    assert found[0].target_issue is None
    assert found[0].target_comment is None


@pytest.mark.django_db
def test_activity_htmx_returns_only_list_fragment(auth_client):
    IssueFactory()

    response = auth_client.get("/activity/", HTTP_HX_REQUEST="true")

    body = response.content.decode()
    assert 'id="activity-list"' in body
    # htmx swap target only — no page chrome.
    assert "<nav" not in body
    assert "heatmap" not in body


@pytest.mark.django_db
def test_activity_paginates(auth_client):
    from pxtx.core.views.activity import PAGE_SIZE

    for _ in range(PAGE_SIZE + 5):
        IssueFactory()

    page1 = auth_client.get("/activity/")
    page2 = auth_client.get("/activity/?page=2")

    assert len(page1.context["entries"]) == PAGE_SIZE
    assert len(page2.context["entries"]) == 5
    assert page1.context["page_obj"].has_next()
    assert not page2.context["page_obj"].has_next()


@pytest.mark.django_db
def test_activity_pagination_links_encode_filter_values(auth_client):
    """Filter values containing querystring-significant chars must be
    percent-encoded in pagination hrefs, otherwise an ``&`` in an actor name
    would break the next page URL."""
    from pxtx.core.views.activity import PAGE_SIZE

    for _ in range(PAGE_SIZE + 1):
        issue = IssueFactory()
        issue.title = "edited"
        issue.save(actor="a&b=c")

    response = auth_client.get("/activity/?actor=a%26b%3Dc")

    body = response.content.decode()
    # Raw ``a&b=c`` in an href would parse as two separate params.
    assert "actor=a%26b%3Dc" in body
    assert "actor=a&b=c&" not in body


# ---- heatmap ---------------------------------------------------------------


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_renders_one_cell_per_day_in_window(auth_client):
    response = auth_client.get("/activity/")

    cells = response.context["heatmap_cells"]
    assert len(cells) == HEATMAP_WEEKS * 7
    # The last non-empty cell is today.
    dated = [c for c in cells if not c["empty"]]
    assert dated[-1]["date"] == dt.date(2026, 4, 22)
    # Start is aligned to Sunday 52 weeks before today.
    start = response.context["heatmap_start"]
    assert start.weekday() == 6  # Sunday in Python's 0=Monday scheme


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_marks_future_cells_as_empty(auth_client):
    response = auth_client.get("/activity/")

    cells = response.context["heatmap_cells"]
    # 2026-04-22 is a Wednesday; the last column has Thu/Fri/Sat empty.
    empty_count = sum(1 for c in cells if c["empty"])
    assert empty_count == 3


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_counts_creates_and_closes_on_today(auth_client):
    IssueFactory()
    IssueFactory()
    closed = IssueFactory()
    closed.status = Status.COMPLETED
    closed.save(actor="tester")
    dropped = IssueFactory()
    dropped.status = Status.WONTFIX
    dropped.save(actor="tester")

    response = auth_client.get("/activity/")

    today_cell = next(
        c
        for c in response.context["heatmap_cells"]
        if not c["empty"] and c["date"] == dt.date(2026, 4, 22)
    )
    # Four issues opened (factories emit pxtx.issue.create); two closes.
    assert today_cell["opened"] == 4
    assert today_cell["closed"] == 2
    assert today_cell["total"] == 6
    assert response.context["heatmap_total_opened"] == 4
    assert response.context["heatmap_total_closed"] == 2


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_excludes_entries_older_than_window(auth_client):
    old = IssueFactory()
    # Push the create entry beyond the 53-week window.
    ActivityLog.objects.filter(object_id=old.pk).update(
        timestamp=timezone.now() - dt.timedelta(days=400)
    )

    response = auth_client.get("/activity/")

    assert response.context["heatmap_total_opened"] == 0


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_ignores_non_counting_action_types(auth_client):
    issue = IssueFactory()
    # An update is logged but should not show up in the heatmap — only create
    # and close actions feed it.
    issue.title = "renamed"
    issue.save(actor="tester")

    response = auth_client.get("/activity/")

    assert response.context["heatmap_total_opened"] == 1
    assert response.context["heatmap_total_closed"] == 0


@pytest.mark.django_db
@freeze_time("2026-04-22 12:00:00")
def test_heatmap_tier_scales_with_count(auth_client):
    issue = IssueFactory()
    content_type = ContentType.objects.get_for_model(Issue)
    for _ in range(10):
        ActivityLog.objects.create(
            content_type=content_type,
            object_id=issue.pk,
            action_type="pxtx.issue.create",
            actor="bulk",
        )

    response = auth_client.get("/activity/")

    today_cell = next(
        c
        for c in response.context["heatmap_cells"]
        if not c["empty"] and c["date"] == dt.date(2026, 4, 22)
    )
    # 11 opens today (1 from factory + 10 synthetic) → highest tier.
    assert today_cell["tier"] == 4


@pytest.mark.django_db
@freeze_time("2026-04-19 12:00:00")
def test_heatmap_starts_on_sunday_when_today_is_sunday(auth_client):
    response = auth_client.get("/activity/")

    cells = response.context["heatmap_cells"]
    start = response.context["heatmap_start"]
    end = response.context["heatmap_end"]
    assert start.weekday() == 6
    assert end == dt.date(2026, 4, 19)
    # Last column is Sunday only; 6 empty slots beneath it.
    assert sum(1 for c in cells if c["empty"]) == 6
