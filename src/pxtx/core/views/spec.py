import difflib
import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Exists, F, Max, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from pxtx.core.models import (
    Issue,
    SpecSession,
    SpecStage,
    SpecTurn,
    SpecTurnKind,
    SpecTurnStatus,
    Status,
)
from pxtx.core.models.spec import ACTIVE_TURN_STATUSES, FINISHED_TURN_STATUSES
from pxtx.core.text import render_markdown
from pxtx.core.views._helpers import is_htmx, request_actor

# Stage transitions that involve claude queue a turn with the matching
# /opsx: command. Marking ready and reopening are pxtx-only state flips and
# queue nothing. A message posted alongside the transition rides on that
# turn, after the command.
STAGE_COMMANDS = {
    (SpecStage.EXPLORE, SpecStage.PROPOSE): "/opsx:propose",
    (SpecStage.PROPOSE, SpecStage.EXPLORE): "/opsx:explore",
}

STATE_LABELS = {
    "waiting": "Waiting on you",
    "error": "Error",
    "running": "Running",
    "queued": "Queued",
    "ready": "Ready",
    "new": "New",
}


def _get_session(number):
    return get_object_or_404(
        SpecSession.objects.select_related("issue"), issue__number=number
    )


def _artifact_diffs(previous, current):
    """Unified diffs between two snapshots, one entry per changed file."""
    diffs = []
    for path in sorted(set(previous) | set(current)):
        old, new = previous.get(path, ""), current.get(path, "")
        if old == new:
            continue
        lines = difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        diffs.append({"path": path, "diff": "\n".join(lines)})
    return diffs


def _transcript_entries(session):
    """Turns paired with render metadata: per-file diffs against the
    previous finished turn's snapshot (the first diffs against empty), and
    pretty-printed raw results for failed turns."""
    entries = []
    previous = {}
    for turn in session.turns.all():
        entry = {"turn": turn, "diffs": []}
        if turn.status == SpecTurnStatus.COMPLETED:
            entry["diffs"] = _artifact_diffs(previous, turn.artifacts)
        if turn.status == SpecTurnStatus.ERROR and turn.raw_result:
            entry["raw_json"] = json.dumps(turn.raw_result, indent=2)
        if turn.status in FINISHED_TURN_STATUSES:
            # Error turns snapshot too; they advance the diff baseline so
            # the next completed turn only shows what it actually changed.
            previous = turn.artifacts
        entries.append(entry)
    return entries


def _session_context(session, *, composer_prefill="", preserve_inputs=False):
    return {
        "issue": session.issue,
        "session": session,
        "entries": _transcript_entries(session),
        "has_active_turn": session.turns.filter(
            status__in=ACTIVE_TURN_STATUSES
        ).exists(),
        "can_critique": session.stage in (SpecStage.PROPOSE, SpecStage.READY)
        and bool(session.latest_snapshot),
        "total_cost": session.turns.aggregate(total=Sum("cost_usd"))["total"],
        "composer_prefill": composer_prefill,
        # True only for timed poll responses: it stamps hx-preserve on the
        # user-input elements so a background swap cannot wipe a draft, while
        # user-action swaps still replace (and thus clear) them.
        "preserve_inputs": preserve_inputs,
    }


def _session_response(request, session):
    """htmx requests get the updated session fragment swapped in place;
    plain form posts fall back to a full-page redirect."""
    if is_htmx(request):
        return render(request, "core/_spec_session.html", _session_context(session))
    return redirect("core:spec-page", number=session.issue.number)


