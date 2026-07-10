import io
import json
import logging
import subprocess
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.utils import timezone

from pxtx.core.management.commands import runworker as runworker_module
from pxtx.core.models import (
    SpecStage,
    SpecTurn,
    SpecTurnKind,
    SpecTurnStatus,
    push_spec_snapshot,
)
from tests.factories import (
    CommentFactory,
    IssueFactory,
    SpecSessionFactory,
    SpecTurnFactory,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    monkeypatch.setattr(runworker_module.time, "sleep", lambda seconds: None)


@pytest.fixture
def checkout(settings, tmp_path):
    settings.SPEC_CHECKOUT_PATH = str(tmp_path)
    settings.SPEC_CLAUDE_BINARY = "claude"
    settings.SPEC_CLAUDE_MODEL = "fable"
    settings.SPEC_CLAUDE_SETTINGS_FILE = ""
    settings.SPEC_MAX_BUDGET_USD = 5.0
    settings.SPEC_TIMEOUT_SECONDS = 3600
    return tmp_path


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _success_payload(session_id=None, result="Spec drafted.", cost=0.123456):
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "num_turns": 3,
        "usage": {},
        "session_id": session_id or str(uuid.uuid4()),
    }
    if cost is not None:
        payload["total_cost_usd"] = cost
    return payload


def _error_payload(cost=0.05):
    # No session_id on purpose: it doubles as the sid-absent branch check —
    # the a-priori id recorded at attempt start must remain on the turn.
    return {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
        "errors": ["Reached max turns"],
        "num_turns": 30,
        "usage": {},
        "total_cost_usd": cost,
    }


def _success_proc(**kwargs):
    return _proc(stdout=json.dumps(_success_payload(**kwargs)))


def _patch_run(monkeypatch, outcomes, on_call=None):
    """Patch subprocess.run in the worker module, replaying one outcome
    (a fake process or an exception to raise) per call. on_call runs at
    invocation time, before the outcome is produced — the hook by which
    materialization tests observe the checkout exactly as claude would."""
    calls = []
    iterator = iter(outcomes)

    def fake_run(
        cmd, cwd=None, capture_output=False, text=False, timeout=None, check=False
    ):
        calls.append({"cmd": list(cmd), "cwd": cwd, "timeout": timeout, "check": check})
        if on_call is not None:
            on_call()
        value = next(iterator)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(runworker_module.subprocess, "run", fake_run)
    return calls


def _run_worker(iterations=1):
    out = io.StringIO()
    call_command("runworker", max_iterations=iterations, stdout=out)
    return out.getvalue()


def _write_change_file(checkout, number, relpath, content):
    path = checkout / "openspec" / "changes" / f"pxtx-{number}" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _started_turn(session, **kwargs):
    """A turn whose invocation attempt already began under the session's
    current claude session id, as the worker would have recorded it."""
    defaults = {
        "status": SpecTurnStatus.COMPLETED,
        "started_at": timezone.now(),
        "claude_session_id": session.claude_session_id,
    }
    defaults.update(kwargs)
    return SpecTurnFactory(session=session, **defaults)


PUSHED = {"proposal.md": "# Pushed proposal", "specs/feature/spec.md": "# Pushed delta"}


def _capture_dir(monkeypatch, outcomes, change_dir):
    """Like _patch_run, but additionally record the change directory's
    contents at every claude invocation: materialization must be complete
    before the run starts, so this capture is the assertion point for it."""
    seen = []
    calls = _patch_run(
        monkeypatch,
        outcomes,
        on_call=lambda: seen.append(runworker_module.snapshot_change_dir(change_dir)),
    )
    return calls, seen


def _propagate_pxtx_logs(monkeypatch):
    # The "pxtx" logger runs with propagate=False in settings, so caplog's
    # root handler never sees records unless we re-enable propagation.
    monkeypatch.setattr(logging.getLogger("pxtx"), "propagate", True)


# --- configuration and loop mechanics ---------------------------------------


@pytest.mark.django_db
def test_runworker_without_checkout_path_exits_with_message(settings, monkeypatch):
    settings.SPEC_CHECKOUT_PATH = ""
    session = SpecSessionFactory()
    turn = session.queue_turn("hello")
    calls = _patch_run(monkeypatch, [])

    out = io.StringIO()
    call_command("runworker", stdout=out)

    assert "checkout_path" in out.getvalue()
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.QUEUED
    assert calls == []


