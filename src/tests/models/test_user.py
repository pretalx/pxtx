import pytest

from pxtx.core.models import User
from tests.factories import UserFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_create_user_hashes_password_and_persists():
    user = User.objects.create_user(username="alice", password="hunter22")

    assert user.username == "alice"
    assert user.pk is not None
    assert user.password != "hunter22"
    assert user.check_password("hunter22") is True
    assert user.is_staff is False
    assert user.is_superuser is False


@pytest.mark.django_db
def test_create_user_without_password_sets_unusable_password():
    user = User.objects.create_user(username="bob")

    assert user.has_usable_password() is False


@pytest.mark.django_db
def test_create_user_rejects_empty_username():
    with pytest.raises(ValueError, match="username is required"):
        User.objects.create_user(username="", password="whatever")


@pytest.mark.django_db
def test_create_superuser_sets_staff_and_superuser_flags():
    user = User.objects.create_superuser(username="admin", password="s3cret")

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.check_password("s3cret") is True


@pytest.mark.django_db
def test_user_factory_sets_usable_password():
    user = UserFactory()

    assert user.has_usable_password() is True
    assert user.check_password("s3cret-pass-phrase") is True
