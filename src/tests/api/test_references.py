import pytest

from pxtx.core.models import IssueReference
from tests.factories import IssueFactory, IssueReferenceFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_create_reference(token_client):
    from_issue = IssueFactory()
    to_issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{from_issue.number}/references/",
        {"to_issue": to_issue.number},
        format="json",
    )

    assert response.status_code == 201
    ref = IssueReference.objects.get()
    assert ref.from_issue == from_issue
    assert ref.to_issue == to_issue


@pytest.mark.django_db
def test_create_self_reference_returns_400(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/references/",
        {"to_issue": issue.number},
        format="json",
    )

    assert response.status_code == 400
    assert "to_issue" in response.json()
    assert IssueReference.objects.count() == 0


@pytest.mark.django_db
def test_create_reference_to_unknown_issue_returns_400(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/references/", {"to_issue": 9999}, format="json"
    )

    assert response.status_code == 400
    assert "to_issue" in response.json()


@pytest.mark.django_db
def test_duplicate_forward_reference_is_idempotent(token_client):
    a = IssueFactory()
    b = IssueFactory()
    existing = IssueReferenceFactory(from_issue=a, to_issue=b)

    response = token_client.post(
        f"/api/v1/issues/{a.number}/references/", {"to_issue": b.number}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["id"] == existing.pk
    assert IssueReference.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_backward_reference_is_idempotent(token_client):
    """References are symmetric; creating B→A when A→B exists should
    return the existing row rather than making a duplicate."""
    a = IssueFactory()
    b = IssueFactory()
    existing = IssueReferenceFactory(from_issue=b, to_issue=a)

    response = token_client.post(
        f"/api/v1/issues/{a.number}/references/", {"to_issue": b.number}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["id"] == existing.pk
    assert IssueReference.objects.count() == 1


@pytest.mark.django_db
def test_create_reference_from_missing_issue_returns_404(token_client):
    other = IssueFactory()

    response = token_client.post(
        "/api/v1/issues/9999/references/", {"to_issue": other.number}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_delete_reference(token_client):
    a = IssueFactory()
    b = IssueFactory()
    ref = IssueReferenceFactory(from_issue=a, to_issue=b)

    response = token_client.delete(f"/api/v1/issues/{a.number}/references/{ref.pk}/")

    assert response.status_code == 204
    assert IssueReference.objects.count() == 0


@pytest.mark.django_db
def test_delete_reference_from_target_side(token_client):
    """A→B can be deleted via either /issues/A/ or /issues/B/ — the edge
    is logically symmetric even though the row has a direction."""
    a = IssueFactory()
    b = IssueFactory()
    ref = IssueReferenceFactory(from_issue=a, to_issue=b)

    response = token_client.delete(f"/api/v1/issues/{b.number}/references/{ref.pk}/")

    assert response.status_code == 204


@pytest.mark.django_db
def test_delete_reference_404_when_ref_unrelated_to_issue(token_client):
    a = IssueFactory()
    b = IssueFactory()
    c = IssueFactory()
    ref = IssueReferenceFactory(from_issue=a, to_issue=b)

    response = token_client.delete(f"/api/v1/issues/{c.number}/references/{ref.pk}/")

    assert response.status_code == 404
    assert IssueReference.objects.filter(pk=ref.pk).exists()


@pytest.mark.django_db
def test_delete_reference_404_when_issue_missing(token_client):
    a = IssueFactory()
    b = IssueFactory()
    ref = IssueReferenceFactory(from_issue=a, to_issue=b)

    response = token_client.delete(f"/api/v1/issues/9999/references/{ref.pk}/")

    assert response.status_code == 404
