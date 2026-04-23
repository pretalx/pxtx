import pytest
from django.utils import timezone

from pxtx.core.models import ActivityLog, Issue, Status
from tests.factories import IssueFactory, MilestoneFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_milestone_list_requires_login(client):
    response = client.get("/milestones/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_milestone_list_renders_empty_state(auth_client):
    response = auth_client.get("/milestones/")

    assert response.status_code == 200
    assert list(response.context["milestones"]) == []
    assert "No releases yet." in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", (1, 3))
def test_milestone_list_lists_all_with_constant_query_count(
    auth_client, django_assert_num_queries, item_count
):
    milestones = [MilestoneFactory() for _ in range(item_count)]
    for m in milestones:
        IssueFactory(milestone=m)
        IssueFactory(milestone=m)

    with django_assert_num_queries(3):
        response = auth_client.get("/milestones/")

    assert response.status_code == 200
    assert set(response.context["milestones"]) == set(milestones)
    for m in response.context["milestones"]:
        assert m.issue_count == 2


@pytest.mark.django_db
def test_milestone_list_marks_released_separately_from_unreleased(auth_client):
    released = MilestoneFactory(name="2024.0", released_at=timezone.now())
    unreleased = MilestoneFactory(name="2025.0")

    response = auth_client.get("/milestones/")

    body = response.content.decode()
    assert "released" in body
    assert "unreleased" in body
    assert {m.pk for m in response.context["milestones"]} == {
        released.pk,
        unreleased.pk,
    }


@pytest.mark.django_db
def test_milestone_detail_requires_login(client):
    milestone = MilestoneFactory()

    response = client.get(f"/milestones/{milestone.slug}/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


# ---- create / edit / release ------------------------------------------------


@pytest.mark.django_db
def test_milestone_new_requires_login(client):
    response = client.get("/milestones/new/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_milestone_edit_requires_login(client):
    milestone = MilestoneFactory()

    response = client.get(f"/milestones/{milestone.slug}/edit/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_milestone_release_requires_login(client):
    milestone = MilestoneFactory()

    response = client.post(f"/milestones/{milestone.slug}/release/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_milestone_new_renders_form(auth_client):
    response = auth_client.get("/milestones/new/")

    assert response.status_code == 200
    assert "New release" in response.content.decode()


@pytest.mark.django_db
def test_milestone_create_persists_and_redirects(auth_client):
    from pxtx.core.models import Milestone

    response = auth_client.post(
        "/milestones/new/",
        data={
            "name": "Version 42",
            "slug": "v42",
            "description": "first shot",
            "target_date": "2026-12-01",
        },
    )

    milestone = Milestone.objects.get(slug="v42")
    assert milestone.name == "Version 42"
    assert milestone.description == "first shot"
    assert response.status_code == 302
    assert response.url == f"/milestones/{milestone.slug}/"


@pytest.mark.django_db
def test_milestone_create_autogenerates_slug_from_name(auth_client):
    from pxtx.core.models import Milestone

    auth_client.post(
        "/milestones/new/", data={"name": "Spring 2027", "slug": "", "description": ""}
    )

    assert Milestone.objects.get(name="Spring 2027").slug == "spring-2027"


@pytest.mark.django_db
def test_milestone_create_surfaces_validation_errors(auth_client):
    response = auth_client.post(
        "/milestones/new/", data={"name": "", "slug": "", "description": ""}
    )

    assert response.status_code == 200
    assert response.context["form"].errors


@pytest.mark.django_db
def test_milestone_edit_renders_prefilled_form(auth_client):
    milestone = MilestoneFactory(name="Alpha", description="notes")

    response = auth_client.get(f"/milestones/{milestone.slug}/edit/")

    assert response.status_code == 200
    assert response.context["form"].initial["name"] == "Alpha"


@pytest.mark.django_db
def test_milestone_edit_saves_changes(auth_client):
    milestone = MilestoneFactory(name="Old", description="")

    response = auth_client.post(
        f"/milestones/{milestone.slug}/edit/",
        data={
            "name": "New name",
            "slug": milestone.slug,
            "description": "updated",
            "target_date": "",
        },
    )

    milestone.refresh_from_db()
    assert milestone.name == "New name"
    assert milestone.description == "updated"
    assert response.status_code == 302
    assert response.url == f"/milestones/{milestone.slug}/"


@pytest.mark.django_db
def test_milestone_release_sets_released_at(auth_client):
    milestone = MilestoneFactory(released_at=None)

    response = auth_client.post(f"/milestones/{milestone.slug}/release/")

    milestone.refresh_from_db()
    assert milestone.is_released
    assert response.status_code == 302
    assert response.url == f"/milestones/{milestone.slug}/"


@pytest.mark.django_db
def test_milestone_release_toggle_reopens(auth_client):
    milestone = MilestoneFactory(released_at=timezone.now())

    auth_client.post(f"/milestones/{milestone.slug}/release/")

    milestone.refresh_from_db()
    assert not milestone.is_released


@pytest.mark.django_db
def test_milestone_detail_shows_edit_and_release_controls(auth_client):
    milestone = MilestoneFactory(released_at=None)

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    body = response.content.decode()
    assert f"/milestones/{milestone.slug}/edit/" in body
    assert f"/milestones/{milestone.slug}/release/" in body
    assert "Mark released" in body


@pytest.mark.django_db
def test_milestone_detail_shows_reopen_when_released(auth_client):
    milestone = MilestoneFactory(released_at=timezone.now())

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    assert "Reopen release" in response.content.decode()


@pytest.mark.django_db
def test_milestone_list_links_to_create(auth_client):
    response = auth_client.get("/milestones/")

    assert "/milestones/new/" in response.content.decode()


# ---- kanban rendering -------------------------------------------------------


@pytest.mark.django_db
def test_milestone_detail_groups_issues_into_kanban_columns(auth_client):
    milestone = MilestoneFactory(name="25.1", slug="25-1", description="release notes")
    open_issue = IssueFactory(
        milestone=milestone, title="my open issue", status=Status.OPEN
    )
    wip_issue = IssueFactory(
        milestone=milestone, title="my wip issue", status=Status.WIP
    )
    blocked_issue = IssueFactory(
        milestone=milestone, title="my blocked", status=Status.BLOCKED
    )
    completed = IssueFactory(
        milestone=milestone, title="shipped", status=Status.COMPLETED
    )
    wontfix = IssueFactory(milestone=milestone, title="dropped", status=Status.WONTFIX)
    other_milestone = MilestoneFactory(slug="other")
    IssueFactory(milestone=other_milestone, title="other-milestone issue")

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    assert response.status_code == 200
    columns = {col["key"]: col for col in response.context["columns"]}
    assert list(columns) == ["open", "wip", "blocked", "done"]
    assert columns["open"]["cards"] == [open_issue]
    assert columns["wip"]["cards"] == [wip_issue]
    assert columns["blocked"]["cards"] == [blocked_issue]
    assert set(columns["done"]["cards"]) == {completed, wontfix}
    body = response.content.decode()
    assert "release notes" in body
    assert "my open issue" in body
    assert "other-milestone issue" not in body


@pytest.mark.django_db
def test_milestone_detail_kanban_is_empty_when_milestone_has_no_issues(auth_client):
    milestone = MilestoneFactory()

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    assert response.status_code == 200
    assert all(col["count"] == 0 for col in response.context["columns"])


@pytest.mark.django_db
def test_milestone_detail_hides_draft_issues_from_kanban(auth_client):
    """Draft ghost issues don't fit the board workflow and stay invisible
    on the kanban even if attached to a milestone."""
    milestone = MilestoneFactory()
    IssueFactory(milestone=milestone, status=Status.DRAFT, title="ghost")

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    cards_total = sum(col["count"] for col in response.context["columns"])
    assert cards_total == 0
    assert "ghost" not in response.content.decode()


@pytest.mark.django_db
def test_milestone_detail_orders_cards_within_column_by_order_in_milestone(auth_client):
    milestone = MilestoneFactory()
    first = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    second = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=1)
    third = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=2)

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    cards = [col for col in response.context["columns"] if col["key"] == "open"][0][
        "cards"
    ]
    assert cards == [first, second, third]


# ---- kanban move endpoint ---------------------------------------------------


@pytest.mark.django_db
def test_kanban_move_requires_login(client):
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN)

    response = client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "wip", "index": 0},
    )

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_kanban_move_within_column_rewrites_dense_order(auth_client):
    milestone = MilestoneFactory()
    a = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    b = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=1)
    c = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=2)

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": c.number, "column": "open", "index": 0},
    )

    a.refresh_from_db()
    b.refresh_from_db()
    c.refresh_from_db()
    assert (c.order_in_milestone, a.order_in_milestone, b.order_in_milestone) == (
        0,
        1,
        2,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_kanban_move_cross_column_updates_status_and_logs(auth_client):
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN)

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "wip", "index": 0},
    )

    issue.refresh_from_db()
    assert issue.status == Status.WIP.value
    assert issue.logged_actions().filter(action_type="pxtx.issue.status.wip").exists()


