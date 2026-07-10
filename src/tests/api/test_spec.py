import uuid

import pytest
from rest_framework.test import APIClient

from pxtx.core.models import (
    ActivityLog,
    SpecSession,
    SpecStage,
    SpecTurn,
    SpecTurnKind,
    SpecTurnStatus,
)
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
    # The latest turn is an error, so the session is not waiting on user.
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
    assert first["actor"] == ""
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
    # A queued turn has no snapshot yet and must not shadow the latest
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
def test_spec_artifacts_survive_later_blank_snapshot(token_client):
    """A crashed turn snapshotting an empty change dir after a completed
    turn with artifacts must not make `pxtx spec pull` come up empty — the
    endpoint mirrors the UI's current-spec view, not the raw latest
    snapshot."""
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.ERROR, artifacts={})

    response = token_client.get(
        f"/api/v1/issues/{session.issue.number}/spec/artifacts/"
    )

    assert response.status_code == 200
    assert response.json()["artifacts"] == {"proposal.md": "# Plan"}


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


@pytest.mark.parametrize(
    ("suffix", "method"),
    (
        # The artifacts endpoint allows POST (the push); the session detail
        # stays GET-only. Everything else is 405 everywhere.
        ("", "post"),
        ("", "put"),
        ("", "patch"),
        ("", "delete"),
        ("artifacts/", "put"),
        ("artifacts/", "patch"),
        ("artifacts/", "delete"),
    ),
)
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


def _push(client, number, payload, **extra):
    return client.post(
        f"/api/v1/issues/{number}/spec/artifacts/", payload, format="json", **extra
    )


@pytest.mark.django_db
def test_spec_push_creates_session_and_completed_turn(token_client):
    issue = IssueFactory()
    ActivityLog.objects.all().delete()

    response = _push(
        token_client,
        issue.number,
        {
            "artifacts": {"proposal.md": "# P", "specs/api/spec.md": "# A"},
            "message": "drafted locally",
        },
        HTTP_X_PXTX_ACTOR="claude-push",
    )

    assert response.status_code == 201
    turn = SpecTurn.objects.get()
    assert response.json() == {
        "issue": issue.number,
        "stage": "propose",
        "turn": turn.pk,
        "files": 2,
        "created_session": True,
        "unchanged": False,
    }
    session = issue.spec_session
    assert session.stage == SpecStage.PROPOSE
    assert turn.session == session
    assert turn.kind == SpecTurnKind.PUSH
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.stage == SpecStage.PROPOSE
    assert turn.message == "drafted locally"
    assert turn.actor == "claude-push"
    assert turn.artifacts == {"proposal.md": "# P", "specs/api/spec.md": "# A"}
    assert [(e.action_type, e.actor) for e in ActivityLog.objects.order_by("pk")] == [
        ("pxtx.spec.session.create", "claude-push"),
        ("pxtx.spec.turn.create", "claude-push"),
    ]


