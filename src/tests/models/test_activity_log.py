import pytest
from django.contrib.contenttypes.models import ContentType

from pxtx.core.models import ActivityLog, Comment, Issue, Status
from tests.factories import CommentFactory, IssueFactory, MilestoneFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_issue_create_logs_a_create_entry():
    issue = IssueFactory(title="hello", description="body text")

    entries = list(issue.logged_actions())

    assert [e.action_type for e in entries] == ["pxtx.issue.create"]
    entry = entries[0]
    assert entry.data["before"] == {}
    assert entry.data["after"]["title"] == "hello"
    assert entry.data["after"]["description"] == "body text"
    assert entry.data["after"]["status"] == Status.OPEN
    assert entry.actor == ""


@pytest.mark.django_db
def test_issue_update_logs_changed_fields_only():
    issue = IssueFactory(title="old", description="body")
    ActivityLog.objects.all().delete()

    issue.title = "new"
    issue.save(actor="rixx")

    entry = issue.logged_actions().get()
    assert entry.action_type == "pxtx.issue.update"
    assert entry.data["before"] == {"title": "old"}
    assert entry.data["after"] == {"title": "new"}
    assert entry.actor == "rixx"


@pytest.mark.django_db
def test_issue_save_without_changes_writes_no_log():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.save()

    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_issue_status_change_logs_separate_entry_from_other_updates():
    issue = IssueFactory(title="t", status=Status.OPEN)
    ActivityLog.objects.all().delete()

    issue.title = "renamed"
    issue.status = Status.WIP
    issue.save()

    entries = sorted(issue.logged_actions(), key=lambda e: e.action_type)
    assert [e.action_type for e in entries] == [
        "pxtx.issue.status.wip",
        "pxtx.issue.update",
    ]
    status_entry, update_entry = entries
    assert status_entry.data == {
        "before": {"status": "open"},
        "after": {"status": "wip"},
    }
    assert update_entry.data == {
        "before": {"title": "t"},
        "after": {"title": "renamed"},
    }


@pytest.mark.django_db
def test_issue_status_change_alone_emits_only_status_entry():
    issue = IssueFactory(status=Status.OPEN)
    ActivityLog.objects.all().delete()

    issue.status = Status.BLOCKED
    issue.save()

    entries = list(issue.logged_actions())
    assert [e.action_type for e in entries] == ["pxtx.issue.status.blocked"]


@pytest.mark.django_db
def test_issue_close_logs_status_and_closed_at():
    issue = IssueFactory(status=Status.OPEN)
    ActivityLog.objects.all().delete()

    issue.status = Status.COMPLETED
    issue.save()

    entries = sorted(issue.logged_actions(), key=lambda e: e.action_type)
    assert [e.action_type for e in entries] == [
        "pxtx.issue.status.completed",
        "pxtx.issue.update",
    ]
    update_entry = entries[1]
    # closed_at flips from None to a real datetime, so it shows up here
    assert set(update_entry.data["before"]) == {"closed_at"}
    assert update_entry.data["before"]["closed_at"] is None
    assert update_entry.data["after"]["closed_at"] is not None


@pytest.mark.django_db
def test_issue_milestone_change_records_pk():
    milestone = MilestoneFactory()
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.milestone = milestone
    issue.save()

    entry = issue.logged_actions().get()
    assert entry.action_type == "pxtx.issue.update"
    assert entry.data == {
        "before": {"milestone": None},
        "after": {"milestone": milestone.pk},
    }


@pytest.mark.django_db
def test_issue_delete_logs_delete_entry_with_snapshot():
    issue = IssueFactory(title="bye")
    issue_pk = issue.pk
    content_type = ContentType.objects.get_for_model(Issue)

    issue.delete()

    entry = ActivityLog.objects.get(
        content_type=content_type, object_id=issue_pk, action_type="pxtx.issue.delete"
    )
    assert entry.data["before"]["title"] == "bye"
    assert entry.data["after"] == {}


