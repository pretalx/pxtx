"""Issue indicator chips — status, priority, effort, spec session.

⁂ These render in the table, the kanban, the modal, the sidebar and the
detail page. Keeping the markup in one place is the only way the colour
classes stay in sync with the CSS; hand-copied spans drifted before.
"""

from django import template

register = template.Library()


@register.inclusion_tag("core/_status_badge.html")
def status_badge(obj):
    """``obj`` is anything with ``status`` / ``get_status_display`` — issues
    today, but the spec list passes ``session.issue`` and related-issue rows
    pass a sibling."""
    return {"obj": obj}


@register.inclusion_tag("core/_priority_badge.html")
def priority_badge(issue):
    return {"issue": issue}


@register.inclusion_tag("core/_effort_badge.html")
def effort_badge(issue, fallback="—"):
    """``fallback`` is what an unset effort renders as: an em dash in table
    cells and definition lists, nothing on kanban cards where a placeholder
    would just eat space."""
    return {"issue": issue, "fallback": fallback}


@register.inclusion_tag("core/_spec_pill.html")
def spec_pill(issue):
    return {"issue": issue}