class SpecPageView(LoginRequiredMixin, View):
    """The per-issue spec page: transcript, composer, stage buttons. Without
    a session it offers the bootstrap affordance instead. ``?forward=<pk>``
    (set by SpecForwardView's redirect) pre-fills the composer with that
    completed critique's text."""

    def get(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        session = SpecSession.objects.filter(issue=issue).first()
        if session is None:
            return render(
                request, "core/spec_page.html", {"issue": issue, "session": None}
            )
        prefill = ""
        forward_pk = request.GET.get("forward", "")
        if forward_pk.isdigit():
            forwarded = session.turns.filter(
                pk=int(forward_pk),
                kind=SpecTurnKind.CRITIQUE,
                status=SpecTurnStatus.COMPLETED,
            ).first()
            if forwarded is not None:
                prefill = forwarded.response
        return render(
            request,
            "core/spec_page.html",
            _session_context(session, composer_prefill=prefill),
        )


class SpecSessionFragmentView(LoginRequiredMixin, View):
    """Polling endpoint: the transcript/composer fragment re-requests itself
    every few seconds, but only while a turn is queued or running — the
    rendered fragment carries no polling trigger otherwise. Poll responses
    mark the composer and critique-focus inputs ``hx-preserve`` so a timed
    swap never clobbers text being typed; user-action responses omit the
    attribute so a sent message still clears the composer."""

    def get(self, request, number):
        session = _get_session(number)
        return render(
            request,
            "core/_spec_session.html",
            _session_context(session, preserve_inputs=True),
        )


def _start_session(issue, actor):
    session = SpecSession(issue=issue)
    session.save(actor=actor)
    session.queue_turn("/opsx:explore", actor=actor)
    return session


class SpecStartView(LoginRequiredMixin, View):
    """Bootstrap: create the session (stage explore) and queue the first
    explore turn. A second start on an existing session is a no-op."""

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        if not SpecSession.objects.filter(issue=issue).exists():
            _start_session(issue, request_actor(request))
        return redirect("core:spec-page", number=number)


class SpecResetView(LoginRequiredMixin, View):
    """Throw the spec out and start over: delete the session — transcript,
    artifacts and claude session id go with it — then bootstrap a fresh one
    in explore. Refused while a turn is queued or running, because the
    worker holds the running turn and would resurrect it on write. The
    worker wipes the change directory before a session's first run, so the
    new session does not inherit the discarded spec from disk."""

    def post(self, request, number):
        session = _get_session(number)
        if session.turns.filter(status__in=ACTIVE_TURN_STATUSES).exists():
            return HttpResponseBadRequest(
                "A spec turn is queued or running; reset once it finishes."
            )
        actor = request_actor(request)
        issue = session.issue
        session.delete(actor=actor)
        _start_session(issue, actor)
        return redirect("core:spec-page", number=number)


class SpecTurnQueueView(LoginRequiredMixin, View):
    def post(self, request, number):
        session = _get_session(number)
        if session.stage == SpecStage.READY:
            return HttpResponseBadRequest(
                "This spec is marked ready; reopen it to keep chatting."
            )
        message = request.POST.get("message", "").strip()
        if not message:
            return HttpResponseBadRequest("The message must not be empty.")
        session.queue_turn(message, actor=request_actor(request))
        return _session_response(request, session)


class SpecStageView(LoginRequiredMixin, View):
    """Flip the stage, and for the transitions that involve claude queue the
    matching /opsx: command. The composer's send-and-<stage> buttons post here
    with a ``message``, which is appended to the command so feedback on the
    current turn rides along instead of costing a separate one. A message on a
    transition that queues nothing (ready, reopen) is ignored — no UI posts
    one."""

    def post(self, request, number):
        session = _get_session(number)
        target = request.POST.get("stage", "")
        if target not in SpecStage.values:
            return HttpResponseBadRequest("Unknown stage.")
        old_stage = session.stage
        actor = request_actor(request)
        try:
            session.change_stage(target, actor=actor)
        except ValidationError as exc:
            return HttpResponseBadRequest(" ".join(exc.messages))
        command = STAGE_COMMANDS.get((old_stage, target))
        if command:
            message = request.POST.get("message", "").strip()
            session.queue_turn(
                f"{command}\n\n{message}" if message else command, actor=actor
            )
        return _session_response(request, session)


class SpecRetryView(LoginRequiredMixin, View):
    """Queue a new turn with a failed turn's message. The worker recomposes
    the sent prompt as the situation calls for, including fresh-session
    recovery after the session-gone failure class. Chat retries respect the
    ready read-only gate, mirroring the composer; critique retries stay
    allowed because critiques are explicitly offered in ready."""

    def post(self, request, number, pk):
        session = _get_session(number)
        failed = get_object_or_404(session.turns, pk=pk, status=SpecTurnStatus.ERROR)
        if failed.kind == SpecTurnKind.CHAT and session.stage == SpecStage.READY:
            return HttpResponseBadRequest(
                "This spec is marked ready; reopen it to retry this turn."
            )
        session.queue_turn(
            failed.message, kind=failed.kind, actor=request_actor(request)
        )
        return _session_response(request, session)


class SpecCritiqueView(LoginRequiredMixin, View):
    """Queue a one-shot critique turn, gated on propose/ready and a spec
    actually existing in the latest snapshot."""

    def post(self, request, number):
        session = _get_session(number)
        if (
            session.stage not in (SpecStage.PROPOSE, SpecStage.READY)
            or not session.latest_snapshot
        ):
            return HttpResponseBadRequest(
                "Critiques need a written spec: reach propose with artifacts first."
            )
        focus = request.POST.get("focus", "").strip()
        session.queue_turn(
            focus, kind=SpecTurnKind.CRITIQUE, actor=request_actor(request)
        )
        return _session_response(request, session)


class SpecForwardView(LoginRequiredMixin, View):
    """Hand a completed critique to the spec agent: reopen the session first
    when it is ready, then land on the spec page with the composer pre-filled
    with the critique text (via the ``?forward=`` query parameter)."""

    def post(self, request, number, pk):
        session = _get_session(number)
        critique = get_object_or_404(
            session.turns,
            pk=pk,
            kind=SpecTurnKind.CRITIQUE,
            status=SpecTurnStatus.COMPLETED,
        )
        if session.stage == SpecStage.READY:
            session.change_stage(SpecStage.PROPOSE, actor=request_actor(request))
        url = reverse("core:spec-page", kwargs={"number": number})
        return redirect(f"{url}?forward={critique.pk}")


class SpecCurrentView(LoginRequiredMixin, View):
    """The current-spec tab: the latest non-empty snapshot's files rendered
    as markdown, one file at a time, navigable via ``?file=``."""

    def get(self, request, number):
        session = _get_session(number)
        artifacts = session.latest_nonempty_snapshot
        files = sorted(artifacts)
        selected = request.GET.get("file") or (files[0] if files else "")
        if files and selected not in artifacts:
            raise Http404("No such artifact file")
        return render(
            request,
            "core/spec_current.html",
            {
                "issue": session.issue,
                "session": session,
                "files": files,
                "selected": selected,
                "rendered": (
                    render_markdown(artifacts[selected], hard_breaks=False)
                    if files
                    else ""
                ),
            },
        )


def _session_state(session):
    """One badge per session, most urgent signal wins: an active turn
    beats a stale error (a retry is already queued), errors beat everything
    else, then the waiting-on-you highlight, then ready. Only turn-less
    sessions fall through to new."""
    if session.has_active_turn:
        return "running" if session.has_running_turn else "queued"
    if session.latest_turn_status == SpecTurnStatus.ERROR:
        return "error"
    if session.waiting_on_user:
        return "waiting"
    if session.stage == SpecStage.READY:
        return "ready"
    return "new"


class SpecListView(LoginRequiredMixin, View):
    """The travel inbox: every spec session with stage, release, state badge,
    and cost, waiting-on-you sessions first, freshest activity on top, ready
    specs parked at the bottom. Completed issues drop out entirely."""

    def get(self, request):
        turns = SpecTurn.objects.filter(session=OuterRef("pk"))
        sessions = list(
            SpecSession.objects.with_waiting_on_user()
            .exclude(issue__status=Status.COMPLETED)
            .select_related("issue", "issue__milestone")
            .annotate(
                total_cost=Sum("turns__cost_usd"),
                has_running_turn=Exists(turns.filter(status=SpecTurnStatus.RUNNING)),
                # A finished turn bumps only the turn's row, so the session's
                # own timestamps say nothing about when claude last did work.
                # Fall back to them for sessions that have no turns yet.
                last_activity=Coalesce(Max("turns__updated_at"), F("updated_at")),
                is_ready=Q(stage=SpecStage.READY),
            )
            .order_by("is_ready", "-waiting_on_user", "-last_activity", "-created_at")
        )
        for session in sessions:
            session.state = _session_state(session)
            session.state_label = STATE_LABELS[session.state]
        return render(request, "core/spec_list.html", {"sessions": sessions})
