import pytest
from django.utils import timezone

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


@pytest.mark.django_db
def test_milestone_detail_renders_milestone_and_its_issues(auth_client):
    milestone = MilestoneFactory(name="25.1", slug="25-1", description="release notes")
    own = IssueFactory(milestone=milestone, title="my issue")
    other_milestone = MilestoneFactory(slug="other")
    IssueFactory(milestone=other_milestone, title="other issue")

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    assert response.status_code == 200
    assert response.context["milestone"] == milestone
    assert list(response.context["issues"]) == [own]
    body = response.content.decode()
    assert "release notes" in body
    assert "my issue" in body
    assert "other issue" not in body


@pytest.mark.django_db
def test_milestone_detail_renders_empty_when_no_issues(auth_client):
    milestone = MilestoneFactory()

    response = auth_client.get(f"/milestones/{milestone.slug}/")

    assert response.status_code == 200
    assert response.context["issues"] == []
    assert "No issues in this release." in response.content.decode()
