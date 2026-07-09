import uuid

import pytest
from rest_framework.test import APIClient

from pxtx.core.models import SpecStage, SpecTurn, SpecTurnKind, SpecTurnStatus
from tests.factories import IssueFactory, SpecSessionFactory, SpecTurnFactory

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_spec_session_detail_returns_stage_cost_and_turns(token_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    run_id = uuid.uuid4()
    completed = SpecTurnFactory(
        session=session,
        message="/opsx:explore",
        prompt_sent="/opsx:explore\n\nIssue context here",
        response="Here is what I found.",
        status=SpecTurnStatus.COMPLETED,
        cost_usd="0.250000",
        claude_session_id=run_id,
        artifacts={"proposal.md": "# Proposal"},
    )
    errored = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        message="focus on migrations",
        status=SpecTurnStatus.ERROR,
        cost_usd="0.050000",
        error_detail="claude exited without JSON",
        raw_result={"exit_code": 1, "stderr": "boom"},
    )

    response = token_client.get(f"/api/v1/issues/{session.issue.number}/spec/")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {
        "issue",
        "stage",
        "waiting_on_user",
        "total_cost_usd",
        "turns",
        "created_at",
        "updated_at",
    }
    assert data["issue"] == session.issue.number
    assert data["stage"] == "propose"
    # ⁂ The latest turn is an error, so the session is not waiting on user.
    assert data["waiting_on_user"] is False
    assert data["total_cost_usd"] == "0.300000"
    assert [t["id"] for t in data["turns"]] == [completed.pk, errored.pk]
    first, second = data["turns"]
    assert first["kind"] == "chat"
    assert first["stage"] == "propose"
    assert first["status"] == "completed"
    assert first["message"] == "/opsx:explore"
    assert first["prompt_sent"] == "/opsx:explore\n\nIssue context here"
    assert first["response"] == "Here is what I found."
    assert first["cost_usd"] == "0.250000"
    assert first["claude_session_id"] == str(run_id)
    assert first["error_detail"] == ""
    assert first["raw_result"] == {}
    assert second["kind"] == "critique"
    assert second["status"] == "error"
    assert second["error_detail"] == "claude exited without JSON"
    assert second["raw_result"] == {"exit_code": 1, "stderr": "boom"}
    assert second["claude_session_id"] is None


@pytest.mark.django_db
def test_spec_session_detail_reports_waiting_on_user(token_client):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED, response="Done.")

    response = token_client.get(f"/api/v1/issues/{session.issue.number}/spec/")

    assert response.status_code == 200
    assert response.json()["waiting_on_user"] is True


@pytest.mark.django_db
def test_spec_session_detail_without_turns_has_null_cost(token_client):
    session = SpecSessionFactory()

    response = token_client.get(f"/api/v1/issues/{session.issue.number}/spec/")

    assert response.status_code == 200
    data = response.json()
    assert data["turns"] == []
    assert data["total_cost_usd"] is None
    assert data["waiting_on_user"] is False


@pytest.mark.django_db
def test_spec_artifacts_returns_latest_finished_snapshot(token_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Old"},
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# New", "specs/api/spec.md": "# API"},
    )
    # ⁂ A queued turn has no snapshot yet and must not shadow the latest
    # finished one.
    SpecTurnFactory(session=session)

    response = token_client.get(
        f"/api/v1/issues/{session.issue.number}/spec/artifacts/"
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue": session.issue.number,
        "stage": "propose",
        "artifacts": {"proposal.md": "# New", "specs/api/spec.md": "# API"},
    }


@pytest.mark.django_db
def test_spec_artifacts_empty_when_no_finished_turn(token_client):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session)

    response = token_client.get(
        f"/api/v1/issues/{session.issue.number}/spec/artifacts/"
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue": session.issue.number,
        "stage": "explore",
        "artifacts": {},
    }


@pytest.mark.parametrize("suffix", ("", "artifacts/"))
@pytest.mark.django_db
def test_spec_endpoints_require_auth(suffix):
    session = SpecSessionFactory()

    response = APIClient().get(f"/api/v1/issues/{session.issue.number}/spec/{suffix}")

    assert response.status_code == 401


@pytest.mark.parametrize("suffix", ("", "artifacts/"))
@pytest.mark.django_db
def test_spec_endpoints_accept_query_param_token(api_token, suffix):
    session = SpecSessionFactory()

    response = APIClient().get(
        f"/api/v1/issues/{session.issue.number}/spec/{suffix}"
        f"?token={api_token.plaintext}"
    )

    assert response.status_code == 200
    assert response.json()["issue"] == session.issue.number


@pytest.mark.parametrize("suffix", ("", "artifacts/"))
@pytest.mark.django_db
def test_spec_endpoints_404_for_issue_without_session(token_client, suffix):
    issue = IssueFactory()

    response = token_client.get(f"/api/v1/issues/{issue.number}/spec/{suffix}")

    assert response.status_code == 404


@pytest.mark.parametrize("suffix", ("", "artifacts/"))
@pytest.mark.django_db
def test_spec_endpoints_404_for_unknown_issue(token_client, suffix):
    response = token_client.get(f"/api/v1/issues/9999/spec/{suffix}")

    assert response.status_code == 404


@pytest.mark.parametrize("method", ("post", "put", "patch", "delete"))
@pytest.mark.parametrize("suffix", ("", "artifacts/"))
@pytest.mark.django_db
def test_spec_endpoints_reject_writes(token_client, suffix, method):
    session = SpecSessionFactory()

    response = getattr(token_client, method)(
        f"/api/v1/issues/{session.issue.number}/spec/{suffix}",
        {"stage": "ready", "message": "hi"},
        format="json",
    )

    assert response.status_code == 405
    session.refresh_from_db()
    assert session.stage == SpecStage.EXPLORE
    assert SpecTurn.objects.count() == 0
