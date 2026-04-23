"""Shared form widgets so modal, filter form, and inline-editable cells all
render the same Choices.js-enhanced dropdowns with badge-styled options.

``choices-init.js`` keys off ``class="enhanced"`` to bind Choices.js, and off
``data-badge-type="status|priority|effort"`` to wrap each option's label in
the matching ``.badge`` / ``.prio`` span — so one set of widgets covers the
dropdown look wherever a Django form is rendered. Inline-editable table
cells pass ``inline_edit=True`` to also disable search and auto-open the
dropdown after a click-to-edit. Routing every such select through these
widgets means fixes like the textContent label re-seed in
``choices-init.js`` apply everywhere without template-level duplication.
"""

from django import forms


class _EnhancedMixin:
    def __init__(
        self, *, badge_type=None, placeholder=None, inline_edit=False, attrs=None
    ):
        classes = ["enhanced"]
        if inline_edit:
            classes.append("inline-edit")
        base = {"class": " ".join(classes)}
        if badge_type:
            base["data-badge-type"] = badge_type
        if placeholder:
            base["data-placeholder"] = placeholder
        if inline_edit:
            base["data-inline-edit"] = "1"
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)


class EnhancedSelect(_EnhancedMixin, forms.Select):
    """Choices.js-enhanced single-select."""


class EnhancedSelectMultiple(_EnhancedMixin, forms.SelectMultiple):
    """Choices.js-enhanced multi-select (for filter forms)."""
