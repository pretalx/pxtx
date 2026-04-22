from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    log_action_prefix = None
    log_tracked_fields = ()

    class Meta:
        abstract = True

    def save(self, *args, actor=None, skip_log=False, **kwargs):
        is_new = self._state.adding
        before = {} if is_new else self._previous_snapshot()
        super().save(*args, **kwargs)
        if skip_log or self.log_action_prefix is None:
            return
        after = self._snapshot()
        if is_new:
            self.log_action(".create", actor=actor, before={}, after=after)
            return
        changed = [key for key in after if before.get(key) != after.get(key)]
        if not changed:
            return
        before_changes = {key: before.get(key) for key in changed}
        after_changes = {key: after[key] for key in changed}
        for action, sub_before, sub_after in self._split_change_actions(
            before_changes, after_changes
        ):
            self.log_action(action, actor=actor, before=sub_before, after=sub_after)

    def delete(self, *args, actor=None, skip_log=False, **kwargs):
        if not skip_log and self.log_action_prefix is not None:
            self.log_action(".delete", actor=actor, before=self._snapshot(), after={})
        return super().delete(*args, **kwargs)

    def _split_change_actions(self, before, after):
        """Hook for splitting one update into multiple log entries.

        Returns an iterable of (action_type, before_dict, after_dict) tuples.
        Default: a single ``.update`` entry covering all changed fields.
        """
        return [(".update", before, after)]

    def _snapshot(self):
        data = {}
        for field_name in self.log_tracked_fields:
            field = self._meta.get_field(field_name)
            if isinstance(field, models.ForeignKey):
                data[field_name] = getattr(self, field.attname)
            else:
                data[field_name] = getattr(self, field_name)
        return data

    def _previous_snapshot(self):
        if self.pk is None:
            return {}
        try:
            previous = self.__class__.objects.get(pk=self.pk)
        except self.__class__.DoesNotExist:
            return {}
        return previous._snapshot()

    def log_action(
        self, action_type, *, actor=None, before=None, after=None, data=None
    ):
        from pxtx.core.models.activity_log import ActivityLog

        if action_type.startswith(".") and self.log_action_prefix:
            action_type = self.log_action_prefix + action_type

        payload = dict(data or {})
        if before is not None:
            payload["before"] = before
        if after is not None:
            payload["after"] = after
        return ActivityLog.objects.create(
            content_object=self,
            action_type=action_type,
            actor=actor or "",
            data=payload,
        )

    def logged_actions(self):
        from django.contrib.contenttypes.models import ContentType

        from pxtx.core.models.activity_log import ActivityLog

        return ActivityLog.objects.filter(
            content_type=ContentType.objects.get_for_model(type(self)),
            object_id=self.pk,
        )
