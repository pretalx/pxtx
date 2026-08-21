from decimal import Decimal

import pytest
from freezegun import freeze_time

from pxtx.core.models import (
    ActivityLog,
    SpecSession,
    SpecStage,
    SpecTurnKind,
    SpecTurnStatus,
    Status,
)
from tests.factories import (
    IssueFactory,
    MilestoneFactory,
    SpecSessionFactory,
    SpecTurnFactory,
)

pytestmark = pytest.mark.integration

POLL_MARKER = 'hx-trigger="every 10s"'


def _spec_url(session_or_issue, suffix=""):
    issue = getattr(session_or_issue, "issue", session_or_issue)
    return f"/issues/{issue.number}/spec/{suffix}"


# --- Spec page & bootstrap (3.1) ---


@pytest.mark.django_db
def test_spec_page_requires_login(client):
    issue = IssueFactory()

    response = client.get(_spec_url(issue))

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_spec_page_unknown_issue_404(auth_client):
    response = auth_client.get("/issues/999999/spec/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_spec_page_without_session_offers_bootstrap(auth_client):
    issue = IssueFactory()

    response = auth_client.get(_spec_url(issue))

    assert response.status_code == 200
    assert response.context["session"] is None
    body = response.content.decode()
    assert "Start spec session" in body
    assert f"/issues/{issue.number}/spec/start/" in body
    # No session means no composer and no transcript machinery.
    assert 'name="message"' not in body


@pytest.mark.django_db
def test_spec_start_creates_session_and_queues_explore_turn(auth_client):
    issue = IssueFactory()

    response = auth_client.post(_spec_url(issue, "start/"))

    assert response.status_code == 302
    assert response.url == _spec_url(issue)
    session = SpecSession.objects.get(issue=issue)
    assert session.stage == SpecStage.EXPLORE
    turns = list(session.turns.all())
    assert [t.message for t in turns] == ["/opsx:explore"]
    assert turns[0].status == SpecTurnStatus.QUEUED
    assert turns[0].kind == SpecTurnKind.CHAT
    assert turns[0].stage == SpecStage.EXPLORE


@pytest.mark.django_db
def test_spec_start_logs_creation_and_queue_with_user_actor(auth_client):
    issue = IssueFactory()

    auth_client.post(_spec_url(issue, "start/"))

    session = SpecSession.objects.get(issue=issue)
    session_entries = list(session.logged_actions())
    assert [e.action_type for e in session_entries] == ["pxtx.spec.session.create"]
    assert session_entries[0].actor.startswith("user/")
    turn_entries = list(session.turns.get().logged_actions())
    assert [e.action_type for e in turn_entries] == ["pxtx.spec.turn.create"]


@pytest.mark.django_db
def test_spec_start_on_existing_session_is_a_noop(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    response = auth_client.post(_spec_url(session, "start/"))

    assert response.status_code == 302
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    assert SpecSession.objects.count() == 1
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_spec_page_renders_transcript_bubbles(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        message="Please explore PX auth",
        status=SpecTurnStatus.COMPLETED,
        response="I looked at **auth** and found things.",
    )

    response = auth_client.get(_spec_url(session))

    assert response.status_code == 200
    assert response.context["session"] == session
    body = response.content.decode()
    assert "Please explore PX auth" in body
    # The response runs through the markdown pipeline.
    assert "<strong>auth</strong>" in body
    assert 'name="message"' in body


@pytest.mark.django_db
def test_spec_page_shows_total_cost(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="ok",
        cost_usd=Decimal("1.25"),
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="ok",
        cost_usd=Decimal("0.50"),
    )

    response = auth_client.get(_spec_url(session))

    assert response.context["total_cost"] == Decimal("1.75")
    assert "$1.75" in response.content.decode()


@pytest.mark.django_db
def test_issue_detail_links_to_spec_page(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/")

    assert _spec_url(issue) in response.content.decode()


# --- Reset ---


@pytest.mark.django_db
def test_spec_reset_replaces_session_with_fresh_explore_one(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)
    issue = session.issue
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Thrown out"},
    )

    response = auth_client.post(_spec_url(issue, "reset/"))

    assert response.status_code == 302
    assert response.url == _spec_url(issue)
    fresh = SpecSession.objects.get(issue=issue)
    assert SpecSession.objects.count() == 1
    assert fresh.pk != session.pk
    assert fresh.stage == SpecStage.EXPLORE
    assert fresh.claude_session_id != session.claude_session_id
    assert fresh.latest_snapshot == {}
    turns = list(fresh.turns.all())
    assert [t.message for t in turns] == ["/opsx:explore"]
    assert turns[0].status == SpecTurnStatus.QUEUED


@pytest.mark.django_db
def test_spec_reset_logs_delete_and_create_with_user_actor(auth_client):
    session = SpecSessionFactory()

    auth_client.post(_spec_url(session, "reset/"))

    deleted = ActivityLog.objects.get(action_type="pxtx.spec.session.delete")
    assert deleted.object_id == session.pk
    assert deleted.actor.startswith("user/")
    assert deleted.data["before"]["stage"] == SpecStage.EXPLORE
    fresh = SpecSession.objects.get(issue=session.issue)
    assert [e.action_type for e in fresh.logged_actions()] == [
        "pxtx.spec.session.create"
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("status", (SpecTurnStatus.QUEUED, SpecTurnStatus.RUNNING))
def test_spec_reset_refused_while_a_turn_is_active(auth_client, status):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=status)

    response = auth_client.post(_spec_url(session, "reset/"))

    assert response.status_code == 400
    assert b"queued or running" in response.content
    assert SpecSession.objects.get() == session


@pytest.mark.django_db
def test_spec_page_offers_reset_only_without_an_active_turn(auth_client):
    session = SpecSessionFactory()
    turn = SpecTurnFactory(session=session, status=SpecTurnStatus.QUEUED)

    body = auth_client.get(_spec_url(session)).content.decode()
    assert _spec_url(session, "reset/") not in body

    turn.status = SpecTurnStatus.COMPLETED
    turn.save()

    body = auth_client.get(_spec_url(session)).content.decode()
    assert _spec_url(session, "reset/") in body


# --- Turn queueing + polling (3.2) ---


@pytest.mark.django_db
def test_queue_message_creates_queued_turn_and_returns_fragment(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(
        _spec_url(session, "turns/"),
        {"message": "Look at the settings module"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "core/_spec_session.html" in [t.name for t in response.templates]
    turns = list(session.turns.all())
    assert [t.message for t in turns] == ["Look at the settings module"]
    assert turns[0].status == SpecTurnStatus.QUEUED
    assert turns[0].stage == SpecStage.EXPLORE
    assert "Look at the settings module" in response.content.decode()


@pytest.mark.django_db
def test_queue_message_without_htmx_redirects_to_spec_page(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(_spec_url(session, "turns/"), {"message": "hi"})

    assert response.status_code == 302
    assert response.url == _spec_url(session)
    assert session.turns.count() == 1


@pytest.mark.django_db
def test_queue_empty_message_rejected(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(_spec_url(session, "turns/"), {"message": "   "})

    assert response.status_code == 400
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_queue_message_on_ready_session_rejected(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)

    response = auth_client.post(_spec_url(session, "turns/"), {"message": "hi"})

    assert response.status_code == 400
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_queue_message_without_session_404(auth_client):
    issue = IssueFactory()

    response = auth_client.post(_spec_url(issue, "turns/"), {"message": "hi"})

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "polls"),
    (
        (SpecTurnStatus.QUEUED, True),
        (SpecTurnStatus.RUNNING, True),
        (SpecTurnStatus.COMPLETED, False),
        (SpecTurnStatus.ERROR, False),
    ),
)
def test_spec_page_polls_only_while_turn_active(auth_client, status, polls):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=status)

    response = auth_client.get(_spec_url(session))

    assert (POLL_MARKER in response.content.decode()) is polls


@pytest.mark.django_db
def test_spec_page_without_turns_does_not_poll(auth_client):
    session = SpecSessionFactory()

    response = auth_client.get(_spec_url(session))

    assert POLL_MARKER not in response.content.decode()


@pytest.mark.django_db
def test_session_fragment_endpoint_renders_fragment(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, message="ping", status=SpecTurnStatus.RUNNING)

    response = auth_client.get(_spec_url(session, "session/"))

    assert response.status_code == 200
    assert "core/_spec_session.html" in [t.name for t in response.templates]
    body = response.content.decode()
    assert "ping" in body
    assert POLL_MARKER in body


@pytest.mark.django_db
def test_session_fragment_marks_user_inputs_preserved(auth_client):
    """Timed poll responses swap the whole fragment, so they mark the
    composer and the critique panel hx-preserve — a draft being typed
    survives the background swap."""
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.RUNNING)

    response = auth_client.get(_spec_url(session, "session/"))

    body = response.content.decode()
    assert body.count("hx-preserve") == 2
    assert 'id="spec-composer-message"' in body
    assert 'id="spec-critique-request"' in body


@pytest.mark.django_db
def test_user_action_swap_does_not_preserve_inputs(auth_client):
    """Responses to user actions omit hx-preserve, so queueing a message
    replaces (and thereby clears) the composer."""
    session = SpecSessionFactory()

    response = auth_client.post(
        _spec_url(session, "turns/"), {"message": "hi"}, HTTP_HX_REQUEST="true"
    )

    body = response.content.decode()
    assert "hx-preserve" not in body
    assert 'id="spec-composer-message"' in body


@pytest.mark.django_db
def test_spec_page_render_does_not_preserve_inputs(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(session=session, status=SpecTurnStatus.RUNNING)

    response = auth_client.get(_spec_url(session))

    assert "hx-preserve" not in response.content.decode()


@pytest.mark.django_db
def test_session_fragment_without_session_404(auth_client):
    issue = IssueFactory()

    response = auth_client.get(_spec_url(issue, "session/"))

    assert response.status_code == 404


# --- Artifact diffs (3.3) ---


@pytest.mark.django_db
def test_first_snapshot_diffs_against_empty(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="wrote the proposal",
        artifacts={"proposal.md": "# Proposal\nline"},
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "1 file changed" in body
    assert "+# Proposal" in body


@pytest.mark.django_db
def test_changed_files_summarized_and_expandable(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v1",
        artifacts={
            "proposal.md": "old text",
            "design.md": "unchanged",
            "tasks.md": "a",
        },
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v2",
        artifacts={"proposal.md": "new text", "design.md": "unchanged"},
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "2 files changed" in body
    assert "-old text" in body
    assert "+new text" in body
    # The deleted file shows up in the diff too.
    assert "-a" in body
    entries = response.context["entries"]
    assert [d["path"] for d in entries[1]["diffs"]] == ["proposal.md", "tasks.md"]
    # The unchanged file produces no diff entry.
    assert entries[1]["diffs"][0]["path"] != "design.md"


@pytest.mark.django_db
def test_unchanged_snapshot_shows_no_diff_summary(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v1",
        artifacts={"proposal.md": "same"},
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v2",
        artifacts={"proposal.md": "same"},
    )

    response = auth_client.get(_spec_url(session))

    entries = response.context["entries"]
    assert entries[1]["diffs"] == []
    # Only the first turn (diffed against empty) shows a summary.
    assert entries[0]["diffs"] != []
    assert response.content.decode().count("file changed") == 1


@pytest.mark.django_db
def test_error_turn_snapshot_advances_diff_baseline(auth_client):
    """An error turn still snapshots artifacts; the next completed turn
    diffs against that, not against the last completed one."""
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.ERROR,
        artifacts={"proposal.md": "written before the crash"},
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="done",
        artifacts={"proposal.md": "written before the crash"},
    )

    response = auth_client.get(_spec_url(session))

    entries = response.context["entries"]
    assert entries[0]["diffs"] == []  # error turns render no diff summary
    assert entries[1]["diffs"] == []


# --- Push turns in the transcript (add-spec-push 4.x) ---


@pytest.mark.django_db
def test_push_turn_renders_distinctly_with_actor_file_count_and_note(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        actor="claude-add-foo",
        message="local draft, please critique",
        artifacts={"proposal.md": "# P", "design.md": "# D", "tasks.md": "# T"},
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "spec-bubble-push" in body
    assert "Spec pushed by claude-add-foo" in body
    assert "3 files" in body
    assert "local draft, please critique" in body
    # The push diffs against the previous (here: empty) snapshot.
    assert "3 files changed" in body
    assert "+# P" in body


@pytest.mark.django_db
def test_push_turn_without_actor_or_note_renders_fallback_label_only(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        message="",
        artifacts={"proposal.md": "# P"},
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "unknown actor" in body
    assert "1 file</span>" in body
    # No note means no prose block inside the push entry (and the push is
    # the only turn, so none anywhere).
    assert 'class="prose"' not in body


@pytest.mark.django_db
def test_push_turn_offers_no_retry_or_forward_affordance(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        actor="claude-x",
        artifacts={"proposal.md": "# P"},
    )

    body = auth_client.get(_spec_url(session)).content.decode()

    assert "Retry" not in body
    assert "Forward to spec agent" not in body


@pytest.mark.django_db
def test_push_diffs_against_previous_finished_snapshot(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v1",
        artifacts={"proposal.md": "old text"},
    )
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        actor="claude-x",
        artifacts={"proposal.md": "pushed text"},
    )

    response = auth_client.get(_spec_url(session))

    entries = response.context["entries"]
    assert [d["path"] for d in entries[1]["diffs"]] == ["proposal.md"]
    body = response.content.decode()
    assert "-old text" in body
    assert "+pushed text" in body


@pytest.mark.django_db
def test_diff_baseline_advances_through_a_push(auth_client):
    """The chat turn after a push diffs against the pushed snapshot, not
    the pre-push one."""
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v1",
        artifacts={"proposal.md": "claude text"},
    )
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        actor="claude-x",
        artifacts={"proposal.md": "pushed text"},
    )
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="v2",
        artifacts={"proposal.md": "pushed text", "design.md": "new"},
    )

    response = auth_client.get(_spec_url(session))

    entries = response.context["entries"]
    # Only the file claude added after the push shows up — proposal.md is
    # unchanged relative to the pushed state.
    assert [d["path"] for d in entries[2]["diffs"]] == ["design.md"]


@pytest.mark.django_db
def test_spec_list_shows_waiting_after_push(auth_client):
    """A completed push turn makes the session waiting-on-you: an unflagged
    pushed spec is exactly what the user should review or mark ready."""
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        actor="claude-x",
        artifacts={"proposal.md": "# P"},
    )

    response = auth_client.get("/specs/")

    (listed,) = response.context["sessions"]
    assert listed.state == "waiting"
    assert "Waiting on you" in response.content.decode()


# --- Current spec view (3.4) ---


@pytest.mark.django_db
def test_current_spec_renders_latest_snapshot_as_markdown(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Big Plan", "specs/api.md": "endpoints"},
    )

    response = auth_client.get(_spec_url(session, "current/"))

    assert response.status_code == 200
    assert response.context["files"] == ["proposal.md", "specs/api.md"]
    assert response.context["selected"] == "proposal.md"
    body = response.content.decode()
    assert "<h1>Big Plan</h1>" in body
    assert "specs/api.md" in body


@pytest.mark.django_db
def test_current_spec_navigates_per_file(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Big Plan", "specs/api.md": "*endpoints*"},
    )

    response = auth_client.get(_spec_url(session, "current/"), {"file": "specs/api.md"})

    assert response.context["selected"] == "specs/api.md"
    assert "<em>endpoints</em>" in response.content.decode()


@pytest.mark.django_db
def test_current_spec_unknown_file_404(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Big Plan"},
    )

    response = auth_client.get(_spec_url(session, "current/"), {"file": "nope.md"})

    assert response.status_code == 404


@pytest.mark.django_db
def test_current_spec_without_artifacts_shows_empty_state(auth_client):
    session = SpecSessionFactory()

    response = auth_client.get(_spec_url(session, "current/"))

    assert response.status_code == 200
    assert response.context["files"] == []
    assert "No spec artifacts yet" in response.content.decode()


@pytest.mark.django_db
def test_current_spec_uses_latest_nonempty_snapshot(auth_client):
    """A later empty snapshot (deleted change dir) must not blank the view."""
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "survives"},
    )
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED, artifacts={})

    response = auth_client.get(_spec_url(session, "current/"))

    assert response.context["files"] == ["proposal.md"]
    assert "survives" in response.content.decode()


