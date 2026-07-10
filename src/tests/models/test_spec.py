import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from pxtx.core.models import (
    ActivityLog,
    SpecSession,
    SpecStage,
    SpecTurn,
    SpecTurnKind,
    SpecTurnStatus,
    Status,
)
from tests.factories import IssueFactory, SpecSessionFactory, SpecTurnFactory

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_spec_session_defaults_to_explore_with_fresh_claude_session_id():
    session = SpecSessionFactory()
    other = SpecSessionFactory()

    assert session.stage == SpecStage.EXPLORE
    assert isinstance(session.claude_session_id, uuid.UUID)
    assert session.claude_session_id != other.claude_session_id


@pytest.mark.django_db
def test_spec_session_create_logs_create_entry():
    session = SpecSessionFactory()

    entries = list(session.logged_actions())

    assert [e.action_type for e in entries] == ["pxtx.spec.session.create"]
    entry = entries[0]
    entry.refresh_from_db()
    assert entry.data["before"] == {}
    assert entry.data["after"] == {
        "stage": "explore",
        "claude_session_id": str(session.claude_session_id),
    }


@pytest.mark.django_db
def test_second_spec_session_for_issue_rejected():
    issue = IssueFactory()
    SpecSessionFactory(issue=issue)

    with pytest.raises(IntegrityError), transaction.atomic():
        SpecSessionFactory(issue=issue)

    assert SpecSession.objects.filter(issue=issue).count() == 1


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (SpecStage.EXPLORE, SpecStage.PROPOSE),
        (SpecStage.PROPOSE, SpecStage.EXPLORE),
        (SpecStage.PROPOSE, SpecStage.READY),
        (SpecStage.READY, SpecStage.PROPOSE),
    ),
)
@pytest.mark.django_db
def test_change_stage_allowed_transition_saves_and_logs(old, new):
    session = SpecSessionFactory(stage=old)
    ActivityLog.objects.all().delete()

    session.change_stage(new, actor="rixx")

    session.refresh_from_db()
    assert session.stage == new
    entry = session.logged_actions().get()
    assert entry.action_type == f"pxtx.spec.session.stage.{new}"
    assert entry.data["before"] == {"stage": old}
    assert entry.data["after"] == {"stage": new}
    assert entry.actor == "rixx"


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (SpecStage.EXPLORE, SpecStage.READY),
        (SpecStage.READY, SpecStage.EXPLORE),
        (SpecStage.EXPLORE, SpecStage.EXPLORE),
        (SpecStage.PROPOSE, SpecStage.PROPOSE),
        (SpecStage.READY, SpecStage.READY),
        (SpecStage.EXPLORE, "nonsense"),
    ),
)
@pytest.mark.django_db
def test_change_stage_invalid_transition_rejected(old, new):
    session = SpecSessionFactory(stage=old)
    ActivityLog.objects.all().delete()

    with pytest.raises(ValidationError) as excinfo:
        session.change_stage(new)

    assert excinfo.value.code == "invalid_stage_transition"
    session.refresh_from_db()
    assert session.stage == old
    assert not ActivityLog.objects.exists()


@pytest.mark.django_db
def test_change_stage_never_touches_the_issue():
    issue = IssueFactory(status=Status.WIP)
    session = SpecSessionFactory(issue=issue, stage=SpecStage.PROPOSE)
    issue_updated_at = issue.updated_at
    issue_log_count = issue.logged_actions().count()

    session.change_stage(SpecStage.READY)

    issue.refresh_from_db()
    assert issue.status == Status.WIP
    assert issue.updated_at == issue_updated_at
    assert issue.logged_actions().count() == issue_log_count


@pytest.mark.django_db
def test_session_without_turns_is_not_waiting_on_user():
    session = SpecSessionFactory()

    assert session.is_waiting_on_user is False


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        (SpecTurnStatus.QUEUED, False),
        (SpecTurnStatus.RUNNING, False),
        (SpecTurnStatus.COMPLETED, True),
        (SpecTurnStatus.ERROR, False),
    ),
)
@pytest.mark.django_db
def test_waiting_on_user_follows_latest_turn_status(status, expected):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=status)

    assert session.is_waiting_on_user is expected


