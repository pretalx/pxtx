import json
import logging
import shutil
import subprocess
import time
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from pxtx.core.models import SpecStage, SpecTurn, SpecTurnKind, SpecTurnStatus
from pxtx.core.models.spec import ACTIVE_TURN_STATUSES, FINISHED_TURN_STATUSES

logger = logging.getLogger(__name__)

ACTOR = "spec-worker"
POLL_INTERVAL_SECONDS = 5
IDLE_PULL_INTERVAL_SECONDS = 300
GIT_PULL_TIMEOUT_SECONDS = 120

# The /opsx: command that drives a session in each stage. The UI never
# queues chat turns in ready (it reopens to propose first); propose is the
# safe reading if one slips through anyway.
OPSX_COMMANDS = {
    SpecStage.EXPLORE: "/opsx:explore",
    SpecStage.PROPOSE: "/opsx:propose",
    SpecStage.READY: "/opsx:propose",
}


def change_dir_for(checkout, issue_number):
    # Always derived from the issue number, never from agent output.
    return Path(checkout) / "openspec" / "changes" / f"pxtx-{issue_number}"


def snapshot_change_dir(change_dir):
    """Copy the change directory into a {relative path: content} mapping.
    Empty when the directory does not exist, which is normal in explore."""
    if not change_dir.is_dir():
        return {}
    return {
        str(path.relative_to(change_dir)): path.read_text(
            encoding="utf-8", errors="replace"
        )
        for path in sorted(change_dir.rglob("*"))
        if path.is_file()
    }


def latest_finished_push(session):
    """The push turn whose snapshot must be materialized before a run:
    the session's most recent finished turn, when that turn is a push —
    exactly the case where the DB is ahead of the checkout. None otherwise;
    claude-produced snapshots never flow back to disk, because for those
    disk is the source of truth and the snapshot its mirror."""
    latest = (
        session.turns.filter(status__in=FINISHED_TURN_STATUSES)
        .order_by("-created_at", "-pk")
        .first()
    )
    if latest is not None and latest.kind == SpecTurnKind.PUSH:
        return latest
    return None


def materialize_snapshot(change_dir, artifacts):
    """Wholesale-replace the change directory with a pushed snapshot:
    files on disk but absent from the snapshot are removed — the push
    semantic is "this snapshot becomes the change directory". The paths
    were validated at push time and the directory is derived from the
    issue number, so nothing here trusts client naming at write time."""
    if change_dir.is_dir():
        shutil.rmtree(change_dir)
    for relpath, content in artifacts.items():
        path = change_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def describe_push(push_turn):
    """The push's note as its own prompt paragraph, empty when the push
    carried none — kept out of the surrounding instructions so the pusher's
    words never blur into the worker's."""
    if not push_turn.message:
        return ""
    return f"Note from the push: {push_turn.message}"


def compose_push_note(turn, push_turn):
    """The materialization note carried by any chat prompt sent after
    the worker replaced the change directory with a pushed snapshot: a
    resumed session's in-context memory of the files is stale, so the
    agent must re-read before continuing."""
    issue = turn.session.issue
    parts = [
        (
            f"Note: `openspec/changes/pxtx-{issue.number}/` was replaced "
            f"with files pushed by {push_turn.actor}. Any version of these "
            "files you remember is stale — re-read the change directory "
            "before continuing."
        )
    ]
    if description := describe_push(push_turn):
        parts.append(description)
    return "\n\n".join(parts)


def compose_push_framing(turn, push_turn):
    """First-prompt task framing when the latest finished turn is a
    push: the /opsx: commands are creation scaffolding — undefined against
    the already-materialized change directory — so the task is framed
    directly around the existing change instead."""
    issue = turn.session.issue
    parts = [
        (
            f"An OpenSpec change for this issue already exists at "
            f"`openspec/changes/pxtx-{issue.number}/`, materialized from files "
            f"pushed by {push_turn.actor}. Read those files first, then work "
            f"on that existing change — keep the name `pxtx-{issue.number}`, "
            "never create a differently named change."
        )
    ]
    if description := describe_push(push_turn):
        parts.append(description)
    return "\n\n".join(parts)