@pytest.mark.django_db
def test_kanban_move_within_column_does_not_log(auth_client):
    milestone = MilestoneFactory()
    a = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    b = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=1)
    before = ActivityLog.objects.count()

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": b.number, "column": "open", "index": 0},
    )

    assert ActivityLog.objects.count() == before
    a.refresh_from_db()
    b.refresh_from_db()
    assert (b.order_in_milestone, a.order_in_milestone) == (0, 1)


@pytest.mark.django_db
def test_kanban_move_to_done_from_open_becomes_completed(auth_client):
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN)

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "done", "index": 0},
    )

    issue.refresh_from_db()
    assert issue.status == Status.COMPLETED.value


@pytest.mark.django_db
def test_kanban_move_onto_done_keeps_wontfix_as_wontfix(auth_client):
    """Dragging a wontfix card inside the combined done column must not
    promote it to completed; the column is a display fold, not a state
    coercion."""
    milestone = MilestoneFactory()
    wontfix = IssueFactory(milestone=milestone, status=Status.WONTFIX)

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": wontfix.number, "column": "done", "index": 0},
    )

    wontfix.refresh_from_db()
    assert wontfix.status == Status.WONTFIX.value


@pytest.mark.django_db
def test_kanban_move_out_of_done_works_for_wontfix(auth_client):
    milestone = MilestoneFactory()
    wontfix = IssueFactory(milestone=milestone, status=Status.WONTFIX)

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": wontfix.number, "column": "open", "index": 0},
    )

    wontfix.refresh_from_db()
    assert wontfix.status == Status.OPEN.value