@pytest.mark.django_db
def test_ready_session_is_not_waiting_on_user():
    session = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED)

    assert session.is_waiting_on_user is False


@pytest.mark.django_db
def test_queueing_a_new_turn_clears_waiting_on_user():
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED)
    assert session.is_waiting_on_user is True

    SpecTurnFactory(session=session)

    assert session.is_waiting_on_user is False


@pytest.mark.django_db
def test_waiting_on_user_requires_no_earlier_active_turn():
    """A queued turn behind a completed one (e.g. after a startup requeue)
    means the worker still has work — the session is not waiting."""
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.QUEUED)
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED)

    assert session.is_waiting_on_user is False


@pytest.mark.django_db
def test_with_waiting_on_user_annotation_matches_property():
    no_turns = SpecSessionFactory()
    waiting = SpecSessionFactory()
    SpecTurnFactory(session=waiting, status=SpecTurnStatus.COMPLETED)
    ready = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(session=ready, status=SpecTurnStatus.COMPLETED)
    errored = SpecSessionFactory()
    SpecTurnFactory(session=errored, status=SpecTurnStatus.ERROR)
    backlogged = SpecSessionFactory()
    SpecTurnFactory(session=backlogged, status=SpecTurnStatus.QUEUED)
    SpecTurnFactory(session=backlogged, status=SpecTurnStatus.COMPLETED)

    annotated = SpecSession.objects.with_waiting_on_user()

    assert set(annotated.filter(waiting_on_user=True)) == {waiting}
    assert set(annotated.filter(waiting_on_user=False)) == {
        no_turns,
        ready,
        errored,
        backlogged,
    }
    for session in annotated:
        assert bool(session.waiting_on_user) == session.is_waiting_on_user


@pytest.mark.django_db
def test_turn_defaults():
    turn = SpecTurnFactory()

    assert turn.kind == SpecTurnKind.CHAT
    assert turn.status == SpecTurnStatus.QUEUED
    assert turn.stage == turn.session.stage
    assert turn.claude_session_id is None
    assert turn.started_at is None
    assert turn.prompt_sent == ""
    assert turn.response == ""
    assert turn.raw_result == {}
    assert turn.cost_usd is None
    assert turn.artifacts == {}
    assert turn.error_detail == ""


@pytest.mark.django_db
def test_turns_ordered_by_creation():
    session = SpecSessionFactory()
    first = SpecTurnFactory(session=session)
    second = SpecTurnFactory(session=session)

    assert list(session.turns.all()) == [first, second]


@pytest.mark.django_db
def test_turns_deleted_with_issue():
    issue = IssueFactory()
    session = SpecSessionFactory(issue=issue)
    SpecTurnFactory(session=session)

    issue.delete()

    assert SpecSession.objects.count() == 0
    assert SpecTurn.objects.count() == 0


@pytest.mark.django_db
def test_turn_queue_logs_create_entry():
    turn = SpecTurnFactory(message="please explore PX-1", stage=SpecStage.EXPLORE)

    entries = list(turn.logged_actions())

    assert [e.action_type for e in entries] == ["pxtx.spec.turn.create"]
    entry = entries[0]
    assert entry.data["before"] == {}
    assert entry.data["after"]["kind"] == "chat"
    assert entry.data["after"]["stage"] == "explore"
    assert entry.data["after"]["status"] == "queued"
    assert entry.data["after"]["message"] == "please explore PX-1"