def compose_transcript(turn):
    """Render the session's stored transcript (prior turns' messages and
    responses) for fresh-session recovery — exploration that never reached
    disk survives only here."""
    parts = []
    for prior in turn.session.turns.exclude(pk=turn.pk):
        if prior.kind == SpecTurnKind.PUSH:
            # A push is neither a chat nor a critique message: it renders
            # as a single pushed-files line, never inlining contents — the
            # pushed snapshot is the on-disk change directory, which
            # materialization keeps current for the recovered session.
            line = (
                f"[{prior.actor} pushed spec files; the pushed content "
                "is the on-disk change directory.]"
            )
            if description := describe_push(prior):
                line += f"\n{description}"
            parts.append(line)
            continue
        is_chat = prior.kind == SpecTurnKind.CHAT
        if prior.message:
            speaker = "User" if is_chat else "User (critique request)"
            parts.append(f"{speaker}:\n{prior.message}")
        if prior.response:
            speaker = "Assistant" if is_chat else "Critic"
            parts.append(f"{speaker}:\n{prior.response}")
    return "\n\n".join(parts)


def compose_first_prompt(turn, push_turn=None):
    """A session's first prompt under its current claude session id: the
    task framing, the required change name, the issue context, and — after
    fresh-session recovery — the stored transcript. The framing is the
    stage's /opsx: command, unless the latest finished turn is a push (the
    worker has just materialized its snapshot — this covers push-created
    sessions): then the prompt frames the existing on-disk change directly,
    with no /opsx: scaffolding."""
    issue = turn.session.issue
    if push_turn is None:
        parts = [
            f"{OPSX_COMMANDS[turn.stage]} pxtx-{issue.number}",
            (
                f"Name the OpenSpec change exactly `pxtx-{issue.number}` — "
                "never pick a different change name."
            ),
        ]
    else:
        parts = [compose_push_framing(turn, push_turn)]
    parts.append(f"# Issue {issue.slug}: {issue.title}")
    if issue.description:
        parts.append(issue.description)
    comments = list(issue.comments.all())
    if comments:
        parts.append("## Comments")
        parts.extend(f"### {comment.author}\n\n{comment.body}" for comment in comments)
    transcript = compose_transcript(turn)
    if transcript:
        parts.append(
            "## Earlier conversation\n\n"
            "This session replaces an earlier one whose claude-side state "
            "was lost; the conversation so far:"
        )
        parts.append(transcript)
    # Stage-command turns queue the /opsx: command, optionally followed by
    # the message sent with the transition. The header above already carries
    # the command (or, under push framing, deliberately drops it), so strip
    # it off and keep only whatever the user wrote.
    task = turn.message.removeprefix(OPSX_COMMANDS[turn.stage]).strip()
    if task:
        parts.append(f"## Your task\n\n{task}")
    return "\n\n".join(parts)


def compose_critique_prompt(turn):
    issue = turn.session.issue
    parts = [
        (
            "You are an adversarial spec reviewer with fresh eyes. Read the "
            f"OpenSpec change in `openspec/changes/pxtx-{issue.number}/` and "
            "critique it against this codebase: hunt for requirements that "
            "contradict existing behaviour, missing or underspecified scenarios, "
            "hidden complexity, and anything that will not survive "
            "implementation. Be specific and cite files. Do not modify any "
            "files — reply with your findings only."
        ),
        f"# Issue {issue.slug}: {issue.title}",
    ]
    if issue.description:
        parts.append(issue.description)
    if turn.message:
        parts.append(f"## Focus\n\n{turn.message}")
    return "\n\n".join(parts)


