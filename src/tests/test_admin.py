import pytest

from pxtx.core.admin import ActivityLogAdmin
from pxtx.core.models import ActivityLog

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_activity_log_admin_forbids_creation_and_editing():
    admin = ActivityLogAdmin(ActivityLog, None)

    assert admin.has_add_permission(request=None) is False
    assert admin.has_change_permission(request=None) is False