@pytest.mark.django_db
def test_spec_push_to_existing_propose_session(token_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    response = _push(
        token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created_session"] is False
    assert data["stage"] == "propose"
    turn = session.turns.get()
    assert turn.kind == SpecTurnKind.PUSH
    assert turn.message == ""


@pytest.mark.django_db
def test_spec_push_actor_falls_back_to_token_name(api_token):
    issue = IssueFactory()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {api_token.plaintext}")

    response = _push(client, issue.number, {"artifacts": {"proposal.md": "# P"}})

    assert response.status_code == 201
    assert SpecTurn.objects.get().actor == api_token.name


@pytest.mark.django_db
def test_spec_push_requires_auth():
    issue = IssueFactory()

    response = _push(APIClient(), issue.number, {"artifacts": {"proposal.md": "# P"}})

    assert response.status_code == 401
    assert SpecSession.objects.count() == 0


@pytest.mark.django_db
def test_spec_push_accepts_query_param_token(api_token):
    issue = IssueFactory()

    response = APIClient().post(
        f"/api/v1/issues/{issue.number}/spec/artifacts/?token={api_token.plaintext}",
        {"artifacts": {"proposal.md": "# P"}},
        format="json",
    )

    assert response.status_code == 201
    assert issue.spec_session.turns.count() == 1


@pytest.mark.django_db
def test_spec_push_unknown_issue_404(token_client):
    response = _push(token_client, 9999, {"artifacts": {"proposal.md": "# P"}})

    assert response.status_code == 404
    assert SpecSession.objects.count() == 0


@pytest.mark.parametrize(
    "payload",
    (
        {},  # artifacts missing entirely
        {"artifacts": {}},
        {"artifacts": ["proposal.md"]},
        {"artifacts": "proposal.md"},
        {"artifacts": {"proposal.md": 5}},
        {"artifacts": {"proposal.md": None}},
    ),
)
@pytest.mark.django_db
def test_spec_push_rejects_malformed_artifacts(token_client, payload):
    issue = IssueFactory()

    response = _push(token_client, issue.number, payload)

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0
    assert SpecTurn.objects.count() == 0


@pytest.mark.parametrize(
    "path",
    (
        "/etc/passwd",
        "..",
        "../proposal.md",
        "specs/../proposal.md",
        "specs/..",
        ".",
        "./proposal.md",
        "specs/./a.md",
        "specs//a.md",
        "specs/a.md/",
        "",
        "specs/a\x00.md",
    ),
)
@pytest.mark.django_db
def test_spec_push_rejects_unsafe_and_non_canonical_paths(token_client, path):
    issue = IssueFactory()

    response = _push(
        token_client, issue.number, {"artifacts": {path: "content", "ok.md": "fine"}}
    )

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0


# ⁂ Raw bodies, not format="json": lone surrogates from JSON "\ud800"
# escapes survive parsing as Python str but cannot be UTF-8-encoded, so the
# test client's own JSON renderer would choke on them before the request
# ever left — exactly the crash the serializer must catch server-side.
@pytest.mark.django_db
def test_spec_push_rejects_surrogate_in_path(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/spec/artifacts/",
        data='{"artifacts": {"bad\\ud800.md": "content", "ok.md": "fine"}}',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0


@pytest.mark.django_db
def test_spec_push_rejects_surrogate_in_content(token_client):
    issue = IssueFactory()

    response = token_client.post(
        f"/api/v1/issues/{issue.number}/spec/artifacts/",
        data='{"artifacts": {"ok.md": "bad \\udfff content"}}',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0


@pytest.mark.django_db
def test_spec_push_rejects_prefix_collisions(token_client):
    issue = IssueFactory()

    response = _push(
        token_client,
        issue.number,
        {"artifacts": {"a.md": "file", "a.md/b.md": "also file?"}},
    )

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0


@pytest.mark.parametrize(
    "artifacts",
    (
        {f"file-{i}.md": "x" for i in range(65)},  # too many files
        {"big.md": "x" * (512 * 1024 + 1)},  # single file too large
        # Each file below the per-file cap, total above the overall cap.
        {f"file-{i}.md": "x" * (480 * 1024) for i in range(5)},
    ),
)
@pytest.mark.django_db
def test_spec_push_rejects_oversized_pushes(token_client, artifacts):
    issue = IssueFactory()

    response = _push(token_client, issue.number, {"artifacts": artifacts})

    assert response.status_code == 400
    assert "artifacts" in response.json()
    assert SpecSession.objects.count() == 0


@pytest.mark.django_db
def test_spec_push_identical_content_returns_unchanged(token_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    _push(token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}})
    log_count = ActivityLog.objects.count()

    response = _push(
        token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}}
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue": session.issue.number,
        "stage": "propose",
        "unchanged": True,
    }
    assert session.turns.count() == 1
    assert ActivityLog.objects.count() == log_count


@pytest.mark.django_db
def test_spec_push_identical_content_with_ready_flag_still_transitions(token_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    _push(token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}})

    response = _push(
        token_client,
        session.issue.number,
        {"artifacts": {"proposal.md": "# P"}, "ready": True},
        HTTP_X_PXTX_ACTOR="claude-push",
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue": session.issue.number,
        "stage": "ready",
        "unchanged": True,
    }
    session.refresh_from_db()
    assert session.stage == SpecStage.READY
    assert session.turns.count() == 1
    stage_entry = ActivityLog.objects.get(action_type="pxtx.spec.session.stage.ready")
    assert stage_entry.actor == "claude-push"


