"""Brand filter for Leiman Schlissel products.

Used to keep only the relevant rows out of a multi-hundred-megabyte national
PriceFull file. The match is intentionally liberal (manufacturer OR item name
contains any of the known brand spellings) to tolerate data entry quirks, but
is paired with a confidence flag so that suspicious matches can be flagged in
the dashboard instead of silently trusted.
"""

from __future__ import annotations

import re

# Hebrew + English spellings we encounter in the transparency-law feeds.
BRAND_PATTERNS = [
    "ליימן שליסל",
    "ליימן",
    "שליסל",
    "לימן שליסל",
    "לימן",
    "leiman schlissel",
    "leiman",
    "schlissel",
    "schliesel",
    "schleissel",
]

_NON_ALNUM = re.compile(r"[\s\-\u2013\u2014]+")


def _normalise(value: str) -> str:
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def is_leiman_manufacturer(manufacturer: str) -> bool:
    """Return ``True`` when the manufacturer string clearly belongs to the brand."""

    if not manufacturer:
        return False
    hay = _normalise(manufacturer)
    return any(pat in hay for pat in (p.lower() for p in BRAND_PATTERNS))


def is_leiman_product(manufacturer: str, item_name: str = "") -> bool:
    """Broader match — accepts hits either on manufacturer or on the item name.

    Some retailers publish the manufacturer in the item name itself instead of
    the dedicated field, so we check both. The caller decides which confidence
    level to assign to the resulting observation.
    """

    if is_leiman_manufacturer(manufacturer):
        return True
    if not item_name:
        return False
    hay = _normalise(item_name)
    return any(pat in hay for pat in (p.lower() for p in BRAND_PATTERNS))


def match_confidence(manufacturer: str, item_name: str) -> str:
    """Return ``'High' | 'Medium' | 'Low'`` for a given raw row."""

    if is_leiman_manufacturer(manufacturer):
        return "High"
    if is_leiman_product(manufacturer, item_name):
        return "Medium"
    return "Low"
