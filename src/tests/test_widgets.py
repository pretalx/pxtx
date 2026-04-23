"""Unit tests for the shared Choices.js-enhanced select widgets. The widget
is the single seam that the modal form, filter bar, and inline-editable
table cells all share — so exercising it here keeps the JS fix (e.g. the
label re-seed for options containing ``<`` / ``>``) applicable everywhere
that marker renders."""

import pytest

from pxtx.core.widgets import EnhancedSelect, EnhancedSelectMultiple

pytestmark = pytest.mark.unit


def _parse_attrs(html):
    """Return the attributes of the first ``<select>`` tag as a dict so tests
    can assert on each one without caring about serialisation order."""
    import re

    match = re.search(r"<select([^>]*)>", html)
    assert match, f"no <select> found in: {html!r}"
    attrs = {}
    for key, _, quoted, bare in re.findall(
        r'([a-zA-Z\-_][\w\-:]*)(=(?:"([^"]*)"|(\S+)))?', match.group(1)
    ):
        attrs[key] = quoted or (bare or True)
    return attrs


def test_enhanced_select_marks_class_and_badge():
    widget = EnhancedSelect(badge_type="effort")
    widget.choices = [("30", "<1h")]

    attrs = _parse_attrs(widget.render("effort_minutes", "30"))

    assert attrs["class"] == "enhanced"
    assert attrs["data-badge-type"] == "effort"
    assert "data-inline-edit" not in attrs


def test_enhanced_select_inline_edit_adds_marker_and_class():
    widget = EnhancedSelect(badge_type="status", inline_edit=True)
    widget.choices = [("open", "Open")]

    attrs = _parse_attrs(widget.render("value", "open"))

    assert attrs["class"] == "enhanced inline-edit"
    assert attrs["data-inline-edit"] == "1"
    assert attrs["data-badge-type"] == "status"


def test_enhanced_select_carries_extra_attrs():
    widget = EnhancedSelect(
        badge_type="effort",
        inline_edit=True,
        attrs={"hx-post": "/issues/1/cell/effort/", "aria-label": "effort"},
    )
    widget.choices = [("30", "<1h")]

    attrs = _parse_attrs(widget.render("value", "30"))

    assert attrs["hx-post"] == "/issues/1/cell/effort/"
    assert attrs["aria-label"] == "effort"


def test_enhanced_select_multiple_uses_placeholder():
    widget = EnhancedSelectMultiple(badge_type="status", placeholder="any status")
    widget.choices = [("open", "Open")]

    attrs = _parse_attrs(widget.render("status", []))

    assert attrs["class"] == "enhanced"
    assert attrs["data-placeholder"] == "any status"
    assert "multiple" in attrs


def test_enhanced_select_option_labels_are_html_escaped():
    """The widget renders Django-escaped option content (``&lt;1h``). The
    decoded label is recovered in JS via ``textContent`` — this test pins
    the contract the JS re-seed relies on."""
    widget = EnhancedSelect(badge_type="effort")
    widget.choices = [("30", "<1h"), ("960", ">1d")]

    html = widget.render("value", "30")

    assert "&lt;1h" in html
    assert "&gt;1d" in html
    assert "<1h" not in html.replace("&lt;1h", "")
    assert ">1d" not in html.replace("&gt;1d", "").replace('">', "")
