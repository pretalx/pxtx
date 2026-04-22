import pytest

from pxtx.core.admin import ActivityLogAdmin, ApiTokenAdmin
from pxtx.core.models import ActivityLog, ApiToken
from pxtx.core.models.api_token import _hash_token
from tests.factories import ApiTokenFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_activity_log_admin_forbids_creation_and_editing():
    admin = ActivityLogAdmin(ActivityLog, None)

    assert admin.has_add_permission(request=None) is False
    assert admin.has_change_permission(request=None) is False


@pytest.mark.django_db
def test_api_token_admin_add_view_creates_token_and_flashes_plaintext(client):
    superuser = UserFactory(username="admin", is_staff=True, is_superuser=True)
    client.force_login(superuser)
    owner = UserFactory(username="tobias")

    response = client.post(
        "/admin/core/apitoken/add/",
        {"name": "claude/feat-x", "user": owner.pk},
        follow=True,
    )

    assert response.status_code == 200
    token = ApiToken.objects.get(name="claude/feat-x")
    assert token.user == owner
    # The plaintext is only accessible once, via a flashed warning message.
    messages = [str(m) for m in response.context["messages"]]
    token_messages = [m for m in messages if "Copy it now" in m]
    assert len(token_messages) == 1
    # The flashed message must contain the exact plaintext: a string whose
    # sha256 matches the stored hash.
    import re

    match = re.search(r"<code>(pxtx_[A-Za-z0-9_\-]+)</code>", token_messages[0])
    assert match is not None
    assert _hash_token(match.group(1)) == token.token_hash


@pytest.mark.django_db
def test_api_token_admin_change_view_does_not_mint_new_token(client):
    superuser = UserFactory(username="admin", is_staff=True, is_superuser=True)
    client.force_login(superuser)
    token = ApiTokenFactory(name="original")
    original_hash = token.token_hash

    response = client.post(
        f"/admin/core/apitoken/{token.pk}/change/",
        {"name": "renamed", "user": token.user.pk},
        follow=True,
    )

    assert response.status_code == 200
    token.refresh_from_db()
    assert token.name == "renamed"
    assert token.token_hash == original_hash


@pytest.mark.django_db
def test_api_token_admin_get_fields_differs_for_add_vs_change():
    admin = ApiTokenAdmin(ApiToken, None)

    assert admin.get_fields(request=None, obj=None) == ["name", "user"]
    existing = admin.get_fields(request=None, obj=ApiTokenFactory())
    assert set(existing) >= {"name", "user", "token_hash"}
