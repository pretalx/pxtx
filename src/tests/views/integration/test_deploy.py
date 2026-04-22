import pytest
from django.urls import reverse

from tests.factories import UserFactory

pytestmark = pytest.mark.integration


@pytest.fixture
def superuser_client(client):
    user = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(user)
    client.user = user
    return client


@pytest.mark.django_db
def test_deploy_requires_login(client):
    response = client.post(reverse("core:deploy"))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_deploy_rejects_regular_user(auth_client):
    response = auth_client.post(reverse("core:deploy"))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_deploy_writes_flag_file(superuser_client, tmp_path, settings):
    flag = tmp_path / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = superuser_client.post(reverse("core:deploy"), HTTP_REFERER="/somewhere/")

    assert response.status_code == 302
    assert response.url == "/somewhere/"
    assert flag.exists()
    assert superuser_client.user.username in flag.read_text()


@pytest.mark.django_db
def test_deploy_without_configured_flag_redirects_to_dashboard(
    superuser_client, settings
):
    settings.DEPLOY_FLAG_FILE = ""

    response = superuser_client.post(reverse("core:deploy"))

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")


@pytest.mark.django_db
def test_deploy_falls_back_to_dashboard_without_referer(
    superuser_client, tmp_path, settings
):
    flag = tmp_path / "nested" / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = superuser_client.post(reverse("core:deploy"))

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")
    assert flag.exists()


@pytest.mark.django_db
def test_deploy_htmx_returns_deploying_fragment(superuser_client, tmp_path, settings):
    flag = tmp_path / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = superuser_client.post(reverse("core:deploy"), HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert "core/_deploying.html" in [t.name for t in response.templates]
    assert b"site-nav-deploying" in response.content
    assert reverse("healthz").encode() in response.content
    assert flag.exists()


@pytest.mark.django_db
def test_deploy_htmx_without_configured_flag_redirects_via_header(
    superuser_client, settings
):
    settings.DEPLOY_FLAG_FILE = ""

    response = superuser_client.post(reverse("core:deploy"), HTTP_HX_REQUEST="true")

    assert response.status_code == 204
    assert response["HX-Redirect"] == reverse("core:dashboard")


@pytest.mark.django_db
def test_deploy_button_visible_for_superuser(superuser_client, tmp_path, settings):
    settings.DEPLOY_FLAG_FILE = str(tmp_path / "deploy.flag")

    response = superuser_client.get(reverse("core:dashboard"))

    assert b"btn-deploy" in response.content


@pytest.mark.django_db
def test_deploy_button_hidden_for_regular_user(auth_client, tmp_path, settings):
    settings.DEPLOY_FLAG_FILE = str(tmp_path / "deploy.flag")

    response = auth_client.get(reverse("core:dashboard"))

    assert b"btn-deploy" not in response.content


@pytest.mark.django_db
def test_deploy_button_hidden_when_not_configured(superuser_client, settings):
    settings.DEPLOY_FLAG_FILE = ""

    response = superuser_client.get(reverse("core:dashboard"))

    assert b"btn-deploy" not in response.content


@pytest.mark.django_db
def test_deploy_rejects_get(superuser_client, tmp_path, settings):
    flag = tmp_path / "deploy.flag"
    settings.DEPLOY_FLAG_FILE = str(flag)

    response = superuser_client.get(reverse("core:deploy"))

    assert response.status_code == 405
    assert not flag.exists()


@pytest.mark.django_db
def test_healthz_is_public_and_returns_ok(client):
    response = client.get(reverse("healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