@pytest.mark.django_db
def test_kanban_move_rejects_unknown_column(auth_client):
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN)

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "archive", "index": 0},
    )

    assert response.status_code == 400
    issue.refresh_from_db()
    assert issue.status == Status.OPEN.value


@pytest.mark.django_db
def test_kanban_move_rejects_draft_issue(auth_client):
    """Drafts aren't rendered on the board, so a move request for one is a
    crafted POST. Reject it — don't silently promote the draft to a visible
    status."""
    milestone = MilestoneFactory()
    draft = IssueFactory(milestone=milestone, status=Status.DRAFT)

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": draft.number, "column": "open", "index": 0},
    )

    assert response.status_code == 400
    draft.refresh_from_db()
    assert draft.status == Status.DRAFT.value


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    (
        {"column": "open", "index": 0},  # missing issue
        {"issue": 1, "index": 0},  # missing column
        {"issue": 1, "column": "open"},  # missing index
    ),
)
def test_kanban_move_rejects_missing_fields(auth_client, payload):
    milestone = MilestoneFactory()

    response = auth_client.post(f"/milestones/{milestone.slug}/move/", data=payload)

    assert response.status_code == 400


@pytest.mark.django_db
def test_kanban_move_rejects_non_integer_fields(auth_client):
    milestone = MilestoneFactory()

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": "abc", "column": "open", "index": 0},
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_kanban_move_404s_if_issue_not_in_milestone(auth_client):
    milestone = MilestoneFactory()
    other_milestone = MilestoneFactory(slug="other")
    stray = IssueFactory(milestone=other_milestone, status=Status.OPEN)

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": stray.number, "column": "open", "index": 0},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_kanban_move_clamps_index_past_end_of_column(auth_client):
    milestone = MilestoneFactory()
    a = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    b = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=1)

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": a.number, "column": "open", "index": 999},
    )

    a.refresh_from_db()
    b.refresh_from_db()
    assert (b.order_in_milestone, a.order_in_milestone) == (0, 1)


@pytest.mark.django_db
def test_kanban_move_response_contains_updated_board(auth_client):
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN, title="to ship")

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "done", "index": 0},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="kanban"' in body
    assert "to ship" in body
    # Returned fragment holds the board, not the whole page.
    assert "<nav" not in body


@pytest.mark.django_db
def test_kanban_move_noop_on_same_column_same_position_is_idempotent(auth_client):
    """A drop that doesn't actually move the card (same status, same index)
    should leave both status and order untouched and not log anything."""
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    before_logs = ActivityLog.objects.count()

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "open", "index": 0},
    )

    issue.refresh_from_db()
    assert issue.status == Status.OPEN.value
    assert issue.order_in_milestone == 0
    assert ActivityLog.objects.count() == before_logs


