import pytest
from django.db import IntegrityError, transaction

from pxtx.core.models import IssueReference
from tests.factories import IssueFactory, IssueReferenceFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_reference_links_two_issues():
    a = IssueFactory()
    b = IssueFactory()

    ref = IssueReferenceFactory(from_issue=a, to_issue=b)

    assert ref.from_issue == a
    assert ref.to_issue == b


@pytest.mark.django_db
def test_reference_unique_per_directed_pair():
    a = IssueFactory()
    b = IssueFactory()
    IssueReferenceFactory(from_issue=a, to_issue=b)

    with pytest.raises(IntegrityError), transaction.atomic():
        IssueReferenceFactory(from_issue=a, to_issue=b)


@pytest.mark.django_db
def test_reference_reverse_direction_is_allowed():
    """Symmetry is enforced at the view/API layer, not the model."""
    a = IssueFactory()
    b = IssueFactory()
    IssueReferenceFactory(from_issue=a, to_issue=b)

    # reverse direction does not violate the unique constraint
    IssueReferenceFactory(from_issue=b, to_issue=a)

    assert IssueReference.objects.count() == 2


@pytest.mark.django_db
def test_reference_rejects_self_link():
    a = IssueFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        IssueReferenceFactory(from_issue=a, to_issue=a)


@pytest.mark.django_db
def test_reference_cascades_on_either_issue_delete():
    a = IssueFactory()
    b = IssueFactory()
    IssueReferenceFactory(from_issue=a, to_issue=b)

    a.delete()

    assert IssueReference.objects.count() == 0
