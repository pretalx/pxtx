from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class ActivityLog(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(db_index=True)
    content_object = GenericForeignKey("content_type", "object_id")
    action_type = models.CharField(max_length=200, db_index=True)
    actor = models.CharField(max_length=200, blank=True, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    data = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ("-timestamp",)
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.action_type} by {self.actor or 'unknown'} @ {self.timestamp.isoformat()}"

    @property
    def is_lifecycle(self):
        """Create and delete entries carry a full snapshot; treat them as
        events, not field-level diffs."""
        return self.action_type.endswith((".create", ".delete"))

    @property
    def changes(self):
        """Field-level diff dict, or None if this entry doesn't carry one."""
        before = (self.data or {}).get("before")
        after = (self.data or {}).get("after")
        if not before and not after:
            return None
        keys = set(before or {}) | set(after or {})
        return {
            key: {"old": (before or {}).get(key), "new": (after or {}).get(key)}
            for key in keys
        }