@pytest.mark.django_db
def test_kanban_move_preserves_issues_in_other_columns(auth_client):
    milestone = MilestoneFactory()
    open_a = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    wip_a = IssueFactory(milestone=milestone, status=Status.WIP, order_in_milestone=5)
    blocked_a = IssueFactory(
        milestone=milestone,
        status=Status.BLOCKED,
        blocked_reason="waiting",
        order_in_milestone=3,
    )

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": open_a.number, "column": "wip", "index": 0},
    )

    open_a.refresh_from_db()
    wip_a.refresh_from_db()
    blocked_a.refresh_from_db()
    assert open_a.status == Status.WIP.value
    # Unrelated columns are left alone.
    assert wip_a.status == Status.WIP.value
    assert blocked_a.status == Status.BLOCKED.value
    assert blocked_a.order_in_milestone == 3
    assert Issue.objects.filter(milestone=milestone).count() == 3


@pytest.mark.django_db
def test_kanban_move_to_blocked_without_reason_rejected(auth_client):
    """Moving into Blocked needs a reason. The edit form enforces this;
    drag must not silently create a blocked issue with an empty reason."""
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone, status=Status.OPEN, blocked_reason="")

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "blocked", "index": 0},
    )

    assert response.status_code == 400
    issue.refresh_from_db()
    assert issue.status == Status.OPEN.value


@pytest.mark.django_db
def test_kanban_move_to_blocked_with_existing_reason_allowed(auth_client):
    """If the card already has a blocked_reason (e.g. was previously blocked),
    dragging it into Blocked again is fine — no silent bypass."""
    milestone = MilestoneFactory()
    issue = IssueFactory(
        milestone=milestone, status=Status.OPEN, blocked_reason="waiting on design"
    )

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": issue.number, "column": "blocked", "index": 0},
    )

    assert response.status_code == 200
    issue.refresh_from_db()
    assert issue.status == Status.BLOCKED.value


@pytest.mark.django_db
def test_kanban_move_reorder_within_blocked_allowed(auth_client):
    """Reordering inside Blocked is fine — the reason check only fires on
    cross-column moves."""
    milestone = MilestoneFactory()
    a = IssueFactory(
        milestone=milestone,
        status=Status.BLOCKED,
        blocked_reason="a",
        order_in_milestone=0,
    )
    b = IssueFactory(
        milestone=milestone,
        status=Status.BLOCKED,
        blocked_reason="b",
        order_in_milestone=1,
    )

    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": b.number, "column": "blocked", "index": 0},
    )

    assert response.status_code == 200
    a.refresh_from_db()
    b.refresh_from_db()
    assert (b.order_in_milestone, a.order_in_milestone) == (0, 1)


@pytest.mark.django_db
def test_kanban_move_within_done_reorders_completed_and_wontfix_together(auth_client):
    """The Done column folds completed + wontfix. Dragging a card within
    Done must reorder relative to all Done cards, not just ones sharing
    its DB status — otherwise the visual drop target doesn't match where
    the card lands after the server re-renders."""
    milestone = MilestoneFactory()
    c_a = IssueFactory(
        milestone=milestone, status=Status.COMPLETED, order_in_milestone=0
    )
    w_a = IssueFactory(milestone=milestone, status=Status.WONTFIX, order_in_milestone=1)
    c_b = IssueFactory(
        milestone=milestone, status=Status.COMPLETED, order_in_milestone=2
    )

    # Drag c_b to the top of Done.
    response = auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": c_b.number, "column": "done", "index": 0},
    )

    assert response.status_code == 200
    c_a.refresh_from_db()
    w_a.refresh_from_db()
    c_b.refresh_from_db()
    assert c_b.order_in_milestone == 0
    assert c_a.order_in_milestone == 1
    assert w_a.order_in_milestone == 2


@pytest.mark.django_db
def test_kanban_move_reorder_does_not_bump_updated_at_on_shuffled_siblings(auth_client):
    """Dense-reorder uses bulk_update so untouched siblings don't get their
    ``updated_at`` bumped — otherwise the ``?sort=updated`` view gets
    spurious activity every time someone drags a card."""
    milestone = MilestoneFactory()
    a = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=0)
    b = IssueFactory(milestone=milestone, status=Status.OPEN, order_in_milestone=1)
    a_before = a.updated_at
    b_before = b.updated_at

    auth_client.post(
        f"/milestones/{milestone.slug}/move/",
        data={"issue": b.number, "column": "open", "index": 0},
    )

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.updated_at == a_before
    assert b.updated_at == b_before