@pytest.mark.django_db
def test_runworker_requeues_stale_running_turn_and_resumes_it(checkout, monkeypatch):
    session = SpecSessionFactory(issue=IssueFactory(title="Add widget support"))
    turn = SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.RUNNING,
        started_at=timezone.now(),
        claude_session_id=session.claude_session_id,
        message="Kick off",
    )
    calls = _patch_run(
        monkeypatch, [_success_proc(session_id=str(session.claude_session_id))]
    )

    out = _run_worker()

    assert "Requeued 1 stale running turn(s)" in out
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    cmd = calls[0]["cmd"]
    # A crashed first attempt may already have registered the session id, so
    # the re-run must resume, never re-register — but it re-sends the
    # composed first prompt (worst case: a duplicate prompt in the session).
    assert cmd[-2:] == ["--resume", str(session.claude_session_id)]
    assert "--session-id" not in cmd
    prompt = cmd[2]
    assert "Add widget support" in prompt
    assert "Kick off" in prompt


@pytest.mark.django_db
def test_runworker_processes_oldest_queued_turn_first(checkout, monkeypatch):
    first_session = SpecSessionFactory()
    second_session = SpecSessionFactory()
    first_turn = first_session.queue_turn("first message")
    second_turn = second_session.queue_turn("second message")
    calls = _patch_run(monkeypatch, [_success_proc(), _success_proc()])

    _run_worker(iterations=2)

    first_turn.refresh_from_db()
    second_turn.refresh_from_db()
    assert first_turn.status == SpecTurnStatus.COMPLETED
    assert second_turn.status == SpecTurnStatus.COMPLETED
    assert f"pxtx-{first_session.issue.number}" in calls[0]["cmd"][2]
    assert f"pxtx-{second_session.issue.number}" in calls[1]["cmd"][2]


@pytest.mark.django_db
def test_runworker_claim_race_leaves_turn_to_other_worker(checkout, monkeypatch):
    session = SpecSessionFactory()
    turn = session.queue_turn("hello")
    calls = _patch_run(monkeypatch, [])
    original_claim = runworker_module.Command._claim

    def racing_claim(self, candidate):
        # Simulate a concurrent worker winning inside the select->update
        # window; the real conditional update must then lose.
        SpecTurn.objects.filter(pk=candidate.pk).update(status=SpecTurnStatus.RUNNING)
        return original_claim(self, candidate)

    monkeypatch.setattr(runworker_module.Command, "_claim", racing_claim)

    _run_worker(iterations=2)

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.RUNNING
    # No claude invocation, and no idle pull either: the second poll sees the
    # other worker's running turn and skips the checkout refresh.
    assert calls == []


@pytest.mark.django_db
def test_runworker_keyboard_interrupt_exits_cleanly(checkout, monkeypatch):
    calls = _patch_run(monkeypatch, [_proc()])

    def interrupting_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(runworker_module.time, "sleep", interrupting_sleep)

    out = io.StringIO()
    call_command("runworker", stdout=out)

    assert "Interrupted" in out.getvalue()
    assert [call["cmd"] for call in calls] == [["git", "pull", "--ff-only"]]


# --- idle checkout refresh ---------------------------------------------------


@pytest.mark.django_db
def test_runworker_idle_pull_runs_ff_only_once_per_interval(checkout, monkeypatch):
    calls = _patch_run(monkeypatch, [_proc()])

    _run_worker(iterations=2)

    assert [call["cmd"] for call in calls] == [["git", "pull", "--ff-only"]]
    assert calls[0]["cwd"] == checkout
    assert calls[0]["check"] is True


@pytest.mark.django_db
def test_runworker_idle_pull_failure_is_logged_and_nonfatal(
    checkout, monkeypatch, caplog
):
    _propagate_pxtx_logs(monkeypatch)
    error = subprocess.CalledProcessError(
        1, ["git", "pull", "--ff-only"], stderr="fatal: not possible to fast-forward"
    )
    _patch_run(monkeypatch, [error])

    with caplog.at_level("WARNING", logger=runworker_module.logger.name):
        _run_worker(iterations=1)

    messages = [record.getMessage() for record in caplog.records]
    assert any("git pull" in m and str(checkout) in m for m in messages)


# --- invocation contract and prompt composition ------------------------------


