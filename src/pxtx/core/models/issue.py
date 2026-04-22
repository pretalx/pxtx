from django.db import models
from django.utils import timezone

from pxtx.core.models.base import BaseModel


class Effort(models.IntegerChoices):
    TINY = 30, "<1h"
    SMALL = 90, "1-2h"
    MEDIUM = 240, "2-6h"
    LARGE = 480, "1d"
    HUGE = 960, ">1d"


class Priority(models.IntegerChoices):
    WANT = 1, "want"
    SHOULD = 2, "should"
    COULD = 3, "could"
    WHATEV = 4, "whatev"
    LOL = 5, "lol"


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    OPEN = "open", "Open"
    WIP = "wip", "In progress"
    BLOCKED = "blocked", "Blocked"
    COMPLETED = "completed", "Completed"
    WONTFIX = "wontfix", "Won't fix"


CLOSED_STATUSES = frozenset({Status.COMPLETED, Status.WONTFIX})


class Source(models.TextChoices):
    MANUAL = "manual", "Manual"
    GITHUB = "github", "GitHub"
    CLAUDE = "claude", "Claude"


class Issue(BaseModel):
    number = models.PositiveIntegerField(unique=True, editable=False, db_index=True)

    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)

    effort_minutes = models.PositiveSmallIntegerField(
        choices=Effort.choices, null=True, blank=True
    )
    priority = models.PositiveSmallIntegerField(
        choices=Priority.choices, default=Priority.COULD
    )
    is_highlighted = models.BooleanField(default=False, db_index=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    blocked_reason = models.TextField(blank=True)

    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.MANUAL
    )

    milestone = models.ForeignKey(
        "core.Milestone",
        null=True,
        blank=True,
        related_name="issues",
        on_delete=models.SET_NULL,
    )
    order_in_milestone = models.PositiveIntegerField(default=0, db_index=True)
    order_in_priority = models.PositiveIntegerField(default=0, db_index=True)

    assignee = models.CharField(max_length=200, blank=True, db_index=True)

    # Shape: list of {"label": str, "url": str|null, "note": str|null}.
    interested_parties = models.JSONField(default=list, blank=True)

    # Shape: list of {"label": str, "url": str}.
    links = models.JSONField(default=list, blank=True)

    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["priority", "-is_highlighted", "order_in_milestone", "-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["milestone", "order_in_milestone"]),
        ]

    def __str__(self):
        return f"{self.slug}: {self.title}"

    @property
    def slug(self):
        return f"PX-{self.number}"

    @property
    def is_closed(self):
        return self.status in CLOSED_STATUSES

    def save(self, *args, **kwargs):
        if self.number is None:
            # max()+1; gaps from deletes are fine; single-writer so no race to worry about
            last = Issue.objects.aggregate(m=models.Max("number"))["m"] or 0
            self.number = last + 1
        if self.is_closed and self.closed_at is None:
            self.closed_at = timezone.now()
        elif not self.is_closed and self.closed_at is not None:
            self.closed_at = None
        super().save(*args, **kwargs)
