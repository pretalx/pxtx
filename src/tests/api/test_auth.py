import pytest
from rest_framework.test import APIClient

from tests.factories import ApiTokenFactory, IssueFactory, UserFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_anonymous_request_returns_401():
    client = APIClient()

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_invalid_token_returns_401_with_no_hint():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Token pxtx_nonsense")

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401
    # The PLAN explicitly says: invalid token → 401 with no hint.
    assert response.json() == {"detail": "Invalid token."}


@pytest.mark.django_db
def test_valid_token_authenticates_and_bumps_last_used_at():
    token = ApiTokenFactory()
    assert token.last_used_at is None
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.plaintext}")

    response = client.get("/api/v1/issues/")

    assert response.status_code == 200
    token.refresh_from_db()
    assert token.last_used_at is not None


@pytest.mark.django_db
def test_inactive_user_token_is_rejected():
    token = ApiTokenFactory()
    token.user.is_active = False
    token.user.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.plaintext}")

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_token_name_is_used_as_comment_author(token_client, api_token):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/comments/",
        {"body": "from the CLI"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["author"] == api_token.name


@pytest.mark.django_db
def test_query_param_token_authenticates_when_header_missing():
    token = ApiTokenFactory()
    client = APIClient()

    response = client.get(f"/api/v1/issues/?token={token.plaintext}")

    assert response.status_code == 200


@pytest.mark.django_db
def test_query_param_token_rejects_invalid_token():
    client = APIClient()

    response = client.get("/api/v1/issues/?token=pxtx_nope")

    assert response.status_code == 401


@pytest.mark.django_db
def test_malformed_authorization_header_falls_through():
    """A single-word Authorization header (no space) is treated as absent;
    the view then demands auth and returns 401."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="MalformedHeader")

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_non_token_scheme_authorization_header_is_rejected():
    """A Basic/Bearer/etc header is not our scheme; we refuse to authenticate."""
    token = ApiTokenFactory()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.plaintext}")

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401


@pytest.mark.django_db
def test_authenticate_header_advertises_token_scheme():
    """401 responses should include WWW-Authenticate: Token so clients know
    which scheme we speak."""
    client = APIClient()

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Token"


@pytest.mark.django_db
def test_token_with_deleted_user_is_rejected():
    """Once a token's owning user is deleted, all requests must fail — even
    though the token row cascades away on delete, this asserts the expected
    behaviour if the cascade ever changes."""
    token = ApiTokenFactory()
    user_pk = token.user.pk
    UserFactory(username="survivor")  # ensure we're not matching "last user"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.plaintext}")
    from pxtx.core.models import User

    User.objects.filter(pk=user_pk).delete()

    response = client.get("/api/v1/issues/")

    assert response.status_code == 401
