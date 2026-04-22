import pytest
from django.utils import timezone

from pxtx.core.models import Comment
from tests.factories import CommentFactory, IssueFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_comment_records_created_at_and_no_edit():
    before = timezone.now()
    comment = CommentFactory()
    after = timezone.now()

    assert before <= comment.created_at <= after
    assert comment.edited_at is None


@pytest.mark.django_db
def test_comments_ordered_by_created_at_ascending():
    issue = IssueFactory()
    first = CommentFactory(issue=issue)
    second = CommentFactory(issue=issue)

    assert list(Comment.objects.filter(issue=issue)) == [first, second]


@pytest.mark.django_db
def test_comment_deleted_when_issue_deleted():
    issue = IssueFactory()
    CommentFactory(issue=issue)

    issue.delete()

    assert Comment.objects.count() == 0
