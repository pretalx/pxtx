import pytest

from tests.factories import UserFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_root_redirects_anonymous_to_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_root_redirects_authenticated_to_issue_list(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get("/")

    assert response.status_code == 302
    assert response.url == "/issues/"