@pytest.mark.django_db
def test_skip_log_save_does_not_write_log():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.title = "silent"
    issue.save(skip_log=True)

    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_skip_log_delete_does_not_write_log():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.delete(skip_log=True)

    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_milestone_save_does_not_log_when_no_prefix():
    """Milestone has no log_action_prefix, so its writes never produce log entries."""
    MilestoneFactory()

    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_milestone_delete_does_not_log_when_no_prefix():
    milestone = MilestoneFactory()

    milestone.delete()

    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_comment_create_logs_with_body_snapshot():
    comment = CommentFactory(body="hello")

    entry = comment.logged_actions().get()
    assert entry.action_type == "pxtx.comment.create"
    assert entry.data["after"]["body"] == "hello"
    assert entry.data["after"]["edited_at"] is None


@pytest.mark.django_db
def test_comment_body_edit_logs_diff():
    comment = CommentFactory(body="first")
    ActivityLog.objects.all().delete()

    comment.body = "second"
    comment.save(actor="claude-feature/foo")

    entry = comment.logged_actions().get()
    assert entry.action_type == "pxtx.comment.update"
    assert entry.data == {"before": {"body": "first"}, "after": {"body": "second"}}
    assert entry.actor == "claude-feature/foo"


@pytest.mark.django_db
def test_log_action_with_explicit_action_name_skips_prefix():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.log_action("pxtx.custom.thing", actor="rixx", data={"foo": "bar"})

    entry = issue.logged_actions().get()
    assert entry.action_type == "pxtx.custom.thing"
    assert entry.data == {"foo": "bar"}
    assert entry.actor == "rixx"


@pytest.mark.django_db
def test_log_action_supports_data_alongside_before_after():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.log_action(".note", before={"x": 1}, after={"x": 2}, data={"why": "test"})

    entry = issue.logged_actions().get()
    assert entry.action_type == "pxtx.issue.note"
    assert entry.data == {"why": "test", "before": {"x": 1}, "after": {"x": 2}}


@pytest.mark.django_db
def test_logged_actions_filters_to_owning_object():
    first = IssueFactory()
    second = IssueFactory()
    ActivityLog.objects.all().delete()

    first.log_action(".note", data={"first": True})
    second.log_action(".note", data={"second": True})

    assert [e.data for e in first.logged_actions()] == [{"first": True}]
    assert [e.data for e in second.logged_actions()] == [{"second": True}]


@pytest.mark.django_db
def test_previous_snapshot_returns_empty_for_unsaved_instance():
    issue = Issue(title="ghost")

    assert issue._previous_snapshot() == {}


@pytest.mark.django_db
def test_previous_snapshot_returns_empty_when_row_was_deleted_underneath():
    issue = IssueFactory()
    pk = issue.pk
    Issue.objects.filter(pk=pk).delete()
    issue.pk = pk

    assert issue._previous_snapshot() == {}


@pytest.mark.django_db
def test_activity_log_orders_newest_first():
    issue = IssueFactory()  # create entry
    issue.title = "renamed"
    issue.save()  # update entry

    entries = list(issue.logged_actions())

    assert [e.action_type for e in entries] == [
        "pxtx.issue.update",
        "pxtx.issue.create",
    ]


@pytest.mark.django_db
def test_activity_log_changes_property_pivots_before_and_after():
    issue = IssueFactory(title="old", description="old body")
    issue.title = "renamed"
    issue.description = "new body"
    issue.save()

    entry = issue.logged_actions().filter(action_type="pxtx.issue.update").get()
    assert entry.changes == {
        "title": {"old": "old", "new": "renamed"},
        "description": {"old": "old body", "new": "new body"},
    }


@pytest.mark.django_db
def test_activity_log_changes_property_returns_none_when_no_diff_payload():
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    issue.log_action(".note", data={"why": "no diff here"})

    entry = issue.logged_actions().get()
    assert entry.changes is None


@pytest.mark.django_db
def test_comment_cascade_delete_does_not_log_comment_delete():
    """Cascade delete from Issue uses the Collector and bypasses Comment.delete()."""
    issue = IssueFactory()
    CommentFactory(issue=issue)
    ActivityLog.objects.all().delete()

    issue.delete()

    assert Comment.objects.count() == 0
    delete_entries = ActivityLog.objects.filter(action_type="pxtx.comment.delete")
    assert delete_entries.count() == 0
