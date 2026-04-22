import pytest

from tests.factories import MilestoneFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_list_milestones(token_client):
    MilestoneFactory(slug="release-1", name="Release 1")
    MilestoneFactory(slug="release-2", name="Release 2")

    response = token_client.get("/api/v1/milestones/")

    assert response.status_code == 200
    slugs = {r["slug"] for r in response.json()["results"]}
    assert slugs == {"release-1", "release-2"}


@pytest.mark.django_db
def test_retrieve_milestone_by_slug(token_client):
    MilestoneFactory(slug="release-1", name="First")

    response = token_client.get("/api/v1/milestones/release-1/")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "release-1"
    assert body["name"] == "First"


@pytest.mark.django_db
def test_create_milestone(token_client):
    response = token_client.post(
        "/api/v1/milestones/",
        {"slug": "release-42", "name": "Release 42"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "release-42"


@pytest.mark.django_db
def test_patch_milestone_updates_name(token_client):
    MilestoneFactory(slug="r1", name="Old")

    response = token_client.patch(
        "/api/v1/milestones/r1/", {"name": "New"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New"
