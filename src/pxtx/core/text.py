import re
from functools import partial
from xml.etree.ElementTree import Element

import bleach
import markdown
from bleach.linkifier import LinkifyFilter
from django.conf import settings
from django.urls import reverse
from django.utils.safestring import SafeString, mark_safe
from markdown.inlinepatterns import InlineProcessor
from markdown.preprocessors import Preprocessor

ALLOWED_TAGS = frozenset(
    {
        "p",
        "a",
        "code",
        "pre",
        "em",
        "strong",
        "ul",
        "ol",
        "li",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "br",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "details",
        "summary",
        "span",
    }
)

ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})


def _img_attr_filter(tag, name, value):
    if name == "alt":
        return True
    if name == "src":
        return value.startswith("https://")
    return False


ALLOWED_ATTRIBUTES = {
    "a": ["href", "title"],
    "code": ["class"],
    "pre": ["class"],
    "span": ["class"],
    "img": _img_attr_filter,
    "details": ["open"],
}


PX_REF_RE = r"\bPX-(\d+)\b"
GH_REF_RE = r"\bGH-(?:([A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*)#)?(\d+)\b"


class PxRefInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):  # noqa: N802 - Python-Markdown API
        number = int(m.group(1))
        element = Element("a")
        element.text = f"PX-{number}"
        element.set("href", reverse("core:issue-detail", kwargs={"number": number}))
        return element, m.start(0), m.end(0)


class GhRefInlineProcessor(InlineProcessor):
    def handleMatch(self, m, data):  # noqa: N802 - Python-Markdown API
        explicit_repo = m.group(1)
        number = m.group(2)
        repo = explicit_repo or settings.DEFAULT_GITHUB_REPO
        element = Element("a")
        element.text = f"{repo}#{number}" if explicit_repo else f"GH-{number}"
        element.set("href", f"https://github.com/{repo}/issues/{number}")
        return element, m.start(0), m.end(0)


class PxtxRefsExtension(markdown.Extension):
    def extendMarkdown(self, md):  # noqa: N802 - Python-Markdown API
        md.inlinePatterns.register(PxRefInlineProcessor(PX_REF_RE), "pxtx_pxref", 175)
        md.inlinePatterns.register(GhRefInlineProcessor(GH_REF_RE), "pxtx_ghref", 174)


# Mirrors python-markdown's own list markers — `1)` is not one of them.
LIST_START_RE = re.compile(r"^ {0,3}(?:[*+-]|\d+\.)[ \t]+\S")


class LazyListPreprocessor(Preprocessor):
    """Insert the blank line markdown wants before a list that follows a
    paragraph.

    Agents routinely write ``Steps:`` and then dive straight into ``- one``,
    which markdown renders as one more line of the paragraph. We only patch a
    list that *starts* — a marker line while a list is already open needs no
    blank line, and adding one would turn a tight list loose.
    """

    def run(self, lines):
        out = []
        in_list = False
        for line in lines:
            if not line.strip():
                out.append(line)
                continue
            if LIST_START_RE.match(line):
                if not in_list and out and out[-1].strip():
                    out.append("")
                in_list = True
            elif in_list and not line.startswith((" ", "\t")) and not out[-1].strip():
                # Unindented text after a blank line closes the list; without
                # the blank line it is a lazy continuation of the last item.
                in_list = False
            out.append(line)
        return out


class LazyListsExtension(markdown.Extension):
    def extendMarkdown(self, md):  # noqa: N802 - Python-Markdown API
        # Below fenced_code (25), so fenced blocks are already stashed.
        md.preprocessors.register(LazyListPreprocessor(md), "pxtx_lazy_lists", 22)


def _build_markdown(*extra_extensions):
    return markdown.Markdown(
        extensions=[
            "markdown.extensions.fenced_code",
            "markdown.extensions.codehilite",
            "markdown.extensions.tables",
            "markdown.extensions.sane_lists",
            PxtxRefsExtension(),
            *extra_extensions,
        ],
        extension_configs={
            "markdown.extensions.codehilite": {
                "guess_lang": False,
                "use_pygments": True,
                "css_class": "codehilite",
            }
        },
    )


_md = _build_markdown("markdown.extensions.nl2br")
_md_flowed = _build_markdown(LazyListsExtension())


def _linkify_callback(attrs, new=False):
    href = attrs.get((None, "href"), "")
    if href.startswith(("mailto:", "/", "#")):
        return attrs
    attrs[(None, "target")] = "_blank"
    attrs[(None, "rel")] = "noopener"
    return attrs


_cleaner = bleach.Cleaner(
    tags=ALLOWED_TAGS,
    attributes=ALLOWED_ATTRIBUTES,
    protocols=ALLOWED_PROTOCOLS,
    strip=True,
    filters=[
        partial(
            LinkifyFilter,
            callbacks=[_linkify_callback],
            skip_tags={"pre", "code"},
            parse_email=True,
        )
    ],
)


def render_markdown(text, *, hard_breaks=True):
    """Render markdown to sanitised HTML.

    - PX-<n> and GH-[<owner>/<repo>#]<n> tokens become links.
    - Bare URLs and email addresses are autolinked; external links get
      target="_blank" rel="noopener". Autolinking is skipped inside <pre>/<code>.
    - Fenced code blocks are highlighted via pygments.
    - Output is run through a strict bleach allowlist; <details>/<summary>
      survive because claude-code emits them in tool output.

    ``hard_breaks=False`` renders agent-authored prose: single newlines reflow
    instead of becoming <br>, and a list may follow a paragraph without the
    blank line markdown normally demands. Both are things agents get wrong when
    they hard-wrap their output.
    """
    if not text:
        return SafeString("")
    md = _md if hard_breaks else _md_flowed
    html = md.reset().convert(str(text))
    return mark_safe(_cleaner.clean(html))  # noqa: S308 - bleach sanitised
