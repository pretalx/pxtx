import pytest
from django.template import Context, Template
from django.utils.safestring import SafeString

from pxtx.core.text import render_markdown

pytestmark = pytest.mark.unit


def test_render_markdown_empty_returns_empty_safe_string():
    result = render_markdown("")

    assert result == ""
    assert isinstance(result, SafeString)


def test_render_markdown_none_returns_empty_safe_string():
    result = render_markdown(None)

    assert result == ""
    assert isinstance(result, SafeString)


def test_render_markdown_returns_safe_string():
    assert isinstance(render_markdown("hello"), SafeString)


def test_render_markdown_wraps_plain_text_in_paragraph():
    assert render_markdown("hello") == "<p>hello</p>"


def test_render_markdown_escapes_raw_html():
    result = render_markdown("<script>alert(1)</script>")

    assert "<script>" not in result
    assert "alert(1)" in result


def test_render_markdown_strips_disallowed_tags_but_keeps_content():
    result = render_markdown('<div class="x">inner</div>')

    assert "<div" not in result
    assert "inner" in result


def test_render_markdown_supports_emphasis_and_strong():
    assert render_markdown("*em* and **strong**") == (
        "<p><em>em</em> and <strong>strong</strong></p>"
    )


def test_render_markdown_nl2br_turns_soft_breaks_into_br():
    result = render_markdown("line one\nline two")

    assert "<br" in result
    assert "line one" in result
    assert "line two" in result


def test_render_markdown_renders_lists():
    result = render_markdown("- a\n- b\n")

    assert "<ul>" in result
    assert "<li>a</li>" in result
    assert "<li>b</li>" in result


def test_render_markdown_renders_tables():
    result = render_markdown("| h1 | h2 |\n| -- | -- |\n| a  | b  |\n")

    assert "<table>" in result
    assert "<thead>" in result
    assert "<tbody>" in result
    assert "<th>h1</th>" in result
    assert "<td>a</td>" in result


def test_render_markdown_allows_details_and_summary():
    result = render_markdown(
        "<details><summary>tool output</summary>\n\nhidden body\n\n</details>"
    )

    assert "<details>" in result
    assert "<summary>tool output</summary>" in result
    assert "hidden body" in result


def test_render_markdown_preserves_open_on_details():
    result = render_markdown('<details open="open"><summary>s</summary></details>')

    assert "<details open" in result


def test_render_markdown_fenced_code_without_lang_emits_pre_code():
    result = render_markdown("```\nPX-47 stays literal\n```")

    # PX-47 must not be linkified inside a code block
    assert "<a " not in result
    assert "PX-47 stays literal" in result
    assert "<pre>" in result
    assert "<code>" in result


def test_render_markdown_fenced_code_with_language_highlights_via_pygments():
    result = render_markdown("```python\ndef foo():\n    pass\n```")

    # pygments emits <span class="k">def</span> etc.
    assert 'class="k"' in result
    assert "<pre>" in result


def test_render_markdown_inline_code_preserved_and_not_linkified():
    result = render_markdown("see `PX-47` reference")

    assert "<code>PX-47</code>" in result
    assert "<a " not in result


def test_render_markdown_linkifies_px_ref():
    assert render_markdown("see PX-47 please") == (
        '<p>see <a href="/issues/47/">PX-47</a> please</p>'
    )


def test_render_markdown_linkifies_multiple_px_refs():
    result = render_markdown("PX-1 and PX-2")

    assert '<a href="/issues/1/">PX-1</a>' in result
    assert '<a href="/issues/2/">PX-2</a>' in result


def test_render_markdown_does_not_linkify_px_without_digits():
    assert render_markdown("PX- is not a ref") == "<p>PX- is not a ref</p>"


def test_render_markdown_does_not_linkify_px_inside_word():
    result = render_markdown("MPX-47 should not link")

    assert "<a " not in result
    assert "MPX-47" in result


def test_render_markdown_linkifies_bare_gh_ref_to_default_repo():
    result = render_markdown("see GH-99")

    assert 'href="https://github.com/pretalx/pretalx/issues/99"' in result
    assert ">GH-99</a>" in result


def test_render_markdown_linkifies_gh_ref_with_explicit_repo():
    result = render_markdown("see GH-owner/repo#123")

    assert 'href="https://github.com/owner/repo/issues/123"' in result
    assert ">owner/repo#123</a>" in result


def test_render_markdown_gh_ref_uses_default_repo_setting(settings):
    settings.DEFAULT_GITHUB_REPO = "foo/bar"

    result = render_markdown("GH-42")

    assert 'href="https://github.com/foo/bar/issues/42"' in result
    assert ">GH-42</a>" in result


def test_render_markdown_does_not_linkify_gh_inside_code_fence():
    result = render_markdown("```\nGH-99\n```")

    assert "<a " not in result
    assert "GH-99" in result


def test_render_markdown_allows_https_image():
    result = render_markdown("![alt text](https://example.com/pic.png)")

    assert "<img" in result
    assert 'src="https://example.com/pic.png"' in result
    assert 'alt="alt text"' in result


def test_render_markdown_strips_http_image_src():
    result = render_markdown("![alt](http://example.com/pic.png)")

    assert 'src="http://' not in result
    assert 'alt="alt"' in result


