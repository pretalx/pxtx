import datetime

import pytest
from django.utils import timezone

from pxtx.core.models import Milestone
from tests.factories import IssueFactory, MilestoneFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_milestone_sets_created_and_updated_timestamps():
    before = timezone.now()
    milestone = MilestoneFactory(name="25.1", slug="25-1")
    after = timezone.now()

    assert before <= milestone.created_at <= after
    assert before <= milestone.updated_at <= after


@pytest.mark.django_db
def test_milestone_is_released_reflects_released_at():
    unreleased = MilestoneFactory()
    released = MilestoneFactory(released_at=timezone.now())

    assert unreleased.is_released is False
    assert released.is_released is True


@pytest.mark.django_db
def test_milestones_ordered_by_descending_target_date():
    soon = MilestoneFactory(target_date=datetime.date(2026, 6, 1))
    later = MilestoneFactory(target_date=datetime.date(2026, 12, 1))
    undated = MilestoneFactory(target_date=None)

    # nulls sort last under descending in sqlite/postgres default
    assert list(Milestone.objects.all()) == [later, soon, undated]


@pytest.mark.django_db
def test_milestone_issue_becomes_orphan_when_milestone_deleted():
    milestone = MilestoneFactory()
    issue = IssueFactory(milestone=milestone)

    milestone.delete()
    issue.refresh_from_db()

    assert issue.milestone is None
