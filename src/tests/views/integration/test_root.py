import pytest

from pxtx.core.models import Status
from tests.factories import IssueFactory, UserFactory

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
def test_dashboard_renders_for_authenticated_user(client):
    user = UserFactory()
    client.force_login(user)

    response = client.get("/dashboard/")

    assert response.status_code == 200
    assert "core/dashboard.html" in [t.name for t in response.templates]
    assert response.context["highlighted"] == []
    assert response.context["wip"] == []
    assert response.context["blocked"] == []
    assert response.context["recent"] == []
    assert response.context["counts"] == {"open": 0, "wip": 0, "blocked": 0, "draft": 0}


@pytest.mark.django_db
def test_dashboard_groups_issues_by_section(client):
    user = UserFactory()
    client.force_login(user)
    highlighted = IssueFactory(status=Status.OPEN, is_highlighted=True)
    wip = IssueFactory(status=Status.WIP)
    blocked = IssueFactory(status=Status.BLOCKED, blocked_reason="waiting")
    draft = IssueFactory(status=Status.DRAFT)
    closed = IssueFactory(status=Status.COMPLETED)
    # Closed highlighted issues are intentionally excluded from the highlighted
    # section — we don't want the dashboard to accumulate shipped work.
    closed_highlighted = IssueFactory(status=Status.COMPLETED, is_highlighted=True)

    response = client.get("/dashboard/")

    assert list(response.context["highlighted"]) == [highlighted]
    assert list(response.context["wip"]) == [wip]
    assert list(response.context["blocked"]) == [blocked]
    assert list(response.context["drafts"]) == [draft]
    assert set(response.context["recent"]) == {
        highlighted,
        wip,
        blocked,
        closed,
        closed_highlighted,
    }
    assert response.context["counts"] == {"open": 1, "wip": 1, "blocked": 1, "draft": 1}


@pytest.mark.django_db
def test_logout_via_post_redirects_to_root(auth_client):
    response = auth_client.post("/logout/")

    assert response.status_code == 302
    assert response.url == "/"
    follow_up = auth_client.get("/issues/")
    assert follow_up.status_code == 302
    assert follow_up.url.startswith("/login/")
