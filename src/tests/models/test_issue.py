import pytest
from django.utils import timezone

from pxtx.core.models import CLOSED_STATUSES, Effort, Issue, Priority, Source, Status
from tests.factories import IssueFactory, MilestoneFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_issue_number_starts_at_one():
    issue = IssueFactory()

    assert issue.number == 1
    assert issue.slug == "PX-1"


@pytest.mark.django_db
def test_issue_number_increments_per_new_issue():
    first = IssueFactory()
    second = IssueFactory()
    third = IssueFactory()

    assert [i.number for i in (first, second, third)] == [1, 2, 3]


@pytest.mark.django_db
def test_issue_number_leaves_gap_when_middle_issue_deleted():
    first = IssueFactory()
    middle = IssueFactory()
    third = IssueFactory()
    middle.delete()

    fourth = IssueFactory()

    # max()+1 means the hole at 2 stays open; we don't backfill
    assert [first.number, third.number, fourth.number] == [1, 3, 4]


@pytest.mark.django_db
def test_issue_number_preserved_when_explicitly_set():
    IssueFactory()
    issue = Issue(title="manual")
    issue.number = 99
    issue.save()

    assert issue.number == 99


@pytest.mark.django_db
def test_issue_defaults_match_plan():
    issue = IssueFactory()

    assert issue.priority == Priority.COULD
    assert issue.status == Status.OPEN
    assert issue.source == Source.MANUAL
    assert issue.effort_minutes is None
    assert issue.is_highlighted is False
    assert issue.milestone is None
    assert issue.assignee == ""
    assert issue.interested_parties == []
    assert issue.links == []
    assert issue.closed_at is None


@pytest.mark.django_db
def test_issue_closed_at_set_when_status_becomes_closed():
    issue = IssueFactory()

    assert issue.closed_at is None
    assert issue.is_closed is False

    issue.status = Status.COMPLETED
    before = timezone.now()
    issue.save()
    after = timezone.now()

    assert issue.is_closed is True
    assert before <= issue.closed_at <= after


@pytest.mark.django_db
def test_issue_closed_at_cleared_when_reopened():
    issue = IssueFactory(status=Status.COMPLETED)
    assert issue.closed_at is not None

    issue.status = Status.OPEN
    issue.save()

    assert issue.closed_at is None
    assert issue.is_closed is False


@pytest.mark.django_db
def test_issue_closed_at_preserved_across_status_save_within_closed():
    issue = IssueFactory(status=Status.COMPLETED)
    original = issue.closed_at

    issue.status = Status.WONTFIX
    issue.save()

    # already closed, don't stomp the original timestamp
    assert issue.closed_at == original


@pytest.mark.django_db
def test_issue_ordering_puts_want_and_highlighted_first():
    low = IssueFactory(priority=Priority.WHATEV)
    highlighted = IssueFactory(priority=Priority.COULD, is_highlighted=True)
    urgent = IssueFactory(priority=Priority.WANT)

    assert list(Issue.objects.all()) == [urgent, highlighted, low]


def test_closed_statuses_contains_completed_and_wontfix():
    assert frozenset({Status.COMPLETED, Status.WONTFIX}) == CLOSED_STATUSES


def test_effort_choices_cover_all_buckets():
    assert Effort.TINY == 30
    assert Effort.HUGE == 960
    assert {c for c, _ in Effort.choices} == {30, 90, 240, 480, 960}


def test_priority_choices_span_one_to_five():
    assert {c for c, _ in Priority.choices} == {1, 2, 3, 4, 5}


@pytest.mark.django_db
def test_issue_milestone_relation_exposes_issues():
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone)

    assert list(milestone.issues.all()) == [issue]