# --- Stage buttons (3.5) ---


@pytest.mark.django_db
def test_explore_page_offers_propose_only(auth_client):
    session = SpecSessionFactory()

    body = auth_client.get(_spec_url(session)).content.decode()

    assert 'value="propose"' in body
    assert 'value="ready"' not in body
    assert 'value="explore"' not in body


@pytest.mark.django_db
def test_propose_page_offers_back_to_explore_and_ready(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    body = auth_client.get(_spec_url(session)).content.decode()

    assert 'value="explore"' in body
    assert 'value="ready"' in body


@pytest.mark.django_db
def test_ready_page_is_read_only_with_reopen(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)

    body = auth_client.get(_spec_url(session)).content.decode()

    assert 'name="message"' not in body
    assert "Reopen" in body
    assert 'value="propose"' in body


@pytest.mark.django_db
def test_propose_button_changes_stage_and_queues_opsx_turn(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(
        _spec_url(session, "stage/"), {"stage": "propose"}, HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    turns = list(session.turns.all())
    assert [t.message for t in turns] == ["/opsx:propose"]
    assert turns[0].status == SpecTurnStatus.QUEUED
    assert turns[0].stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_propose_button_carries_a_composer_message(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(
        _spec_url(session, "stage/"),
        {"stage": "propose", "message": "Skip the migration, PX-3 covers it."},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    turns = list(session.turns.all())
    assert [t.message for t in turns] == [
        "/opsx:propose\n\nSkip the migration, PX-3 covers it."
    ]
    assert turns[0].stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_propose_button_ignores_a_blank_composer_message(auth_client):
    session = SpecSessionFactory()

    auth_client.post(_spec_url(session, "stage/"), {"stage": "propose", "message": " "})

    assert [t.message for t in session.turns.all()] == ["/opsx:propose"]


@pytest.mark.django_db
def test_mark_ready_drops_a_message_because_it_queues_no_turn(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    auth_client.post(
        _spec_url(session, "stage/"), {"stage": "ready", "message": "ship it"}
    )

    session.refresh_from_db()
    assert session.stage == SpecStage.READY
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_back_to_explore_button_carries_a_composer_message(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    auth_client.post(
        _spec_url(session, "stage/"),
        {"stage": "explore", "message": "Too much guessing, dig into the model first."},
    )

    session.refresh_from_db()
    assert session.stage == SpecStage.EXPLORE
    turns = list(session.turns.all())
    assert [t.message for t in turns] == [
        "/opsx:explore\n\nToo much guessing, dig into the model first."
    ]
    assert turns[0].stage == SpecStage.EXPLORE


@pytest.mark.django_db
def test_explore_composer_offers_send_and_propose(auth_client):
    session = SpecSessionFactory()

    body = auth_client.get(_spec_url(session)).content.decode()

    assert "Send and propose" in body
    assert "Send and back to explore" not in body


@pytest.mark.django_db
def test_propose_composer_offers_send_and_back_to_explore(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    body = auth_client.get(_spec_url(session)).content.decode()

    assert "Send and back to explore" in body
    assert "Send and propose" not in body


@pytest.mark.django_db
def test_back_to_explore_queues_explore_turn(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    response = auth_client.post(_spec_url(session, "stage/"), {"stage": "explore"})

    assert response.status_code == 302
    session.refresh_from_db()
    assert session.stage == SpecStage.EXPLORE
    assert [t.message for t in session.turns.all()] == ["/opsx:explore"]


@pytest.mark.django_db
def test_mark_ready_queues_nothing(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    response = auth_client.post(_spec_url(session, "stage/"), {"stage": "ready"})

    assert response.status_code == 302
    session.refresh_from_db()
    assert session.stage == SpecStage.READY
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_mark_ready_never_touches_the_issue(auth_client):
    issue = IssueFactory(status=Status.OPEN)
    session = SpecSessionFactory(issue=issue, stage=SpecStage.PROPOSE)

    auth_client.post(_spec_url(session, "stage/"), {"stage": "ready"})

    issue.refresh_from_db()
    assert issue.status == Status.OPEN


@pytest.mark.django_db
def test_reopen_queues_nothing(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)

    response = auth_client.post(_spec_url(session, "stage/"), {"stage": "propose"})

    assert response.status_code == 302
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_invalid_stage_transition_rejected(auth_client):
    session = SpecSessionFactory()  # explore

    response = auth_client.post(_spec_url(session, "stage/"), {"stage": "ready"})

    assert response.status_code == 400
    session.refresh_from_db()
    assert session.stage == SpecStage.EXPLORE
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_unknown_stage_value_rejected(auth_client):
    session = SpecSessionFactory()

    response = auth_client.post(_spec_url(session, "stage/"), {"stage": "shipped"})

    assert response.status_code == 400
    session.refresh_from_db()
    assert session.stage == SpecStage.EXPLORE


# --- Error display + retry (3.5) ---


@pytest.mark.django_db
def test_error_turn_marked_with_diagnostics(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        message="broken run",
        status=SpecTurnStatus.ERROR,
        error_detail="claude was killed after exceeding the 3600s timeout.",
        raw_result={"is_error": True, "subtype": "error_max_turns"},
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "This turn failed." in body
    assert "exceeding the 3600s timeout" in body
    assert "error_max_turns" in body
    assert "Retry" in body
    # A resumable error is not the session-gone class.
    assert "session was lost" not in body


@pytest.mark.django_db
def test_session_gone_error_shows_fresh_start_hint(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.ERROR,
        raw_result={"exit_code": 1, "stderr": "No conversation found"},
    )

    response = auth_client.get(_spec_url(session))

    assert "session was lost" in response.content.decode()


@pytest.mark.django_db
def test_retry_queues_new_turn_with_failed_turns_message(auth_client):
    session = SpecSessionFactory()
    failed = SpecTurnFactory(
        session=session, message="try this", status=SpecTurnStatus.ERROR
    )

    response = auth_client.post(
        _spec_url(session, f"turns/{failed.pk}/retry/"), HTTP_HX_REQUEST="true"
    )

    assert response.status_code == 200
    turns = list(session.turns.all())
    assert len(turns) == 2
    retry = turns[1]
    assert retry.message == "try this"
    assert retry.kind == SpecTurnKind.CHAT
    assert retry.status == SpecTurnStatus.QUEUED


@pytest.mark.django_db
def test_retry_of_failed_critique_queues_critique(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    failed = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        message="focus here",
        status=SpecTurnStatus.ERROR,
    )

    auth_client.post(_spec_url(session, f"turns/{failed.pk}/retry/"))

    retry = session.turns.exclude(pk=failed.pk).get()
    assert retry.kind == SpecTurnKind.CRITIQUE
    assert retry.message == "focus here"


@pytest.mark.django_db
def test_retry_of_chat_turn_rejected_on_ready_session(auth_client):
    """Ready is read-only for the chat: retrying a failed chat turn is
    gated exactly like the composer, and needs a reopen first."""
    session = SpecSessionFactory(stage=SpecStage.READY)
    failed = SpecTurnFactory(
        session=session, message="try this", status=SpecTurnStatus.ERROR
    )

    response = auth_client.post(_spec_url(session, f"turns/{failed.pk}/retry/"))

    assert response.status_code == 400
    assert session.turns.count() == 1


@pytest.mark.django_db
def test_retry_of_failed_critique_allowed_on_ready_session(auth_client):
    """Critiques are explicitly offered in ready, so retrying a failed one
    stays allowed there."""
    session = SpecSessionFactory(stage=SpecStage.READY)
    failed = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        message="focus here",
        status=SpecTurnStatus.ERROR,
    )

    response = auth_client.post(_spec_url(session, f"turns/{failed.pk}/retry/"))

    assert response.status_code == 302
    retry = session.turns.exclude(pk=failed.pk).get()
    assert retry.kind == SpecTurnKind.CRITIQUE
    assert retry.status == SpecTurnStatus.QUEUED


@pytest.mark.django_db
def test_ready_page_hides_retry_for_failed_chat_turn(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(session=session, message="broken", status=SpecTurnStatus.ERROR)

    body = auth_client.get(_spec_url(session)).content.decode()

    assert "This turn failed." in body
    assert "Retry" not in body


@pytest.mark.django_db
def test_ready_page_offers_retry_for_failed_critique(auth_client):
    session = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(
        session=session, kind=SpecTurnKind.CRITIQUE, status=SpecTurnStatus.ERROR
    )

    body = auth_client.get(_spec_url(session)).content.decode()

    assert "Retry" in body


@pytest.mark.django_db
def test_retry_of_non_error_turn_404(auth_client):
    session = SpecSessionFactory()
    turn = SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED)

    response = auth_client.post(_spec_url(session, f"turns/{turn.pk}/retry/"))

    assert response.status_code == 404
    assert session.turns.count() == 1


# --- Critique UI (3.5b) ---


def _proposed_session_with_spec(**session_kwargs):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE, **session_kwargs)
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        response="proposal written",
        artifacts={"proposal.md": "# Plan"},
    )
    return session


@pytest.mark.django_db
def test_critique_action_offered_in_propose_with_artifacts(auth_client):
    session = _proposed_session_with_spec()

    response = auth_client.get(_spec_url(session))

    assert response.context["can_critique"] is True
    assert "Request critique" in response.content.decode()


@pytest.mark.django_db
def test_critique_action_offered_in_ready_with_artifacts(auth_client):
    session = _proposed_session_with_spec()
    session.change_stage(SpecStage.READY)

    response = auth_client.get(_spec_url(session))

    assert response.context["can_critique"] is True


@pytest.mark.django_db
def test_no_critique_action_without_artifacts(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED, artifacts={})

    response = auth_client.get(_spec_url(session))

    assert response.context["can_critique"] is False
    assert "Request critique" not in response.content.decode()


@pytest.mark.django_db
def test_no_critique_action_in_explore_even_with_artifacts(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )

    response = auth_client.get(_spec_url(session))

    assert response.context["can_critique"] is False


@pytest.mark.django_db
def test_request_critique_queues_critique_turn_with_focus(auth_client):
    session = _proposed_session_with_spec()

    response = auth_client.post(
        _spec_url(session, "critique/"),
        {"focus": "poke holes in the migration plan"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    critique = session.turns.get(kind=SpecTurnKind.CRITIQUE)
    assert critique.message == "poke holes in the migration plan"
    assert critique.status == SpecTurnStatus.QUEUED
    assert critique.stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_request_critique_focus_is_optional(auth_client):
    session = _proposed_session_with_spec()

    response = auth_client.post(_spec_url(session, "critique/"))

    assert response.status_code == 302
    critique = session.turns.get(kind=SpecTurnKind.CRITIQUE)
    assert critique.message == ""


@pytest.mark.django_db
def test_request_critique_rejected_in_explore(auth_client):
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.COMPLETED,
        artifacts={"proposal.md": "# Plan"},
    )

    response = auth_client.post(_spec_url(session, "critique/"))

    assert response.status_code == 400
    assert session.turns.filter(kind=SpecTurnKind.CRITIQUE).count() == 0


@pytest.mark.django_db
def test_request_critique_rejected_without_artifacts(auth_client):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)

    response = auth_client.post(_spec_url(session, "critique/"))

    assert response.status_code == 400
    assert session.turns.count() == 0


@pytest.mark.django_db
def test_critique_turn_renders_distinctly_with_forward_button(auth_client):
    session = _proposed_session_with_spec()
    critique = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        message="focus on auth",
        status=SpecTurnStatus.COMPLETED,
        response="The spec ignores token expiry.",
    )

    response = auth_client.get(_spec_url(session))

    body = response.content.decode()
    assert "spec-bubble-critique" in body
    assert "Forward to spec agent" in body
    assert f"turns/{critique.pk}/forward/" in body


@pytest.mark.django_db
def test_incomplete_critique_offers_no_forward_button(auth_client):
    session = _proposed_session_with_spec()
    SpecTurnFactory(
        session=session, kind=SpecTurnKind.CRITIQUE, status=SpecTurnStatus.RUNNING
    )

    response = auth_client.get(_spec_url(session))

    assert "Forward to spec agent" not in response.content.decode()


@pytest.mark.django_db
def test_forward_prefills_composer_with_critique_text(auth_client):
    session = _proposed_session_with_spec()
    critique = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        status=SpecTurnStatus.COMPLETED,
        response="The spec ignores token expiry.",
    )

    response = auth_client.post(
        _spec_url(session, f"turns/{critique.pk}/forward/"), follow=True
    )

    assert response.status_code == 200
    assert response.context["composer_prefill"] == "The spec ignores token expiry."
    assert "The spec ignores token expiry." in response.content.decode()
    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE


@pytest.mark.django_db
def test_forward_from_ready_reopens_to_propose(auth_client):
    session = _proposed_session_with_spec()
    critique = SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        status=SpecTurnStatus.COMPLETED,
        response="Needs work.",
    )
    session.change_stage(SpecStage.READY)

    response = auth_client.post(
        _spec_url(session, f"turns/{critique.pk}/forward/"), follow=True
    )

    session.refresh_from_db()
    assert session.stage == SpecStage.PROPOSE
    assert response.context["composer_prefill"] == "Needs work."
    # No turn was queued by forwarding itself.
    assert session.turns.count() == 2


@pytest.mark.django_db
def test_forward_of_non_critique_turn_404(auth_client):
    session = _proposed_session_with_spec()
    chat = session.turns.get()

    response = auth_client.post(_spec_url(session, f"turns/{chat.pk}/forward/"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_forward_query_param_with_unknown_pk_leaves_composer_empty(auth_client):
    session = _proposed_session_with_spec()

    response = auth_client.get(_spec_url(session), {"forward": "999999"})

    assert response.context["composer_prefill"] == ""


@pytest.mark.django_db
def test_forward_query_param_with_garbage_leaves_composer_empty(auth_client):
    session = _proposed_session_with_spec()

    response = auth_client.get(_spec_url(session), {"forward": "abc"})

    assert response.context["composer_prefill"] == ""


# --- /specs/ list view (3.6) ---


@pytest.mark.django_db
def test_spec_list_requires_login(client):
    response = client.get("/specs/")

    assert response.status_code == 302
    assert response.url.startswith("/login/")


@pytest.mark.django_db
def test_spec_list_empty_state(auth_client):
    response = auth_client.get("/specs/")

    assert response.status_code == 200
    assert response.context["sessions"] == []
    assert "No spec sessions yet" in response.content.decode()


@pytest.mark.django_db
def test_spec_list_highlights_waiting_and_shows_running(auth_client):
    waiting = SpecSessionFactory()
    SpecTurnFactory(session=waiting, status=SpecTurnStatus.COMPLETED)
    running = SpecSessionFactory()
    SpecTurnFactory(session=running, status=SpecTurnStatus.RUNNING)

    response = auth_client.get("/specs/")

    states = {s.pk: s.state for s in response.context["sessions"]}
    assert states == {waiting.pk: "waiting", running.pk: "running"}
    body = response.content.decode()
    assert "Waiting on you" in body
    assert "spec-state-waiting" in body
    assert "spec-state-running" in body


@pytest.mark.django_db
def test_spec_list_orders_waiting_sessions_first(auth_client):
    running = SpecSessionFactory()
    SpecTurnFactory(session=running, status=SpecTurnStatus.RUNNING)
    waiting = SpecSessionFactory()
    SpecTurnFactory(session=waiting, status=SpecTurnStatus.COMPLETED)

    response = auth_client.get("/specs/")

    assert [s.pk for s in response.context["sessions"]] == [waiting.pk, running.pk]


@pytest.mark.django_db
def test_spec_list_orders_by_latest_turn_within_group(auth_client):
    """A completing turn floats its session to the top of its group."""
    with freeze_time("2026-04-22 12:00:00"):
        stale = SpecSessionFactory()
        SpecTurnFactory(session=stale, status=SpecTurnStatus.COMPLETED)
        fresh = SpecSessionFactory()
    with freeze_time("2026-04-22 13:00:00"):
        SpecTurnFactory(session=fresh, status=SpecTurnStatus.COMPLETED)

    response = auth_client.get("/specs/")

    assert [s.pk for s in response.context["sessions"]] == [fresh.pk, stale.pk]


@pytest.mark.django_db
def test_spec_list_orders_turnless_sessions_by_own_timestamp(auth_client):
    with freeze_time("2026-04-22 12:00:00"):
        older = SpecSessionFactory()
    with freeze_time("2026-04-22 13:00:00"):
        newer = SpecSessionFactory()

    response = auth_client.get("/specs/")

    assert [s.pk for s in response.context["sessions"]] == [newer.pk, older.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stage", "turn_kwargs", "expected"),
    (
        (SpecStage.EXPLORE, {"status": SpecTurnStatus.QUEUED}, "queued"),
        (SpecStage.EXPLORE, {"status": SpecTurnStatus.RUNNING}, "running"),
        (SpecStage.EXPLORE, {"status": SpecTurnStatus.ERROR}, "error"),
        (SpecStage.EXPLORE, {"status": SpecTurnStatus.COMPLETED}, "waiting"),
        (SpecStage.READY, {"status": SpecTurnStatus.COMPLETED}, "ready"),
        (SpecStage.EXPLORE, None, "new"),
    ),
)
def test_spec_list_state_badges(auth_client, stage, turn_kwargs, expected):
    session = SpecSessionFactory(stage=stage)
    if turn_kwargs:
        SpecTurnFactory(session=session, **turn_kwargs)

    response = auth_client.get("/specs/")

    (listed,) = response.context["sessions"]
    assert listed.state == expected
    assert f"spec-state-{expected}" in response.content.decode()


@pytest.mark.django_db
def test_spec_list_error_beats_ready_stage(auth_client):
    """A failed critique on a ready session must scream, not show ready."""
    session = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(
        session=session, kind=SpecTurnKind.CRITIQUE, status=SpecTurnStatus.ERROR
    )

    response = auth_client.get("/specs/")

    (listed,) = response.context["sessions"]
    assert listed.state == "error"


@pytest.mark.django_db
def test_spec_list_shows_costs_and_issue_reference(auth_client):
    session = SpecSessionFactory(issue=IssueFactory(title="Auth overhaul"))
    SpecTurnFactory(
        session=session, status=SpecTurnStatus.COMPLETED, cost_usd=Decimal("2.50")
    )
    SpecTurnFactory(
        session=session, status=SpecTurnStatus.COMPLETED, cost_usd=Decimal("1.25")
    )

    response = auth_client.get("/specs/")

    (listed,) = response.context["sessions"]
    assert listed.total_cost == Decimal("3.75")
    body = response.content.decode()
    assert "$3.75" in body
    assert "Auth overhaul" in body
    assert session.issue.slug in body
    assert _spec_url(session) in body


@pytest.mark.django_db
def test_spec_list_shows_issue_status_badge(auth_client):
    SpecSessionFactory(issue=IssueFactory(status=Status.BLOCKED))

    response = auth_client.get("/specs/")

    body = response.content.decode()
    assert f'<span class="badge status-{Status.BLOCKED}">Blocked</span>' in body


@pytest.mark.django_db
def test_spec_list_hides_completed_issues(auth_client):
    SpecSessionFactory(issue=IssueFactory(status=Status.COMPLETED))
    open_session = SpecSessionFactory(issue=IssueFactory(status=Status.BLOCKED))

    response = auth_client.get("/specs/")

    assert [s.pk for s in response.context["sessions"]] == [open_session.pk]


@pytest.mark.django_db
def test_spec_list_parks_ready_sessions_at_the_bottom(auth_client):
    ready = SpecSessionFactory(stage=SpecStage.READY)
    SpecTurnFactory(session=ready, status=SpecTurnStatus.COMPLETED)
    waiting = SpecSessionFactory()
    SpecTurnFactory(session=waiting, status=SpecTurnStatus.COMPLETED)
    new = SpecSessionFactory()

    response = auth_client.get("/specs/")

    assert [s.pk for s in response.context["sessions"]] == [
        waiting.pk,
        new.pk,
        ready.pk,
    ]


@pytest.mark.django_db
def test_spec_list_shows_release(auth_client):
    milestone = MilestoneFactory(name="v2.0")
    SpecSessionFactory(issue=IssueFactory(milestone=milestone))
    SpecSessionFactory(issue=IssueFactory(milestone=None))

    response = auth_client.get("/specs/")

    body = response.content.decode()
    assert f'<a href="{milestone.get_absolute_url()}">v2.0</a>' in body
    assert "<td>—</td>" in body


@pytest.mark.django_db
def test_spec_list_capitalizes_state_labels(auth_client):
    SpecSessionFactory(stage=SpecStage.EXPLORE)

    response = auth_client.get("/specs/")

    body = response.content.decode()
    assert '<span class="badge spec-state spec-state-new">New</span>' in body


@pytest.mark.django_db
@pytest.mark.parametrize("item_count", (1, 3))
def test_spec_list_query_count_is_constant(
    auth_client, django_assert_num_queries, item_count
):
    for _ in range(item_count):
        session = SpecSessionFactory()
        SpecTurnFactory(session=session, status=SpecTurnStatus.COMPLETED)

    with django_assert_num_queries(3):
        response = auth_client.get("/specs/")

    assert len(response.context["sessions"]) == item_count


# --- Issue table indicator (3.7) ---


@pytest.mark.django_db
def test_issue_table_shows_in_progress_spec_pill(auth_client):
    issue = IssueFactory()
    SpecSessionFactory(issue=issue)

    response = auth_client.get("/issues/")

    body = response.content.decode()
    assert "spec-pill-progress" in body
    assert "spec-pill-ready" not in body
    assert _spec_url(issue) in body


@pytest.mark.django_db
def test_issue_table_shows_ready_spec_pill(auth_client):
    issue = IssueFactory()
    SpecSessionFactory(issue=issue, stage=SpecStage.READY)

    response = auth_client.get("/issues/")

    body = response.content.decode()
    assert "spec-pill-ready" in body
    assert "spec-pill-progress" not in body


@pytest.mark.django_db
def test_issue_table_shows_no_spec_pill_without_session(auth_client):
    IssueFactory()

    response = auth_client.get("/issues/")

    assert "spec-pill" not in response.content.decode()