@pytest.mark.django_db
def test_runworker_first_turn_registers_session_id_with_injected_prompt(
    checkout, monkeypatch
):
    issue = IssueFactory(
        title="Add feedback exports", description="Users want CSV exports."
    )
    CommentFactory(issue=issue, author="tobias", body="Excel too, sadly.")
    CommentFactory(issue=issue, author="claude-main", body="XLSX needs openpyxl.")
    session = SpecSessionFactory(issue=issue)
    turn = session.queue_turn("Focus on the data model first")
    calls = _patch_run(
        monkeypatch, [_success_proc(session_id=str(session.claude_session_id))]
    )

    _run_worker()

    turn.refresh_from_db()
    assert calls[0]["cwd"] == checkout
    assert calls[0]["timeout"] == 3600
    prompt = calls[0]["cmd"][2]
    assert calls[0]["cmd"] == [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        "fable",
        "--max-budget-usd",
        "5.0",
        "--session-id",
        str(session.claude_session_id),
    ]
    assert prompt.startswith(f"/opsx:explore pxtx-{issue.number}")
    assert f"pxtx-{issue.number}" in prompt
    assert f"Issue PX-{issue.number}: Add feedback exports" in prompt
    assert "Users want CSV exports." in prompt
    assert "tobias" in prompt
    assert "Excel too, sadly." in prompt
    assert "claude-main" in prompt
    assert "XLSX needs openpyxl." in prompt
    assert "Focus on the data model first" in prompt
    assert turn.prompt_sent == prompt
    assert turn.message == "Focus on the data model first"
    assert turn.started_at is not None
    assert turn.claude_session_id == session.claude_session_id


@pytest.mark.django_db
def test_runworker_first_turn_omits_empty_sections(checkout, monkeypatch):
    issue = IssueFactory(title="Bare issue", description="")
    session = SpecSessionFactory(issue=issue)
    turn = session.queue_turn("")
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    prompt = calls[0]["cmd"][2]
    assert "Comments" not in prompt
    assert "Earlier conversation" not in prompt
    assert "Your task" not in prompt
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED


@pytest.mark.django_db
def test_runworker_first_turn_with_bare_stage_command_sends_it_once(
    checkout, monkeypatch
):
    """The bootstrap queues the stage's /opsx: command verbatim; the
    composed first prompt already opens with it, so the Your-task echo must
    be skipped instead of sending the command twice."""
    session = SpecSessionFactory()
    turn = session.queue_turn("/opsx:explore")
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    prompt = calls[0]["cmd"][2]
    assert "Your task" not in prompt
    assert prompt.count("/opsx:explore") == 1
    turn.refresh_from_db()
    assert turn.prompt_sent == prompt
    assert turn.status == SpecTurnStatus.COMPLETED


@pytest.mark.parametrize(
    "message", ("Please also cover the API surface", "/opsx:propose")
)
@pytest.mark.django_db
def test_runworker_later_turn_resumes_with_verbatim_prompt(
    checkout, monkeypatch, message
):
    session = SpecSessionFactory()
    _started_turn(session, message="earlier", response="done that")
    turn = session.queue_turn(message)
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    cmd = calls[0]["cmd"]
    assert cmd[2] == message
    assert cmd[-2:] == ["--resume", str(session.claude_session_id)]
    assert "--session-id" not in cmd
    turn.refresh_from_db()
    assert turn.prompt_sent == message


@pytest.mark.django_db
def test_runworker_fresh_recovery_runs_as_first_turn_with_transcript(
    checkout, monkeypatch
):
    issue = IssueFactory(title="Rework schedule editor")
    session = SpecSessionFactory(issue=issue)
    old_session_id = session.claude_session_id
    _started_turn(session, message="", response="Bootstrap exploration notes")
    _started_turn(session, message="Explore the editor", response="I explored it")
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.CRITIQUE,
        status=SpecTurnStatus.COMPLETED,
        claude_session_id=uuid.uuid4(),
        message="check the drag logic",
        response="The drag logic section is hand-wavy",
    )
    _started_turn(
        session,
        status=SpecTurnStatus.ERROR,
        message="Go deeper",
        response="",
        raw_result={"exit_code": 1, "stderr": "No conversation found"},
    )

    turn = session.queue_turn("Pick up where we left off")
    session.refresh_from_db()
    assert session.claude_session_id != old_session_id
    calls = _patch_run(
        monkeypatch, [_success_proc(session_id=str(session.claude_session_id))]
    )

    _run_worker()

    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["--session-id", str(session.claude_session_id)]
    assert "--resume" not in cmd
    prompt = cmd[2]
    assert "Rework schedule editor" in prompt
    assert "Bootstrap exploration notes" in prompt
    assert "Explore the editor" in prompt
    assert "I explored it" in prompt
    assert "check the drag logic" in prompt
    assert "The drag logic section is hand-wavy" in prompt
    assert "Go deeper" in prompt
    assert "Pick up where we left off" in prompt
    turn.refresh_from_db()
    assert turn.claude_session_id == session.claude_session_id


