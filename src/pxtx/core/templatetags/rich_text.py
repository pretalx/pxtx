from django import template

from pxtx.core.models import Status
from pxtx.core.text import render_markdown

register = template.Library()


@register.filter(is_safe=True)
def rich_text(value):
    return render_markdown(value)


_STATUS_LABELS = dict(Status.choices)

_FIXED_ACTIONS = {
    "pxtx.issue.create": "created",
    "pxtx.issue.update": "updated",
    "pxtx.issue.delete": "deleted",
    "pxtx.comment.create": "commented",
    "pxtx.comment.update": "edited comment",
    "pxtx.comment.delete": "deleted comment",
}


@register.filter
def humanize_action(action_type):
    """Turn a raw activity log ``action_type`` into a short, readable label.

    Status transitions become e.g. "status → In progress". Unknown custom
    actions (e.g. submitted via the API) fall back to their trailing segment
    with underscores replaced by spaces, so ``team.standup_note`` reads as
    ``standup note``.
    """
    if action_type in _FIXED_ACTIONS:
        return _FIXED_ACTIONS[action_type]
    if action_type.startswith("pxtx.issue.status."):
        key = action_type.rsplit(".", 1)[-1]
        return f"status → {_STATUS_LABELS.get(key, key)}"
    tail = action_type.split(".")[-1]
    return tail.replace("_", " ")
