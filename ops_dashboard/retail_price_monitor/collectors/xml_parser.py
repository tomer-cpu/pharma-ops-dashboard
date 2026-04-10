"""XML parsers for the Israeli price-transparency feeds.

Every chain publishes two kinds of files:

* ``PriceFull<chain>-<store>-<timestamp>.xml[.gz]`` — complete price list.
* ``PromoFull<chain>-<store>-<timestamp>.xml[.gz]`` — active promotions.

The file format is defined by the Ministry of Economy and is mostly identical
across chains, but tag casing and nesting vary slightly. The helpers in this
module are tolerant of those differences.
"""

from __future__ import annotations

import gzip
from typing import Callable, Dict, Iterable, List, Optional, Set
from xml.etree import ElementTree as ET

from ops_dashboard.retail_price_monitor.collectors.brand import is_leiman_product


# ── helpers ─────────────────────────────────────────────────────────────

def decompress(data: bytes) -> bytes:
    """Return raw XML bytes, transparently handling gzip-compressed input."""

    if not data:
        return data
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def _localname(elem) -> str:
    tag = elem.tag
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return tag.lower()


def _first_text(elem, names: Iterable[str]) -> Optional[str]:
    wanted = {n.lower() for n in names}
    for child in elem:
        if _localname(child) in wanted:
            if child.text is None:
                return None
            text = child.text.strip()
            return text or None
    return None


def _as_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "").replace("₪", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _iter_elements(root: ET.Element, name: str) -> Iterable[ET.Element]:
    wanted = name.lower()
    for elem in root.iter():
        if _localname(elem) == wanted:
            yield elem


# ── PriceFull ──────────────────────────────────────────────────────────

def parse_price_file(
    data: bytes,
    brand_filter: Callable[[str, str], bool] = is_leiman_product,
) -> List[Dict[str, object]]:
    """Parse a ``PriceFull`` XML file and return the matching items.

    ``brand_filter`` receives ``(manufacturer, item_name)`` and should return
    ``True`` for items we want to keep. The default filter matches Leiman
    Schlissel across its various Hebrew and English spellings.
    """

    xml = decompress(data)
    if not xml:
        return []

    root = ET.fromstring(xml)

    items: List[Dict[str, object]] = []
    for item in _iter_elements(root, "item"):
        manufacturer = (
            _first_text(item, ("ManufacturerName", "ManufactureName", "ManufacturerDescription"))
            or ""
        )
        item_name = _first_text(item, ("ItemName", "ItemNm")) or ""
        if not brand_filter(manufacturer, item_name):
            continue

        items.append({
            "barcode":            _first_text(item, ("ItemCode",)),
            "item_name":          item_name or None,
            "manufacturer":       manufacturer or None,
            "manufacturer_country": _first_text(
                item, ("ManufactureCountry", "ManufacturerCountry"),
            ),
            "manufacturer_desc":  _first_text(item, ("ManufacturerItemDescription",)),
            "unit_qty":           _first_text(item, ("UnitQty",)),
            "quantity":           _as_float(_first_text(item, ("Quantity",))),
            "unit_of_measure":    _first_text(item, ("UnitOfMeasure",)),
            "is_weighted":        _first_text(item, ("bIsWeighted", "isWeighted")) == "1",
            "qty_in_package":     _as_float(_first_text(item, ("QtyInPackage",))),
            "regular_price":      _as_float(_first_text(item, ("ItemPrice",))),
            "unit_price":         _as_float(_first_text(item, ("UnitOfMeasurePrice",))),
            "allow_discount":     _first_text(item, ("AllowDiscount",)) == "1",
            "item_status":        _first_text(item, ("ItemStatus",)),
            "price_update_date":  _first_text(item, ("PriceUpdateDate",)),
        })

    return items


# ── PromoFull ──────────────────────────────────────────────────────────

def parse_promo_file(
    data: bytes,
    item_codes: Set[str],
) -> List[Dict[str, object]]:
    """Parse a ``PromoFull`` XML file and return only the promos that touch
    any of ``item_codes``.

    Returns a list of flattened ``(promo, item_code)`` pairs so that the
    runner can attach each promotion to the matching observation.
    """

    xml = decompress(data)
    if not xml:
        return []

    root = ET.fromstring(xml)
    results: List[Dict[str, object]] = []

    for promo in _iter_elements(root, "promotion"):
        matching_codes: Set[str] = set()
        for item in _iter_elements(promo, "item"):
            code = _first_text(item, ("ItemCode",))
            if code and code in item_codes:
                matching_codes.add(code)
        if not matching_codes:
            continue

        promo_desc   = _first_text(promo, ("PromotionDescription",))
        discounted   = _as_float(_first_text(promo, ("DiscountedPrice",)))
        discount_pct = _as_float(_first_text(promo, ("DiscountRate", "DiscountedRate")))
        start_date   = _first_text(promo, ("PromotionStartDate",))
        end_date     = _first_text(promo, ("PromotionEndDate",))
        min_qty      = _as_float(_first_text(promo, ("MinQty", "MinNoOfItemOffered")))

        for code in matching_codes:
            results.append({
                "item_code":      code,
                "promo_desc":     promo_desc,
                "discounted_price": discounted,
                "discount_pct":   discount_pct,
                "start_date":     start_date,
                "end_date":       end_date,
                "min_qty":        min_qty,
            })

    return results