@pytest.mark.django_db
def test_runworker_timeout_retry_resumes_without_transcript(checkout, monkeypatch):
    session = SpecSessionFactory()
    old_session_id = session.claude_session_id
    _started_turn(
        session,
        status=SpecTurnStatus.ERROR,
        message="Explore",
        response="",
        error_detail="claude was killed after exceeding the timeout",
        raw_result={},
    )
    turn = session.queue_turn("Continue")
    session.refresh_from_db()
    assert session.claude_session_id == old_session_id
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    cmd = calls[0]["cmd"]
    assert cmd[2] == "Continue"
    assert cmd[-2:] == ["--resume", str(old_session_id)]
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED


@pytest.mark.django_db
def test_runworker_omits_model_flag_when_unconfigured(checkout, settings, monkeypatch):
    settings.SPEC_CLAUDE_MODEL = ""
    session = SpecSessionFactory()
    session.queue_turn("go")
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    assert "--model" not in calls[0]["cmd"]


# --- result classification ----------------------------------------------------


@pytest.mark.django_db
def test_runworker_success_populates_turn(checkout, monkeypatch):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    number = session.issue.number
    turn = session.queue_turn("Write it up")
    _write_change_file(checkout, number, "proposal.md", "# Proposal")
    _write_change_file(checkout, number, "specs/feature/spec.md", "# Spec delta")
    claude_session_id = str(session.claude_session_id)
    payload = _success_payload(session_id=claude_session_id, cost=0.123456)
    _patch_run(monkeypatch, [_proc(stdout=json.dumps(payload))])

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.response == "Spec drafted."
    assert turn.cost_usd == Decimal("0.123456")
    assert turn.raw_result == payload
    assert turn.artifacts == {
        "proposal.md": "# Proposal",
        "specs/feature/spec.md": "# Spec delta",
    }
    assert turn.claude_session_id == uuid.UUID(claude_session_id)
    assert turn.error_detail == ""
    status_entries = [
        e
        for e in turn.logged_actions()
        if e.action_type.startswith("pxtx.spec.turn.status")
    ]
    assert [e.action_type for e in status_entries] == [
        "pxtx.spec.turn.status.completed"
    ]
    assert status_entries[0].actor == "spec-worker"


@pytest.mark.django_db
def test_runworker_error_json_keeps_session_resumable(checkout, monkeypatch):
    session = SpecSessionFactory()
    number = session.issue.number
    original_session_id = session.claude_session_id
    turn = session.queue_turn("Explore")
    _write_change_file(checkout, number, "proposal.md", "half-finished")
    payload = _error_payload(cost=0.05)
    _patch_run(monkeypatch, [_proc(returncode=1, stdout=json.dumps(payload))])

    _run_worker()

    turn.refresh_from_db()
    session.refresh_from_db()
    assert turn.status == SpecTurnStatus.ERROR
    assert turn.raw_result == payload
    assert turn.cost_usd == Decimal("0.05")
    assert turn.response == ""
    assert turn.artifacts == {"proposal.md": "half-finished"}
    # No session_id in the error payload: the a-priori id remains the record.
    assert turn.claude_session_id == original_session_id
    assert session.claude_session_id == original_session_id
    assert turn.is_session_gone is False
    status_entries = [
        e
        for e in turn.logged_actions()
        if e.action_type.startswith("pxtx.spec.turn.status")
    ]
    assert [e.action_type for e in status_entries] == ["pxtx.spec.turn.status.error"]


@pytest.mark.django_db
def test_runworker_timeout_marks_error_with_snapshot(checkout, monkeypatch):
    session = SpecSessionFactory()
    number = session.issue.number
    original_session_id = session.claude_session_id
    turn = session.queue_turn("Explore")
    _write_change_file(checkout, number, "proposal.md", "written before the kill")
    _patch_run(monkeypatch, [subprocess.TimeoutExpired(cmd=["claude"], timeout=3600)])

    _run_worker()

    turn.refresh_from_db()
    session.refresh_from_db()
    assert turn.status == SpecTurnStatus.ERROR
    assert "3600" in turn.error_detail
    assert turn.raw_result == {}
    assert turn.artifacts == {"proposal.md": "written before the kill"}
    assert session.claude_session_id == original_session_id
    assert turn.is_session_gone is False


