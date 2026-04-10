"""Collectors that share the ``url.publishedprices.co.il`` backend.

Several chains — notably Rami Levy, Yochananof, Hatzi Hinam and Yenot Bitan
— publish their transparency-law files through the ``Published Prices``
platform. The platform exposes:

* ``POST /login/user`` — form login with a chain-specific username and an
  empty password.
* ``GET  /file/ajax_dir?...&sSearch=PriceFull<prefix>`` — a DataTables JSON
  endpoint that returns the file catalogue.
* ``GET  /file/d/<filename>``  — the actual gzipped XML download.

All of that is public, documented and explicitly meant to be consumed by
third parties such as comparison tools, so there is no scraping or auth
bypass involved.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date
from http.cookiejar import CookieJar
from typing import List, Optional, Set

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


BASE_URL = "https://url.publishedprices.co.il"


class PublishedPricesCollector(BaseCollector):
    """Base adapter for any chain hosted on ``url.publishedprices.co.il``."""

    #: Username assigned by the platform to the chain. Public by design.
    username: str = ""
    #: Password is empty for most chains but some override it.
    password: str = ""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        cookie_jar = CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )
        self._opener.addheaders = [("User-Agent", self.user_agent)]
        self._logged_in = False

    # ── low-level HTTP (cookie-aware) ───────────────────────────

    def _get(self, url: str) -> bytes:
        with self._opener.open(url, timeout=self.timeout) as resp:
            return resp.read()

    def _post(self, url: str, payload: dict) -> bytes:
        body = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        with self._opener.open(req, timeout=self.timeout) as resp:
            return resp.read()

    def _login(self) -> None:
        if self._logged_in:
            return
        # GET first to establish a session cookie, then POST the credentials.
        self._get(f"{BASE_URL}/login")
        self._post(
            f"{BASE_URL}/login/user",
            {"username": self.username, "password": self.password},
        )
        self._logged_in = True

    # ── file catalogue + download ───────────────────────────────

    def _list_files(self, prefix: str) -> List[dict]:
        self._login()
        params = {
            "sEcho":          "1",
            "iColumns":       "5",
            "iDisplayStart":  "0",
            "iDisplayLength": "100000",
            "mDataProp_0":    "fname",
            "sSearch":        prefix,
        }
        url = f"{BASE_URL}/file/ajax_dir?{urllib.parse.urlencode(params)}"
        payload = self._get(url).decode("utf-8", errors="ignore")
        data = json.loads(payload)
        rows = data.get("aaData") or []
        # Each row's first cell contains an <a> with the filename.
        files: List[dict] = []
        for row in rows:
            if not row:
                continue
            fname_cell = row[0]
            if isinstance(fname_cell, str):
                fname = fname_cell
            elif isinstance(fname_cell, dict):
                fname = fname_cell.get("fname", "")
            else:
                continue
            if not fname:
                continue
            files.append({"fname": fname})
        return files

    def _download(self, filename: str) -> bytes:
        self._login()
        return self._get(f"{BASE_URL}/file/d/{urllib.parse.quote(filename)}")

    # ── main entry ──────────────────────────────────────────────

    def collect(self, target_date: Optional[date] = None) -> CollectorResult:
        if not self.username:
            raise RuntimeError(
                f"{self.__class__.__name__}: username must be configured"
            )
        td = target_date or date.today()
        result = self._result(td)

        stamp = td.strftime("%Y%m%d")

        price_files = self._list_files("PriceFull")
        price_file = _pick_latest(price_files, stamp)
        if not price_file:
            return result.finalize(
                "failed",
                "No PriceFull file available for the requested date",
            )

        price_bytes = self._download(price_file)
        items = parse_price_file(price_bytes)
        codes: Set[str] = {str(i["barcode"]) for i in items if i.get("barcode")}

        promos_by_code = {}
        try:
            promo_files = self._list_files("PromoFull")
            promo_file = _pick_latest(promo_files, stamp)
            if promo_file:
                promo_bytes = self._download(promo_file)
                for promo in parse_promo_file(promo_bytes, codes):
                    promos_by_code.setdefault(promo["item_code"], []).append(promo)
        except Exception as exc:
            result.meta["promo_error"] = f"{type(exc).__name__}: {exc}"

        observations: List[RawObservation] = []
        for item in items:
            barcode = item.get("barcode")
            if not barcode:
                continue

            promo_price = None
            promo_type = None
            promos = promos_by_code.get(str(barcode)) or []
            if promos:
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
                regular_price=item.get("regular_price"),
                promo_price=promo_price,
                promo_type=promo_type,
                unit_price=item.get("unit_price"),
                size_value=item.get("quantity"),
                size_unit=item.get("unit_qty"),
                in_stock=item.get("item_status") != "0",
                branch=price_file,
                product_url=f"{BASE_URL}/file/d/{urllib.parse.quote(price_file)}",
                match_confidence=confidence,
            ))

        result.observations = observations
        result.meta["price_file"] = price_file
        result.meta["parsed_items"] = len(items)
        return result.finalize("ok" if observations else "partial")


def _pick_latest(files: List[dict], stamp: str) -> Optional[str]:
    if not files:
        return None
    names = [f["fname"] for f in files]
    for_date = [n for n in names if stamp in n]
    pool = for_date or names
    pool.sort(reverse=True)
    return pool[0]


# ── Concrete chains ────────────────────────────────────────────────────

class RamiLevyCollector(PublishedPricesCollector):
    retailer_code = "rami_levy"
    retailer_name = "רמי לוי"
    username = "RamiLevi"


class YochananofCollector(PublishedPricesCollector):
    retailer_code = "yochananof"
    retailer_name = "יוחננוף"
    username = "yohananof"


class HatziHinamCollector(PublishedPricesCollector):
    retailer_code = "hatzi_hinam"
    retailer_name = "חצי חינם"
    username = "HaziHinam"


class YenotBitanCollector(PublishedPricesCollector):
    retailer_code = "yenot_bitan"
    retailer_name = "יינות ביתן"
    username = "ybitan"


class TivTaamCollector(PublishedPricesCollector):
    retailer_code = "tiv_taam"
    retailer_name = "טיב טעם"
    username = "TivTaam"
