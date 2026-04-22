import pytest

from tests.factories import UserFactory


@pytest.fixture
def auth_client(client):
    user = UserFactory()
    client.force_login(user)
    return client