@pytest.mark.django_db
def test_runworker_no_json_exit_is_session_gone(checkout, monkeypatch):
    session = SpecSessionFactory()
    number = session.issue.number
    turn = session.queue_turn("Explore")
    _write_change_file(checkout, number, "proposal.md", "leftovers")
    _patch_run(
        monkeypatch,
        [
            _proc(
                returncode=1, stdout="", stderr="No conversation found with session ID"
            )
        ],
    )

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.ERROR
    assert turn.raw_result == {
        "exit_code": 1,
        "stderr": "No conversation found with session ID",
    }
    assert "1" in turn.error_detail
    assert "No conversation found with session ID" in turn.error_detail
    assert turn.artifacts == {"proposal.md": "leftovers"}
    assert turn.is_session_gone is True


@pytest.mark.django_db
def test_runworker_non_object_json_output_is_session_gone(checkout, monkeypatch):
    session = SpecSessionFactory()
    turn = session.queue_turn("Explore")
    _patch_run(monkeypatch, [_proc(returncode=2, stdout="42", stderr="boom")])

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.ERROR
    assert turn.raw_result == {"exit_code": 2, "stderr": "boom"}
    assert turn.is_session_gone is True


# --- artifact copy-out --------------------------------------------------------


@pytest.mark.django_db
def test_runworker_explore_turn_without_change_dir_completes_empty(
    checkout, monkeypatch
):
    session = SpecSessionFactory()
    turn = session.queue_turn("Just think about it")
    _patch_run(monkeypatch, [_success_proc(cost=None)])

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.artifacts == {}
    assert turn.cost_usd is None


@pytest.mark.django_db
def test_runworker_propose_turn_without_change_dir_errors(checkout, monkeypatch):
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    turn = session.queue_turn("Write the proposal")
    payload = _success_payload()
    _patch_run(monkeypatch, [_proc(stdout=json.dumps(payload))])

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.ERROR
    assert turn.raw_result == payload
    assert turn.artifacts == {}
    assert f"pxtx-{session.issue.number}" in turn.error_detail
    assert turn.is_session_gone is False


@pytest.mark.django_db
def test_runworker_stage_flip_does_not_reclassify_older_queued_turns(
    checkout, monkeypatch
):
    session = SpecSessionFactory()
    turn = session.queue_turn("Queued while exploring")
    session.change_stage(SpecStage.PROPOSE, actor="tobias")
    _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    turn.refresh_from_db()
    assert turn.stage == SpecStage.EXPLORE
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.artifacts == {}


# --- critique turns -----------------------------------------------------------


@pytest.mark.django_db
def test_runworker_critique_runs_sessionless_with_template_prompt(
    checkout, monkeypatch
):
    issue = IssueFactory(
        title="Add feedback exports", description="Users want CSV exports."
    )
    session = SpecSessionFactory(issue=issue, stage=SpecStage.PROPOSE)
    original_session_id = session.claude_session_id
    _started_turn(session, message="explore", response="explored")
    turn = session.queue_turn("focus on the API surface", kind=SpecTurnKind.CRITIQUE)
    throwaway_id = str(uuid.uuid4())
    _patch_run(monkeypatch, [_success_proc(session_id=throwaway_id)])

    _run_worker()

    turn.refresh_from_db()
    session.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.claude_session_id == uuid.UUID(throwaway_id)
    assert session.claude_session_id == original_session_id
    prompt = turn.prompt_sent
    assert "adversarial" in prompt
    assert f"openspec/changes/pxtx-{issue.number}/" in prompt
    assert f"Issue PX-{issue.number}: Add feedback exports" in prompt
    assert "Users want CSV exports." in prompt
    assert "focus on the API surface" in prompt
    # Missing change directory is never an error for critiques.
    assert turn.artifacts == {}


@pytest.mark.django_db
def test_runworker_critique_snapshot_makes_modifications_visible(checkout, monkeypatch):
    """Critics are told not to write, but when one does, the turn snapshot
    records the change directory as it stands — the resulting transcript
    diff is the tamper evidence, never a silent edit."""
    session = SpecSessionFactory(stage=SpecStage.PROPOSE)
    number = session.issue.number
    turn = session.queue_turn("", kind=SpecTurnKind.CRITIQUE)
    _write_change_file(checkout, number, "proposal.md", "# Tampered by critic")
    _write_change_file(checkout, number, "design.md", "# Also touched")
    _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.artifacts == {
        "proposal.md": "# Tampered by critic",
        "design.md": "# Also touched",
    }


