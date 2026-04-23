import pytest

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_root_redirects_to_issue_list(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url == "/issues/"


@pytest.mark.django_db
def test_root_redirects_anonymous_to_login(client):
    response = client.get("/", follow=True)

    assert response.redirect_chain[-1][0].startswith("/login/")


@pytest.mark.django_db
def test_logout_via_post_redirects_to_root(auth_client):
    response = auth_client.post("/logout/")

    assert response.status_code == 302
    assert response.url == "/"
    follow_up = auth_client.get("/issues/")
    assert follow_up.status_code == 302
    assert follow_up.url.startswith("/login/")
