from django import template

from pxtx.core.text import render_markdown

register = template.Library()


@register.filter(is_safe=True)
def rich_text(value):
    return render_markdown(value)