@pytest.mark.django_db
def test_runworker_critique_command_has_no_session_flags(checkout, monkeypatch):
    session = SpecSessionFactory(stage=SpecStage.READY)
    _started_turn(session, message="explore", response="explored")
    session.queue_turn("", kind=SpecTurnKind.CRITIQUE)
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    cmd = calls[0]["cmd"]
    assert "--session-id" not in cmd
    assert "--resume" not in cmd
    assert cmd[-2:] == ["--max-budget-usd", "5.0"]


@pytest.mark.django_db
def test_runworker_critique_without_focus_omits_focus_section(checkout, monkeypatch):
    issue = IssueFactory(title="Terse issue", description="")
    session = SpecSessionFactory(issue=issue, stage=SpecStage.PROPOSE)
    turn = session.queue_turn("", kind=SpecTurnKind.CRITIQUE)
    calls = _patch_run(monkeypatch, [_success_proc()])

    _run_worker()

    prompt = calls[0]["cmd"][2]
    assert "Focus" not in prompt
    turn.refresh_from_db()
    assert turn.prompt_sent == prompt


# --- pushed snapshot materialization -------------------------------------------


@pytest.mark.django_db
def test_runworker_first_chat_after_push_materializes_and_frames_existing_change(
    checkout, monkeypatch
):
    issue = IssueFactory(title="Feedback exports", description="Users want CSV.")
    session = push_spec_snapshot(issue, PUSHED, actor="claude-dev").session
    _write_change_file(checkout, issue.number, "stale.md", "left over on disk")
    turn = session.queue_turn("Tighten the API section")
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(
        monkeypatch,
        [_success_proc(session_id=str(session.claude_session_id))],
        change_dir,
    )

    _run_worker()

    # The stale file is gone and the nested pushed file exists before
    # claude runs — wholesale replacement, not a merge.
    assert seen == [PUSHED]
    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["--session-id", str(session.claude_session_id)]
    prompt = cmd[2]
    assert "/opsx" not in prompt
    assert f"openspec/changes/pxtx-{issue.number}/" in prompt
    assert "claude-dev" in prompt
    assert "Note from the push" not in prompt
    assert f"Issue PX-{issue.number}: Feedback exports" in prompt
    assert "Users want CSV." in prompt
    assert prompt.endswith("## Your task\n\nTighten the API section")
    turn.refresh_from_db()
    assert turn.prompt_sent == prompt
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.artifacts == PUSHED


@pytest.mark.django_db
def test_runworker_critique_after_push_reviews_materialized_spec_without_note(
    checkout, monkeypatch
):
    issue = IssueFactory(title="Terse issue", description="")
    session = push_spec_snapshot(
        issue, PUSHED, message="please review", actor="claude-dev"
    ).session
    turn = session.queue_turn("", kind=SpecTurnKind.CRITIQUE)
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    _run_worker()

    assert seen == [PUSHED]
    prompt = calls[0]["cmd"][2]
    assert "adversarial" in prompt
    # Critiques are sessionless one-shots reading fresh disk: no
    # materialization note, no push provenance in the prompt.
    assert "claude-dev" not in prompt
    assert "re-read" not in prompt
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED
    assert turn.artifacts == PUSHED


