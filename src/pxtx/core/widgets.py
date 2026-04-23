"""Shared form widgets so modal, filter form, and inline-editable cells all
render the same Choices.js-enhanced dropdowns with badge-styled options.

``choices-init.js`` keys off ``class="enhanced"`` to bind Choices.js, and off
``data-badge-type="status|priority|effort"`` to wrap each option's label in
the matching ``.badge`` / ``.prio`` span — so one set of widgets covers the
dropdown look wherever a Django form is rendered.
"""

from django import forms


class _EnhancedMixin:
    def __init__(self, *, badge_type=None, placeholder=None, attrs=None):
        base = {"class": "enhanced"}
        if badge_type:
            base["data-badge-type"] = badge_type
        if placeholder:
            base["data-placeholder"] = placeholder
        if attrs:
            base.update(attrs)
        super().__init__(attrs=base)


class EnhancedSelect(_EnhancedMixin, forms.Select):
    """Choices.js-enhanced single-select."""


class EnhancedSelectMultiple(_EnhancedMixin, forms.SelectMultiple):
    """Choices.js-enhanced multi-select (for filter forms)."""
