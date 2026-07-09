import uuid

from django.core.exceptions import ValidationError
from django.db import models

from pxtx.core.models.base import BaseModel


class SpecStage(models.TextChoices):
    EXPLORE = "explore", "Explore"
    PROPOSE = "propose", "Propose"
    READY = "ready", "Ready"


class SpecTurnKind(models.TextChoices):
    CHAT = "chat", "Chat"
    CRITIQUE = "critique", "Critique"


class SpecTurnStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    ERROR = "error", "Error"


# ⁂ User-driven stage machine: explore ⇄ propose → ready, plus reopen
# (ready → propose). Everything else is rejected.
SPEC_STAGE_TRANSITIONS = {
    SpecStage.EXPLORE: (SpecStage.PROPOSE,),
    SpecStage.PROPOSE: (SpecStage.EXPLORE, SpecStage.READY),
    SpecStage.READY: (SpecStage.PROPOSE,),
}

ACTIVE_TURN_STATUSES = (SpecTurnStatus.QUEUED, SpecTurnStatus.RUNNING)
FINISHED_TURN_STATUSES = (SpecTurnStatus.COMPLETED, SpecTurnStatus.ERROR)


class SpecSessionQuerySet(models.QuerySet):
    def with_waiting_on_user(self):
        # ⁂ Annotation twin of SpecSession.is_waiting_on_user, for list
        # views and the API: stage not ready, latest turn completed, and
        # nothing queued or running. Derived on the fly, never stored.
        turns = SpecTurn.objects.filter(session=models.OuterRef("pk"))
        latest_turn_status = turns.order_by("-created_at", "-pk").values("status")[:1]
        return self.annotate(
            latest_turn_status=models.Subquery(latest_turn_status),
            has_active_turn=models.Exists(
                turns.filter(status__in=ACTIVE_TURN_STATUSES)
            ),
        ).annotate(
            # ⁂ Case instead of a bare Q: sessions without turns have a NULL
            # latest_turn_status, and NULL must count as False, not NULL.
            waiting_on_user=models.Case(
                models.When(
                    models.Q(latest_turn_status=SpecTurnStatus.COMPLETED)
                    & models.Q(has_active_turn=False)
                    & ~models.Q(stage=SpecStage.READY),
                    then=models.Value(True),
                ),
                default=models.Value(False),
                output_field=models.BooleanField(),
            )
        )


class SpecSession(BaseModel):
    log_action_prefix = "pxtx.spec.session"
    log_tracked_fields = ("stage", "claude_session_id")

    issue = models.OneToOneField(
        "core.Issue", related_name="spec_session", on_delete=models.CASCADE
    )
    # ⁂ Pre-assigned by pxtx and handed to claude via --session-id on the
    # first invocation. Mutates only on fresh-session recovery; the
    # audit-grade record of what actually ran lives on each turn.
    claude_session_id = models.UUIDField(default=uuid.uuid4)
    stage = models.CharField(
        max_length=10,
        choices=SpecStage.choices,
        default=SpecStage.EXPLORE,
        db_index=True,
    )

    objects = SpecSessionQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Spec session for {self.issue.slug} ({self.stage})"

    def _split_change_actions(self, before, after):
        # ⁂ Name stage flips after the target stage (mirrors issue status
        # logging); everything else stays a plain update.
        if "stage" not in after:
            return super()._split_change_actions(before, after)
        return [(f".stage.{after['stage']}", before, after)]

    def change_stage(self, new_stage, *, actor=None):
        """⁂ Validated, user-driven stage transition. Never touches the
        issue — spec stage is orthogonal to issue status by design."""
        if new_stage not in SPEC_STAGE_TRANSITIONS[self.stage]:
            raise ValidationError(
                "⁂ Cannot move the spec stage from %(old)s to %(new)s.",
                code="invalid_stage_transition",
                params={"old": self.stage, "new": new_stage},
            )
        self.stage = new_stage
        self.save(actor=actor)

    @property
    def is_waiting_on_user(self):
        if self.stage == SpecStage.READY:
            return False
        latest = self.turns.order_by("-created_at", "-pk").first()
        if latest is None or latest.status != SpecTurnStatus.COMPLETED:
            return False
        return not self.turns.filter(status__in=ACTIVE_TURN_STATUSES).exists()

    @property
    def latest_snapshot(self):
        """⁂ Artifacts of the most recent finished turn — the closest proxy
        for what is on disk right now. Queued and running turns are skipped
        because their snapshots have not been taken yet."""
        turn = (
            self.turns.filter(status__in=FINISHED_TURN_STATUSES)
            .order_by("-created_at", "-pk")
            .first()
        )
        return turn.artifacts if turn else {}

    @property
    def latest_nonempty_snapshot(self):
        """⁂ The most recent snapshot with any files in it, used by the
        current-spec view: an agent deleting the change directory should not
        blank the page, only the on-disk gating (latest_snapshot)."""
        turn = (
            self.turns.filter(status__in=FINISHED_TURN_STATUSES)
            .exclude(artifacts={})
            .order_by("-created_at", "-pk")
            .first()
        )
        return turn.artifacts if turn else {}

    def queue_turn(self, message="", *, kind=SpecTurnKind.CHAT, actor=None):
        """⁂ Queue a turn on this session — the single entry point for the
        UI. Snapshots the current stage onto the turn, and when the last
        chat turn lost its claude session (the no-JSON-exit class), rotates
        claude_session_id so the worker starts a fresh session with issue
        context and the stored transcript injected. Retries after any other
        error resume the existing session unchanged."""
        if kind == SpecTurnKind.CHAT:
            last_chat = (
                self.turns.filter(kind=SpecTurnKind.CHAT)
                .order_by("-created_at", "-pk")
                .first()
            )
            if last_chat is not None and last_chat.is_session_gone:
                self.claude_session_id = uuid.uuid4()
                self.save(actor=actor)
        turn = SpecTurn(session=self, kind=kind, message=message, stage=self.stage)
        turn.save(actor=actor)
        return turn