@pytest.mark.parametrize("push_message", ("", "wip draft, needs a critique"))
@pytest.mark.django_db
def test_runworker_resumed_chat_after_push_carries_materialization_note(
    checkout, monkeypatch, push_message
):
    session = SpecSessionFactory()
    _started_turn(session, message="explore this", response="explored")
    session.push_snapshot(PUSHED, message=push_message, actor="claude-dev")
    turn = session.queue_turn("Tighten section X")
    change_dir = runworker_module.change_dir_for(checkout, session.issue.number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    _run_worker()

    assert seen == [PUSHED]
    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["--resume", str(session.claude_session_id)]
    prompt = cmd[2]
    assert f"openspec/changes/pxtx-{session.issue.number}/" in prompt
    assert "claude-dev" in prompt
    assert "re-read" in prompt
    assert ("wip draft, needs a critique" in prompt) == bool(push_message)
    # For plain user text the note leads and the queued message closes.
    assert prompt.endswith("\n\nTighten section X")
    turn.refresh_from_db()
    assert turn.prompt_sent == prompt


@pytest.mark.django_db
def test_runworker_stage_command_after_push_keeps_command_first(checkout, monkeypatch):
    """A bare /opsx: stage command only expands when it starts the
    prompt: after a push, the materialization note must follow the
    command, not displace it."""
    session = SpecSessionFactory()
    _started_turn(session, message="explore this", response="explored")
    session.push_snapshot(PUSHED, actor="claude-dev")
    turn = session.queue_turn("/opsx:propose")
    change_dir = runworker_module.change_dir_for(checkout, session.issue.number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    _run_worker()

    assert seen == [PUSHED]
    prompt = calls[0]["cmd"][2]
    assert prompt.startswith("/opsx:propose\n\n")
    assert "claude-dev" in prompt
    assert "re-read" in prompt
    turn.refresh_from_db()
    assert turn.prompt_sent == prompt


@pytest.mark.django_db
def test_runworker_claude_snapshot_never_materializes(checkout, monkeypatch):
    session = SpecSessionFactory()
    number = session.issue.number
    _started_turn(
        session,
        message="draft it",
        response="drafted",
        artifacts={"proposal.md": "db copy that must never reach disk"},
    )
    _write_change_file(checkout, number, "proposal.md", "disk copy")
    turn = session.queue_turn("continue")
    change_dir = runworker_module.change_dir_for(checkout, number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    _run_worker()

    assert seen == [{"proposal.md": "disk copy"}]
    assert calls[0]["cmd"][2] == "continue"
    turn.refresh_from_db()
    assert turn.artifacts == {"proposal.md": "disk copy"}


@pytest.mark.django_db
def test_runworker_retry_after_errored_chat_does_not_rematerialize(
    checkout, monkeypatch
):
    issue = IssueFactory()
    session = push_spec_snapshot(issue, PUSHED, actor="claude-dev").session
    first = session.queue_turn("draft it")
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(
        monkeypatch,
        [_proc(returncode=1, stdout=json.dumps(_error_payload())), _success_proc()],
        change_dir,
    )

    _run_worker()

    first.refresh_from_db()
    assert first.status == SpecTurnStatus.ERROR
    assert first.artifacts == PUSHED

    # The errored chat turn is now the latest finished turn and its
    # snapshot mirrors disk, so the retry must not rewrite the checkout.
    _write_change_file(checkout, issue.number, "notes.md", "written after the error")
    retry = session.queue_turn("try again")

    _run_worker()

    assert seen[1] == {**PUSHED, "notes.md": "written after the error"}
    assert calls[1]["cmd"][2] == "try again"
    retry.refresh_from_db()
    assert retry.status == SpecTurnStatus.COMPLETED


@pytest.mark.django_db
def test_runworker_second_push_supersedes_first(checkout, monkeypatch):
    issue = IssueFactory()
    session = push_spec_snapshot(issue, {"proposal.md": "v1"}, actor="claude-a").session
    session.push_snapshot({"proposal.md": "v2"}, actor="claude-b")
    session.queue_turn("go")
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    _run_worker()

    assert seen == [{"proposal.md": "v2"}]
    prompt = calls[0]["cmd"][2]
    assert "claude-b" in prompt
    # The superseded push still shows in the injected transcript as a
    # pushed-files line, but its content reaches neither disk nor prompt.
    assert "claude-a pushed spec files" in prompt
    assert "v1" not in prompt


@pytest.mark.django_db
def test_runworker_requeued_turn_after_push_rematerializes(checkout, monkeypatch):
    issue = IssueFactory()
    session = push_spec_snapshot(issue, PUSHED, actor="claude-dev").session
    SpecTurnFactory(
        session=session,
        status=SpecTurnStatus.RUNNING,
        started_at=timezone.now(),
        claude_session_id=session.claude_session_id,
        message="draft it",
    )
    # The interrupted attempt may have half-run and left the change
    # directory diverged; the re-run must converge it back to the push.
    _write_change_file(checkout, issue.number, "proposal.md", "half-clobbered")
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(monkeypatch, [_success_proc()], change_dir)

    out = _run_worker()

    assert "Requeued 1 stale running turn(s)" in out
    assert seen == [PUSHED]
    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["--resume", str(session.claude_session_id)]
    assert "/opsx" not in cmd[2]
    assert "claude-dev" in cmd[2]


@pytest.mark.django_db
def test_runworker_fresh_recovery_after_push_injects_push_line(checkout, monkeypatch):
    issue = IssueFactory(title="Rework exports")
    session = SpecSessionFactory(issue=issue)
    old_session_id = session.claude_session_id
    _started_turn(session, message="Explore the exporters", response="I explored them")
    _started_turn(
        session,
        status=SpecTurnStatus.ERROR,
        message="Go deeper",
        response="",
        raw_result={"exit_code": 1, "stderr": "No conversation found"},
    )
    session.push_snapshot(
        PUSHED, message="rescued the draft locally", actor="claude-dev"
    )
    session.queue_turn("Continue from the pushed draft")
    session.refresh_from_db()
    assert session.claude_session_id != old_session_id
    change_dir = runworker_module.change_dir_for(checkout, issue.number)
    calls, seen = _capture_dir(
        monkeypatch,
        [_success_proc(session_id=str(session.claude_session_id))],
        change_dir,
    )

    _run_worker()

    assert seen == [PUSHED]
    cmd = calls[0]["cmd"]
    assert cmd[-2:] == ["--session-id", str(session.claude_session_id)]
    prompt = cmd[2]
    assert "/opsx" not in prompt
    assert "claude-dev pushed spec files" in prompt
    assert "rescued the draft locally" in prompt
    # Pushed file contents never inline into the recovery prompt, and the
    # push line carries no chat or critique speaker label.
    assert "# Pushed proposal" not in prompt
    assert "User:\nrescued the draft locally" not in prompt
    assert "Explore the exporters" in prompt
    assert "I explored them" in prompt
    assert prompt.endswith("## Your task\n\nContinue from the pushed draft")


@pytest.mark.django_db
def test_compose_transcript_renders_push_without_note_as_single_line():
    session = SpecSessionFactory()
    SpecTurnFactory(
        session=session,
        kind=SpecTurnKind.PUSH,
        status=SpecTurnStatus.COMPLETED,
        message="",
        actor="claude-dev",
        artifacts=PUSHED,
    )
    current = SpecTurnFactory(session=session, message="follow up")

    rendered = runworker_module.compose_transcript(current)

    assert "claude-dev pushed spec files" in rendered
    assert "Note from the push" not in rendered
    assert "# Pushed proposal" not in rendered
    assert "User" not in rendered
    assert "Critic" not in rendered


# --- settings file validation ---------------------------------------------------


@pytest.mark.parametrize("content", (None, '{"permissions": broken'))
@pytest.mark.django_db
def test_runworker_warns_on_missing_or_invalid_settings_file(
    checkout, settings, monkeypatch, caplog, content
):
    _propagate_pxtx_logs(monkeypatch)
    settings_file = checkout / "claude-settings.json"
    if content is not None:
        settings_file.write_text(content)
    settings.SPEC_CLAUDE_SETTINGS_FILE = str(settings_file)
    session = SpecSessionFactory()
    session.queue_turn("go")
    calls = _patch_run(monkeypatch, [_success_proc()])

    with caplog.at_level("WARNING", logger=runworker_module.logger.name):
        _run_worker()

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert any(str(settings_file) in message for message in warnings)
    # The flag is still passed: claude ignoring the file is claude's problem.
    assert "--settings" in calls[0]["cmd"]


@pytest.mark.django_db
def test_runworker_warns_when_no_settings_file_configured(
    checkout, monkeypatch, caplog
):
    """An empty [spec] settings-file key means the agent runs with no
    deployment guardrails at all — the worker keeps going but must say so."""
    _propagate_pxtx_logs(monkeypatch)
    session = SpecSessionFactory()
    turn = session.queue_turn("go")
    calls = _patch_run(monkeypatch, [_success_proc()])

    with caplog.at_level("WARNING", logger=runworker_module.logger.name):
        _run_worker()

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert any("settings file configured" in message for message in warnings)
    assert "--settings" not in calls[0]["cmd"]
    turn.refresh_from_db()
    assert turn.status == SpecTurnStatus.COMPLETED


@pytest.mark.django_db
def test_runworker_valid_settings_file_passes_silently(
    checkout, settings, monkeypatch, caplog
):
    _propagate_pxtx_logs(monkeypatch)
    settings_file = checkout / "claude-settings.json"
    settings_file.write_text('{"permissions": {"deny": ["Bash(git push:*)"]}}')
    settings.SPEC_CLAUDE_SETTINGS_FILE = str(settings_file)
    session = SpecSessionFactory()
    session.queue_turn("go")
    calls = _patch_run(monkeypatch, [_success_proc()])

    with caplog.at_level("WARNING", logger=runworker_module.logger.name):
        _run_worker()

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == []
    cmd = calls[0]["cmd"]
    settings_index = cmd.index("--settings")
    assert cmd[settings_index + 1] == str(settings_file)
