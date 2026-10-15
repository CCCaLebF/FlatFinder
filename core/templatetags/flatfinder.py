"""Template helpers for FlatFinder pages."""
import math

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **changes):
    """
    The current query string with some parameters changed, e.g. {% url_replace page=2 %}.
    A value of None removes the parameter. All search state lives in the URL (PLAN §6).
    """
    params = context["request"].GET.copy()
    for key, value in changes.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


@register.simple_tag(takes_context=True)
def hidden_query_inputs(context, exclude=""):
    """Hidden inputs for the current query string, minus `exclude` (comma-separated names)."""
    skip = {name.strip() for name in exclude.split(",") if name.strip()}
    inputs = [
        format_html('<input type="hidden" name="{}" value="{}">', key, value)
        for key, values in context["request"].GET.lists() if key not in skip
        for value in values
    ]
    return mark_safe("".join(inputs))


@register.filter
def lease_years(value):
    """52.46 -> '52 yrs 5 mths'."""
    if value is None:
        return "—"
    years = math.floor(value)
    months = int(round((value - years) * 12))
    if months == 12:
        years, months = years + 1, 0
    return f"{years} yrs {months} mths" if months else f"{years} yrs"


@register.filter
def is_in(value, collection):
    """{{ flat.id|is_in:bookmarked_ids }} — membership test usable inside {% include with %}."""
    return value in (collection or ())


@register.filter
def percent(value):
    """A 0–1 sub-score as a whole percentage, or '—' when the category is ignored."""
    return "—" if value is None else f"{round(value * 100)}%"


ACRONYMS = {"MRT", "LRT", "CHAS", "HDB", "NTUC", "PCF", "MOE", "YMCA", "YWCA", "PAP", "SG", "UK", "USA",
             "PTE", "LTD", "LLP", "CC", "RC", "II", "III", "IV"}


@register.filter
def display_name(value):
    """
    Names from data.gov.sg are often ALL CAPS. Re-case those, keeping acronyms such as
    MRT and CHAS; leave names that already have mixed case alone.
    """
    text = str(value)
    if text != text.upper():
        return text
    words = []
    for word in text.split():
        core = word.strip("().,&'-")
        words.append(word if core in ACRONYMS or any(ch.isdigit() for ch in core) else word.capitalize())
    return " ".join(words)


@register.filter
def street_title(value):
    """'ANG MO KIO AVE 3' -> 'Ang Mo Kio Ave 3' (keeps 'ST.' style abbreviations readable)."""
    return " ".join(word.capitalize() for word in str(value).split())