class Command(BaseCommand):
    help = (
        "Spec worker: poll for queued spec turns, run each via `claude -p` "
        "in the configured pretalx checkout, and store results and artifact "
        "snapshots on the turn. Serial and single-instance by contract (the "
        "startup requeue would clobber a second live worker). Configure via "
        "[spec] in pxtx.toml; see pxtx.toml.example."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-iterations",
            type=int,
            default=None,
            help=(
                "Exit after this many poll iterations instead of running "
                "forever. Mainly for tests and one-shot runs."
            ),
        )

    def handle(self, *args, max_iterations=None, **options):
        if not settings.SPEC_CHECKOUT_PATH:
            self.stdout.write(
                "No [spec] checkout_path configured in pxtx.toml; the spec "
                "worker has nothing to do. See pxtx.toml.example."
            )
            return
        self.checkout = Path(settings.SPEC_CHECKOUT_PATH)
        # -inf so the first idle poll pulls immediately.
        self._last_pull = float("-inf")

        requeued = SpecTurn.objects.filter(status=SpecTurnStatus.RUNNING).update(
            status=SpecTurnStatus.QUEUED
        )
        if requeued:
            self.stdout.write(
                f"Requeued {requeued} stale running turn(s) from an "
                "interrupted worker; they will re-run via --resume."
            )

        iterations = 0
        try:
            while max_iterations is None or iterations < max_iterations:
                iterations += 1
                if not self._poll_once():
                    time.sleep(POLL_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Interrupted; exiting.")

    def _poll_once(self):
        """Process at most one queued turn. Returns True when a turn was
        run (poll again immediately), False when the worker should sleep."""
        candidate = (
            SpecTurn.objects.filter(status=SpecTurnStatus.QUEUED)
            .order_by("created_at", "pk")
            .first()
        )
        if candidate is None:
            self._refresh_checkout()
            return False
        if not self._claim(candidate):
            # Another worker won the race; leave the turn to it.
            return False
        candidate.refresh_from_db()
        self._process_turn(candidate)
        return True

    def _claim(self, candidate):
        # Atomic conditional update: only one worker can flip a turn from
        # queued to running. Bypasses activity logging on purpose — claims
        # are bookkeeping, not audit events.
        return (
            SpecTurn.objects.filter(
                pk=candidate.pk, status=SpecTurnStatus.QUEUED
            ).update(status=SpecTurnStatus.RUNNING)
            == 1
        )

    def _refresh_checkout(self):
        """Keep the checkout fresh while idle. The agent is denied git
        writes, so this pull is the only path by which the checkout
        advances; failures are logged and never fatal."""
        if SpecTurn.objects.filter(status__in=ACTIVE_TURN_STATUSES).exists():
            return
        now = time.monotonic()
        if now - self._last_pull < IDLE_PULL_INTERVAL_SECONDS:
            return
        self._last_pull = now
        try:
            subprocess.run(  # noqa: S603
                ["git", "pull", "--ff-only"],  # noqa: S607
                cwd=self.checkout,
                capture_output=True,
                text=True,
                check=True,
                timeout=GIT_PULL_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Idle git pull in %s failed: %s", self.checkout, exc)

    def _process_turn(self, turn):
        session = turn.session
        push_turn = latest_finished_push(session)
        if push_turn is not None:
            # A pushed snapshot is born in the DB, so until it is
            # materialized the checkout is stale: the agent would never see
            # the pushed spec, and the post-run snapshot would appear to
            # delete it. Repeating this before every run while the condition
            # holds makes interrupted runs self-healing.
            materialize_snapshot(
                change_dir_for(self.checkout, session.issue.number), push_turn.artifacts
            )
        if turn.kind == SpecTurnKind.CRITIQUE:
            # Critiques are sessionless one-shots: fresh context is the
            # point, so neither --session-id nor --resume is passed and the
            # session's own claude_session_id is never touched. No
            # materialization note either — a critique reads the freshly
            # materialized disk anyway.
            prompt, session_flags = compose_critique_prompt(turn), []
        else:
            prompt, session_flags = self._prepare_chat_turn(turn, push_turn)
        turn.prompt_sent = prompt
        turn.started_at = timezone.now()
        # skip_log: the attempt marker must be durable before claude runs
        # (a requeued turn must resume, never re-register its session id),
        # but it is bookkeeping — the single finalization entry below is the
        # audit event.
        turn.save(skip_log=True)

        self._warn_on_broken_settings()
        command = self._build_command(prompt) + session_flags
        try:
            proc = subprocess.run(  # noqa: S603
                command,
                cwd=self.checkout,
                capture_output=True,
                text=True,
                check=False,
                timeout=settings.SPEC_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            turn.status = SpecTurnStatus.ERROR
            turn.error_detail = (
                f"claude was killed after exceeding the "
                f"{settings.SPEC_TIMEOUT_SECONDS}s timeout. The session is "
                "almost certainly still alive; a retry resumes it."
            )
        else:
            self._classify_result(turn, proc)

        # Snapshot on every outcome: the checkout is readable regardless
        # of how claude died, and files are often written before budget,
        # max-turns, or timeout kills.
        change_dir = change_dir_for(self.checkout, session.issue.number)
        turn.artifacts = snapshot_change_dir(change_dir)
        if (
            turn.status == SpecTurnStatus.COMPLETED
            and turn.kind == SpecTurnKind.CHAT
            and turn.stage == SpecStage.PROPOSE
            and not change_dir.is_dir()
        ):
            # In propose, producing the change directory is the whole job.
            # Judged against the queue-time stage on the turn, never the
            # session's current stage.
            turn.status = SpecTurnStatus.ERROR
            turn.error_detail = (
                f"The run finished without creating {change_dir.name}/ in "
                "the checkout; a propose turn must produce the change "
                "directory. The raw result is attached."
            )
        turn.save(actor=ACTOR)
        logger.info("Turn %s finished with status %s.", turn.pk, turn.status)

    def _prepare_chat_turn(self, turn, push_turn=None):
        """Decide prompt and session flags for a chat turn. --session-id
        registers a new claude session and fails hard on reuse, so it is
        passed only when no attempt ever started under the session's current
        id; everything else resumes. Context injection additionally requires
        that no *other* turn started under the current id — a requeued first
        turn resumes, but re-sends its composed prompt. When a pushed
        snapshot was just materialized (push_turn is set), verbatim prompts
        carry the materialization note and composed first prompts use the
        push framing. A bare /opsx: stage command only expands when it
        starts the prompt, so there the note follows the command; any other
        verbatim message gets the note first."""
        session = turn.session
        started = session.turns.filter(
            kind=SpecTurnKind.CHAT,
            claude_session_id=session.claude_session_id,
            started_at__isnull=False,
        )
        session_id = str(session.claude_session_id)
        if started.exists():
            session_flags = ["--resume", session_id]
        else:
            session_flags = ["--session-id", session_id]
        if started.exclude(pk=turn.pk).exists():
            prompt = turn.message
            if push_turn is not None:
                note = compose_push_note(turn, push_turn)
                if prompt.startswith("/opsx:"):
                    prompt = f"{prompt}\n\n{note}"
                else:
                    prompt = f"{note}\n\n{prompt}"
        else:
            prompt = compose_first_prompt(turn, push_turn)
        # Audit-grade record: the id this run actually uses. The session-
        # level id mutates via fresh-session recovery.
        turn.claude_session_id = session.claude_session_id
        return prompt, session_flags

    def _build_command(self, prompt):
        command = [settings.SPEC_CLAUDE_BINARY, "-p", prompt, "--output-format", "json"]
        if settings.SPEC_CLAUDE_MODEL:
            command += ["--model", settings.SPEC_CLAUDE_MODEL]
        if settings.SPEC_CLAUDE_SETTINGS_FILE:
            command += ["--settings", settings.SPEC_CLAUDE_SETTINGS_FILE]
        command += ["--max-budget-usd", str(settings.SPEC_MAX_BUDGET_USD)]
        return command

    def _warn_on_broken_settings(self):
        path = settings.SPEC_CLAUDE_SETTINGS_FILE
        if not path:
            logger.warning(
                "No [spec] claude settings file configured in pxtx.toml; "
                "the agent runs without the deployed guardrails and only the "
                "budget cap applies."
            )
            return
        try:
            json.loads(Path(path).read_text())
        except (OSError, ValueError):
            logger.warning(
                "Claude settings file %s is missing or not valid JSON; "
                "claude silently ignores broken settings files, so this run "
                "proceeds without the deployed guardrails.",
                path,
            )

    def _classify_result(self, turn, proc):
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            # Claude exited on its own without a JSON result — the only
            # outcome after which the session is gone. The exit code in
            # raw_result is the marker SpecTurn.is_session_gone keys on.
            turn.status = SpecTurnStatus.ERROR
            turn.raw_result = {"exit_code": proc.returncode, "stderr": proc.stderr}
            turn.error_detail = (
                f"claude exited with code {proc.returncode} without a JSON "
                "result; the session is likely gone, and retrying will start "
                f"a fresh session.\n\nstderr:\n{proc.stderr}"
            )
            return
        turn.raw_result = payload
        cost = payload.get("total_cost_usd")
        if cost is not None:
            turn.cost_usd = Decimal(str(cost))
        session_id = payload.get("session_id")
        if session_id:
            turn.claude_session_id = session_id
        turn.response = payload.get("result") or ""
        if payload.get("is_error"):
            # In-run failure (budget, max turns, execution error): the
            # session id remains resumable.
            turn.status = SpecTurnStatus.ERROR
        else:
            turn.status = SpecTurnStatus.COMPLETED
