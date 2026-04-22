import pytest
from rest_framework.test import APIClient

from tests.factories import ApiTokenFactory, UserFactory


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    return client


@pytest.fixture
def api_token():
    return ApiTokenFactory()


@pytest.fixture
def token_client(api_token):
    """APIClient with ``Authorization: Token <plaintext>`` preset."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {api_token.plaintext}")
    return client