def test_render_markdown_strips_javascript_image_src():
    result = render_markdown('<img src="javascript:alert(1)" alt="x">')

    assert "javascript:" not in result


def test_render_markdown_strips_unlisted_image_attributes():
    result = render_markdown(
        '<img src="https://example.com/x.png" alt="a" width="10" onload="x()">'
    )

    assert 'src="https://example.com/x.png"' in result
    assert 'alt="a"' in result
    assert "width" not in result
    assert "onload" not in result


def test_render_markdown_allows_http_and_https_links():
    result = render_markdown("[http](http://example.com) [https](https://example.com)")

    assert 'href="http://example.com"' in result
    assert ">http</a>" in result
    assert 'href="https://example.com"' in result
    assert ">https</a>" in result


def test_render_markdown_strips_javascript_link_href():
    result = render_markdown("[x](javascript:alert(1))")

    assert "javascript:" not in result


def test_render_markdown_keeps_class_on_code_pre_span():
    result = render_markdown(
        '<pre class="x"><code class="y"><span class="z">t</span></code></pre>'
    )

    assert 'class="x"' in result
    assert 'class="y"' in result
    assert 'class="z"' in result


def test_render_markdown_strips_class_on_paragraph():
    result = render_markdown('<p class="bad">text</p>')

    assert "bad" not in result
    assert "<p>text</p>" in result


def test_render_markdown_blockquote_and_headings():
    result = render_markdown("# head\n\n> quoted")

    assert "<h1>head</h1>" in result
    assert "<blockquote>" in result
    assert "quoted" in result


def test_render_markdown_horizontal_rule():
    assert "<hr" in render_markdown("---\n")


def test_render_markdown_linkifies_bare_url():
    result = render_markdown("see https://example.com for more")

    assert 'href="https://example.com"' in result
    assert ">https://example.com</a>" in result


def test_render_markdown_linkifies_bare_email():
    result = render_markdown("contact me@example.com please")

    assert 'href="mailto:me@example.com"' in result


def test_render_markdown_does_not_linkify_url_in_inline_code():
    result = render_markdown("`https://example.com`")

    assert "<a " not in result
    assert "https://example.com" in result


def test_render_markdown_does_not_linkify_url_in_fenced_code():
    result = render_markdown("```\nhttps://example.com\n```")

    assert "<a " not in result
    assert "https://example.com" in result


def test_render_markdown_external_link_opens_in_new_tab():
    result = render_markdown("[x](https://example.com)")

    assert 'target="_blank"' in result
    assert 'rel="noopener"' in result


def test_render_markdown_internal_px_link_does_not_open_in_new_tab():
    result = render_markdown("see PX-7")

    assert "target=" not in result
    assert "rel=" not in result


def test_render_markdown_external_gh_link_opens_in_new_tab():
    result = render_markdown("see GH-99")

    assert 'target="_blank"' in result
    assert 'rel="noopener"' in result


def test_render_markdown_mailto_link_does_not_open_in_new_tab():
    result = render_markdown("[mail](mailto:me@example.com)")

    assert "target=" not in result


def test_render_markdown_state_does_not_leak_between_calls():
    first = render_markdown("# one")
    second = render_markdown("plain text")

    assert "<h1>one</h1>" in first
    assert "<h1>" not in second
    assert second == "<p>plain text</p>"


def test_rich_text_filter_invokes_render_markdown():
    tpl = Template("{% load rich_text %}{{ body|rich_text }}")

    rendered = tpl.render(Context({"body": "see PX-7"}))

    assert '<a href="/issues/7/">PX-7</a>' in rendered


def test_rich_text_filter_marks_output_safe_so_django_does_not_escape():
    tpl = Template("{% load rich_text %}{{ body|rich_text }}")

    rendered = tpl.render(Context({"body": "**bold**"}))

    assert "<strong>bold</strong>" in rendered


def test_rich_text_filter_handles_empty_input():
    tpl = Template("{% load rich_text %}[{{ body|rich_text }}]")

    rendered = tpl.render(Context({"body": ""}))

    assert rendered == "[]"


def _humanize(action_type):
    tpl = Template("{% load rich_text %}{{ action|humanize_action }}")
    return tpl.render(Context({"action": action_type}))


def test_humanize_action_maps_known_lifecycle_actions():
    assert _humanize("pxtx.issue.create") == "created"
    assert _humanize("pxtx.issue.update") == "updated"
    assert _humanize("pxtx.issue.delete") == "deleted"
    assert _humanize("pxtx.comment.create") == "commented"
    assert _humanize("pxtx.comment.update") == "edited comment"
    assert _humanize("pxtx.comment.delete") == "deleted comment"


def test_humanize_action_formats_status_transitions_with_display_label():
    assert _humanize("pxtx.issue.status.wip") == "status → In progress"
    assert _humanize("pxtx.issue.status.completed") == "status → Completed"


def test_humanize_action_status_keeps_unknown_key_verbatim():
    assert _humanize("pxtx.issue.status.weird") == "status → weird"


def test_humanize_action_falls_back_to_trailing_segment_for_custom_actions():
    assert _humanize("team.standup_note") == "standup note"
    assert _humanize("custom") == "custom"