class SpecTurn(BaseModel):
    log_action_prefix = "pxtx.spec.turn"
    log_tracked_fields = (
        "kind",
        "stage",
        "status",
        "message",
        "cost_usd",
        "error_detail",
        "claude_session_id",
    )

    session = models.ForeignKey(
        "core.SpecSession", related_name="turns", on_delete=models.CASCADE
    )
    kind = models.CharField(
        max_length=10, choices=SpecTurnKind.choices, default=SpecTurnKind.CHAT
    )
    # ⁂ Queue-time input: user text or an /opsx: command; focus guidance
    # for critiques. The worker composes prompt_sent from this at run time.
    message = models.TextField(blank=True)
    # ⁂ Session stage in effect when the turn was queued. Classification
    # and transcript rendering key on this, not on the mutable session
    # stage, which may have moved on while the turn sat in the queue.
    stage = models.CharField(max_length=10, choices=SpecStage.choices)
    # ⁂ The claude session this turn actually ran under, set at run time.
    # The session-level id mutates via fresh-session recovery and critique
    # ids are throwaway, so this is the audit-grade record.
    claude_session_id = models.UUIDField(null=True, blank=True)
    prompt_sent = models.TextField(blank=True)
    response = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=SpecTurnStatus.choices,
        default=SpecTurnStatus.QUEUED,
        db_index=True,
    )
    # ⁂ Set when an invocation attempt begins; drives the worker's
    # --session-id vs --resume decision (a requeued turn must resume).
    started_at = models.DateTimeField(null=True, blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    # ⁂ Snapshot of openspec/changes/pxtx-<n>/ after the turn, as a mapping
    # of relative path to file content. Empty when the directory does not
    # exist, which is normal in explore.
    artifacts = models.JSONField(default=dict, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.kind} turn ({self.status}) in {self.session}"

    def _split_change_actions(self, before, after):
        # ⁂ Name status flips after the target status so queue/complete/
        # error events are greppable in the activity log.
        if "status" not in after:
            return super()._split_change_actions(before, after)
        return [(f".status.{after['status']}", before, after)]

    @property
    def is_session_gone(self):
        """⁂ True when this chat turn failed the no-JSON-exit class — the
        only outcome after which the claude session cannot be resumed. The
        worker stores the exit code in raw_result exactly for that class,
        so its presence is the marker. Timeouts and in-run error JSON keep
        the session resumable and never set it."""
        return (
            self.kind == SpecTurnKind.CHAT
            and self.status == SpecTurnStatus.ERROR
            and "exit_code" in self.raw_result
        )
