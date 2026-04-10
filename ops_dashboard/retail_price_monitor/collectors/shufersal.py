"""Shufersal collector.

Shufersal publishes its transparency-law files on a public index page:

    https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=<n>

where ``catID=2`` is ``PriceFull`` and ``catID=3`` is ``PromoFull``. The page
is a plain HTML table listing the latest files for every store. We scrape the
HTML for direct ``.gz`` download links (public data, no auth required), pick
the most recent ``PriceFull``/``PromoFull`` file for one canonical store, and
parse them with the shared XML parser.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional, Set, Tuple

from ops_dashboard.retail_price_monitor.collectors.base import (
    BaseCollector,
    CollectorResult,
    RawObservation,
)
from ops_dashboard.retail_price_monitor.collectors.brand import match_confidence
from ops_dashboard.retail_price_monitor.collectors.xml_parser import (
    parse_price_file,
    parse_promo_file,
)


INDEX_URL = "https://prices.shufersal.co.il/FileObject/UpdateCategory"

# Capture download URLs of the form "...PriceFull7290027600007-001-20260410...xml.gz"
_LINK_RE = re.compile(
    r'href="(?P<url>[^"]+(?P<kind>PriceFull|PromoFull)[^"]+\.gz)"',
    re.IGNORECASE,
)


class ShufersalCollector(BaseCollector):
    retailer_code = "shufersal"
    retailer_name = "שופרסל"

    #: Shufersal ships several store files daily. We pin one canonical store
    #: to keep the run deterministic; override via the constructor if a
    #: different branch should be the reference.
    canonical_store = "001"

    def __init__(self, canonical_store: Optional[str] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        if canonical_store:
            self.canonical_store = canonical_store

    # ── Fetching ────────────────────────────────────────────────

    def _list_files(self, cat_id: int) -> List[str]:
        html = self.http_get(f"{INDEX_URL}?catID={cat_id}").decode("utf-8", errors="ignore")
        return [m.group("url") for m in _LINK_RE.finditer(html)]

    def _pick_latest(
        self, urls: List[str], target_date: date, kind: str
    ) -> Optional[str]:
        """Return the most recent ``PriceFull``/``PromoFull`` URL for the
        canonical store, restricted to ``target_date`` when possible."""

        wanted_kind = kind.lower()
        store = f"-{self.canonical_store}-"
        stamp = target_date.strftime("%Y%m%d")

        def score(url: str) -> Tuple[int, str]:
            # Prefer: (a) matches target date, (b) lexicographically latest.
            match_date = 1 if stamp in url else 0
            return match_date, url

        candidates = [
            u for u in urls
            if wanted_kind in u.lower() and store in u
        ]
        if not candidates:
            return None
        candidates.sort(key=score, reverse=True)
        return candidates[0]

    # ── Main entry ──────────────────────────────────────────────

    def collect(self, target_date: Optional[date] = None) -> CollectorResult:
        td = target_date or date.today()
        result = self._result(td)

        price_urls = self._list_files(cat_id=2)
        price_url = self._pick_latest(price_urls, td, "PriceFull")
        if not price_url:
            return result.finalize("failed", "No PriceFull file listed for the canonical store")

        price_bytes = self.http_get(price_url)
        items = parse_price_file(price_bytes)

        item_codes: Set[str] = {str(i["barcode"]) for i in items if i.get("barcode")}
        promos_by_code = {}
        try:
            promo_urls = self._list_files(cat_id=3)
            promo_url = self._pick_latest(promo_urls, td, "PromoFull")
            if promo_url:
                promo_bytes = self.http_get(promo_url)
                for promo in parse_promo_file(promo_bytes, item_codes):
                    promos_by_code.setdefault(promo["item_code"], []).append(promo)
        except Exception as exc:
            # Promos are best-effort — parsing failures don't fail the run.
            result.meta["promo_error"] = f"{type(exc).__name__}: {exc}"

        observations: List[RawObservation] = []
        for item in items:
            barcode = item.get("barcode")
            if not barcode:
                continue
            regular = item.get("regular_price")
            unit_price = item.get("unit_price")

            promo_price = None
            promo_type = None
            promos = promos_by_code.get(barcode) or []
            if promos:
                # Pick the best price for the consumer
                cheapest = min(
                    (p for p in promos if p.get("discounted_price") is not None),
                    key=lambda p: p["discounted_price"],
                    default=None,
                )
                if cheapest:
                    promo_price = cheapest["discounted_price"]
                    promo_type = cheapest.get("promo_desc")

            confidence = match_confidence(
                item.get("manufacturer") or "", item.get("item_name") or ""
            )

            observations.append(RawObservation(
                retailer_code=self.retailer_code,
                observation_date=td.isoformat(),
                barcode=str(barcode),
                source_product_name=item.get("item_name") or "",
                manufacturer_name=item.get("manufacturer"),
                regular_price=regular,
                promo_price=promo_price,
                promo_type=promo_type,
                unit_price=unit_price,
                size_value=item.get("quantity"),
                size_unit=item.get("unit_qty"),
                in_stock=item.get("item_status") != "0",
                branch=f"store-{self.canonical_store}",
                product_url=price_url,
                match_confidence=confidence,
            ))

        result.observations = observations
        result.meta["price_file"] = price_url
        result.meta["parsed_items"] = len(items)
        return result.finalize("ok" if observations else "partial")