@pytest.mark.django_db
def test_turn_completion_logs_status_entry_with_cost():
    turn = SpecTurnFactory()
    run_session_id = uuid.uuid4()
    ActivityLog.objects.all().delete()

    turn.status = SpecTurnStatus.COMPLETED
    turn.cost_usd = Decimal("1.230000")
    turn.claude_session_id = run_session_id
    turn.response = "spec written"
    turn.save(actor="spec-worker")

    entry = turn.logged_actions().get()
    entry.refresh_from_db()
    assert entry.action_type == "pxtx.spec.turn.status.completed"
    assert entry.actor == "spec-worker"
    assert entry.data["before"] == {
        "status": "queued",
        "cost_usd": None,
        "claude_session_id": None,
    }
    assert entry.data["after"] == {
        "status": "completed",
        "cost_usd": "1.230000",
        "claude_session_id": str(run_session_id),
    }


@pytest.mark.django_db
def test_turn_error_logs_status_entry_with_detail():
    turn = SpecTurnFactory()
    ActivityLog.objects.all().delete()

    turn.status = SpecTurnStatus.ERROR
    turn.error_detail = "exit code 1, empty stdout"
    turn.save(actor="spec-worker")

    entry = turn.logged_actions().get()
    assert entry.action_type == "pxtx.spec.turn.status.error"
    assert entry.actor == "spec-worker"
    assert entry.data["before"] == {"status": "queued", "error_detail": ""}
    assert entry.data["after"] == {
        "status": "error",
        "error_detail": "exit code 1, empty stdout",
    }


@pytest.mark.django_db
def test_turn_non_status_update_logs_plain_update():
    turn = SpecTurnFactory(message="old message")
    ActivityLog.objects.all().delete()

    turn.message = "new message"
    turn.save()

    entry = turn.logged_actions().get()
    assert entry.action_type == "pxtx.spec.turn.update"
    assert entry.data["before"] == {"message": "old message"}
    assert entry.data["after"] == {"message": "new message"}


@pytest.mark.django_db
def test_session_fresh_claude_session_id_logs_plain_update():
    """Fresh-session recovery swaps the session-level claude id; that is an
    update entry, not a stage entry."""
    session = SpecSessionFactory()
    old_id = session.claude_session_id
    new_id = uuid.uuid4()
    ActivityLog.objects.all().delete()

    session.claude_session_id = new_id
    session.save(actor="spec-worker")

    entry = session.logged_actions().get()
    entry.refresh_from_db()
    assert entry.action_type == "pxtx.spec.session.update"
    assert entry.data["before"] == {"claude_session_id": str(old_id)}
    assert entry.data["after"] == {"claude_session_id": str(new_id)}
    assert entry.actor == "spec-worker"


@pytest.mark.django_db
def test_queue_turn_creates_queued_turn_with_stage_snapshot():
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    turn = session.queue_turn("Write the API section", actor="tobias")

    assert turn.session == session
    assert turn.kind == SpecTurnKind.CHAT
    assert turn.status == SpecTurnStatus.QUEUED
    assert turn.message == "Write the API section"
    assert turn.stage == SpecStage.PROPOSE
    assert turn.started_at is None
    entries = list(turn.logged_actions())
    assert [e.action_type for e in entries] == ["pxtx.spec.turn.create"]
    assert entries[0].actor == "tobias"


@pytest.mark.django_db
def test_queue_turn_on_session_without_turns_keeps_session_id():
    session = SpecSessionFactory()
    original = session.claude_session_id

    session.queue_turn("Start exploring")

    session.refresh_from_db()
    assert session.claude_session_id == original


@pytest.mark.django_db
def test_queue_turn_rotates_session_id_after_session_gone():
    session = SpecSessionFactory()
    original = session.claude_session_id
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.ERROR,
        started_at=timezone.now(),
        claude_session_id=original,
        raw_result={"exit_code": 1, "stderr": "No conversation found"},
    )

    turn = session.queue_turn("Try again", actor="tobias")

    session.refresh_from_db()
    assert session.claude_session_id != original
    assert turn.status == SpecTurnStatus.QUEUED
    update_entries = [
        e
        for e in session.logged_actions()
        if e.action_type == "pxtx.spec.session.update"
    ]
    assert len(update_entries) == 1
    assert update_entries[0].data["after"] == {
        "claude_session_id": str(session.claude_session_id)
    }