@pytest.mark.django_db
def test_spec_push_unchanged_content_to_explore_session_still_normalizes_stage(
    token_client,
):
    # ⁂ The explore → propose normalization is a stage effect, not a
    # content effect: it must apply even when the pushed content matches
    # the latest finished snapshot and no turn is created.
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# P"},
    )
    assert session.stage == SpecStage.EXPLORE

    response = _push(
        token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}}
    )

    assert response.status_code == 200
    assert response.json() == {
        "issue": session.issue.number,
        "stage": "propose",
        "unchanged": True,
    }
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    assert session.turns.count() == 1


@pytest.mark.parametrize("status", (SpecTurnStatus.QUEUED, SpecTurnStatus.RUNNING))
@pytest.mark.django_db
def test_spec_push_conflicts_with_active_turn(token_client, status):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(session=session, status=status)
    log_count = ActivityLog.objects.count()

    response = _push(
        token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}}
    )

    assert response.status_code == 409
    assert "detail" in response.json()
    assert session.turns.count() == 1
    assert ActivityLog.objects.count() == log_count


@pytest.mark.django_db
def test_spec_push_to_ready_session_conflicts_without_reopen(token_client):
    session = SpecSessionFactory(stage=SpecStage.READY)
    log_count = ActivityLog.objects.count()

    response = _push(
        token_client, session.issue.number, {"artifacts": {"proposal.md": "# P"}}
    )

    assert response.status_code == 409
    assert "detail" in response.json()
    session.refresh_from_db()
    assert session.stage == SpecStage.READY
    assert session.turns.count() == 0
    assert ActivityLog.objects.count() == log_count


@pytest.mark.django_db
def test_spec_push_reopen_flag_reopens_ready_session(token_client):
    session = SpecSessionFactory(stage=SpecStage.READY)

    response = _push(
        token_client,
        session.issue.number,
        {"artifacts": {"proposal.md": "# P"}, "reopen": True},
    )

    assert response.status_code == 201
    assert response.json()["stage"] == "propose"
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    assert session.turns.get().kind == SpecTurnKind.PUSH


@pytest.mark.django_db
def test_spec_push_ready_flag_marks_session_ready(token_client):
    session = SpecSessionFactory(stage=SpecStage.EXPLORE)

    response = _push(
        token_client,
        session.issue.number,
        {"artifacts": {"proposal.md": "# P"}, "ready": True},
    )

    assert response.status_code == 201
    assert response.json()["stage"] == "ready"
    session.refresh_from_db()
    assert session.stage == SpecStage.READY
    # The push turn itself records propose: the ready flag applies after
    # the turn is stored.
    assert session.turns.get().stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_spec_push_turn_appears_in_session_detail_with_actor(token_client):
    issue = IssueFactory()
    _push(
        token_client,
        issue.number,
        {"artifacts": {"proposal.md": "# P"}, "message": "take a look"},
        HTTP_X_PXTX_ACTOR="claude-push",
    )

    response = token_client.get(f"/api/v1/issues/{issue.number}/spec/")

    assert response.status_code == 200
    (turn,) = response.json()["turns"]
    assert turn["kind"] == "push"
    assert turn["status"] == "completed"
    assert turn["actor"] == "claude-push"
    assert turn["message"] == "take a look"
    assert turn["prompt_sent"] == ""
    assert turn["response"] == ""
    assert turn["cost_usd"] is None
    assert turn["claude_session_id"] is None


@pytest.mark.django_db
def test_spec_push_feeds_the_artifacts_pull(token_client):
    issue = IssueFactory()
    artifacts = {"proposal.md": "# P", "specs/api/spec.md": "# A"}
    _push(token_client, issue.number, {"artifacts": artifacts})

    response = token_client.get(f"/api/v1/issues/{issue.number}/spec/artifacts/")

    assert response.status_code == 200
    assert response.json() == {
        "issue": issue.number,
        "stage": "propose",
        "artifacts": artifacts,
    }
