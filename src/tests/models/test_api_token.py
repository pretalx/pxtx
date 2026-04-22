import pytest

from pxtx.core.models import ApiToken
from pxtx.core.models.api_token import _hash_token, generate_token
from tests.factories import ApiTokenFactory, UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_create_returns_plaintext_once_and_stores_hash_only():
    user = UserFactory()

    token, plaintext = ApiToken.create(user=user, name="claude/feat-x")

    assert plaintext.startswith("pxtx_")
    assert token.token_hash == _hash_token(plaintext)
    assert token.token_hash != plaintext
    assert token.name == "claude/feat-x"
    assert token.user == user


@pytest.mark.django_db
def test_lookup_finds_token_by_plaintext():
    token = ApiTokenFactory()

    assert ApiToken.lookup(token.plaintext) == token


@pytest.mark.django_db
def test_lookup_returns_none_for_unknown_plaintext():
    ApiTokenFactory()

    assert ApiToken.lookup("pxtx_nonsense") is None


@pytest.mark.django_db
def test_lookup_returns_none_for_empty_key():
    assert ApiToken.lookup("") is None
    assert ApiToken.lookup(None) is None


def test_generate_token_is_prefixed_and_unique():
    a = generate_token()
    b = generate_token()

    assert a.startswith("pxtx_")
    assert b.startswith("pxtx_")
    assert a != b


@pytest.mark.django_db
def test_token_str_includes_name_and_user():
    token = ApiTokenFactory(name="claude/xyz")
    token.user.username = "rixx"
    token.user.save()

    assert str(token) == "claude/xyz (rixx)"