@pytest.mark.parametrize(
    "raw_result",
    (
        {},  # timeout class: session still resumable
        {"type": "result", "is_error": True, "errors": ["max turns"]},
    ),
)
@pytest.mark.django_db
def test_queue_turn_keeps_session_id_after_resumable_errors(raw_result):
    session = SpecSessionFactory()
    original = session.claude_session_id
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.ERROR,
        started_at=timezone.now(),
        claude_session_id=original,
        raw_result=raw_result,
    )

    session.queue_turn("Try again")

    session.refresh_from_db()
    assert session.claude_session_id == original


@pytest.mark.django_db
def test_queue_turn_critique_never_rotates_session_id():
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    original = session.claude_session_id
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.ERROR,
        started_at=timezone.now(),
        claude_session_id=original,
        raw_result={"exit_code": 1, "stderr": "gone"},
    )

    turn = session.queue_turn("Focus on the API", kind=SpecTurnKind.CRITIQUE)

    session.refresh_from_db()
    assert session.claude_session_id == original
    assert turn.kind == SpecTurnKind.CRITIQUE
    assert turn.stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_queue_turn_rotation_keys_on_latest_chat_turn_only():
    """A critique failing after a healthy chat turn says nothing about the
    chat session — no rotation."""
    session = SpecSessionFactory()
    original = session.claude_session_id
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        started_at=timezone.now(),
        claude_session_id=original,
        response="All good",
    )
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        status=SpecTurnStatus.ERROR,
        raw_result={"exit_code": 1, "stderr": "gone"},
    )

    session.queue_turn("Continue")

    session.refresh_from_db()
    assert session.claude_session_id == original


@pytest.mark.parametrize(
    ("kind", "status", "raw_result", "expected"),
    (
        (SpecTurnKind.CHAT, SpecTurnStatus.ERROR, {"exit_code": 1, "stderr": ""}, True),
        (SpecTurnKind.CHAT, SpecTurnStatus.ERROR, {}, False),
        (SpecTurnKind.CHAT, SpecTurnStatus.ERROR, {"is_error": True}, False),
        (
            SpecTurnKind.CHAT,
            SpecTurnStatus.COMPLETED,
            {"exit_code": 0, "stderr": ""},
            False,
        ),
        (
            SpecTurnKind.CRITIQUE,
            SpecTurnStatus.ERROR,
            {"exit_code": 1, "stderr": ""},
            False,
        ),
    ),
)
def test_is_session_gone_matrix(kind, status, raw_result, expected):
    turn = SpecTurn(kind=kind, status=status, raw_result=raw_result)

    assert turn.is_session_gone is expected


@pytest.mark.django_db
def test_latest_snapshot_empty_without_finished_turns():
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.QUEUED)

    assert session.latest_snapshot == {}


@pytest.mark.django_db
def test_latest_snapshot_skips_active_turns():
    """A freshly queued turn (empty snapshot by definition) must not hide
    the last finished turn's snapshot."""
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.QUEUED)

    assert session.latest_snapshot == {"proposal.md": "# Plan"}


@pytest.mark.django_db
def test_latest_snapshot_reflects_latest_finished_turn_even_when_empty():
    """An error turn whose snapshot came back empty (change dir deleted) is
    the truth about the disk — latest_snapshot must not fall back."""
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.ERROR, artifacts={})

    assert session.latest_snapshot == {}


@pytest.mark.django_db
def test_latest_nonempty_snapshot_falls_back_past_empty_snapshots():
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED, artifacts={})

    assert session.latest_nonempty_snapshot == {"proposal.md": "# Plan"}


@pytest.mark.django_db
def test_latest_nonempty_snapshot_empty_when_no_turn_produced_artifacts():
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED, artifacts={})

    assert session.latest_nonempty_snapshot == {}
