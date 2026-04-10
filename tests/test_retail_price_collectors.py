"""Unit tests for the retail price monitor collectors.

These tests run without touching the network: they drive the XML parser
against synthetic transparency-law files and the runner against a custom
``BaseCollector`` subclass that returns hard-coded observations.

Run with::

    python -m unittest tests.test_retail_price_collectors
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime
from typing import List, Optional

# ---------------------------------------------------------------------------
# Isolate the tests' database to a temporary file BEFORE importing anything
# from the ``retail_price_monitor`` package. ``config.RPM_DB_PATH`` is read at
# import time, so we patch both the module attribute and the downstream
# ``database.RPM_DB_PATH`` import.
# ---------------------------------------------------------------------------
_TMP_DIR = tempfile.mkdtemp(prefix="rpm-test-")
_TMP_DB  = os.path.join(_TMP_DIR, "rpm_test.db")

from ops_dashboard.retail_price_monitor import config as rpm_config      # noqa: E402
rpm_config.RPM_DB_PATH = _TMP_DB
from ops_dashboard.retail_price_monitor import database as rpm_db        # noqa: E402
rpm_db.RPM_DB_PATH = _TMP_DB

from ops_dashboard.retail_price_monitor.collectors.base import (          # noqa: E402
    BaseCollector, CollectorResult, RawObservation,
)
from ops_dashboard.retail_price_monitor.collectors.brand import (         # noqa: E402
    is_leiman_manufacturer, is_leiman_product, match_confidence,
)
from ops_dashboard.retail_price_monitor.collectors.runner import (        # noqa: E402
    run_collectors,
)
from ops_dashboard.retail_price_monitor.collectors.xml_parser import (    # noqa: E402
    parse_price_file, parse_promo_file,
)


# ── Synthetic XML fixtures ────────────────────────────────────────────

PRICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Prices>
  <ChainId>7290027600007</ChainId>
  <StoreId>001</StoreId>
  <Items>
    <Item>
      <PriceUpdateDate>2026-04-10 05:30:00</PriceUpdateDate>
      <ItemCode>7290000100011</ItemCode>
      <ItemName>חלבה פיסטוק 500 גרם</ItemName>
      <ManufacturerName>ליימן שליסל בע"מ</ManufacturerName>
      <ManufactureCountry>IL</ManufactureCountry>
      <UnitQty>גרמים</UnitQty>
      <Quantity>500</Quantity>
      <UnitOfMeasure>100 גרם</UnitOfMeasure>
      <bIsWeighted>0</bIsWeighted>
      <ItemPrice>39.90</ItemPrice>
      <UnitOfMeasurePrice>7.98</UnitOfMeasurePrice>
      <ItemStatus>1</ItemStatus>
    </Item>
    <Item>
      <ItemCode>7290000100028</ItemCode>
      <ItemName>חלבה שוקולד 500 גרם</ItemName>
      <ManufacturerName>Leiman Schlissel Ltd.</ManufacturerName>
      <Quantity>500</Quantity>
      <UnitQty>גרמים</UnitQty>
      <ItemPrice>37.90</ItemPrice>
      <UnitOfMeasurePrice>7.58</UnitOfMeasurePrice>
      <ItemStatus>1</ItemStatus>
    </Item>
    <Item>
      <ItemCode>7290000999999</ItemCode>
      <ItemName>חלב תנובה 3% 1 ליטר</ItemName>
      <ManufacturerName>תנובה</ManufacturerName>
      <Quantity>1000</Quantity>
      <UnitQty>מ"ל</UnitQty>
      <ItemPrice>6.90</ItemPrice>
      <ItemStatus>1</ItemStatus>
    </Item>
  </Items>
</Prices>
"""

PROMO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Promos>
  <Promotions>
    <Promotion>
      <PromotionId>P-1</PromotionId>
      <PromotionDescription>1+1 על חלבה</PromotionDescription>
      <PromotionStartDate>2026-04-08</PromotionStartDate>
      <PromotionEndDate>2026-04-15</PromotionEndDate>
      <DiscountedPrice>29.90</DiscountedPrice>
      <DiscountRate>25</DiscountRate>
      <MinQty>1</MinQty>
      <PromotionItems>
        <Item>
          <ItemCode>7290000100011</ItemCode>
        </Item>
      </PromotionItems>
    </Promotion>
    <Promotion>
      <PromotionId>P-2</PromotionId>
      <PromotionDescription>מבצע חלב</PromotionDescription>
      <DiscountedPrice>5.50</DiscountedPrice>
      <PromotionItems>
        <Item>
          <ItemCode>7290000999999</ItemCode>
        </Item>
      </PromotionItems>
    </Promotion>
  </Promotions>
</Promos>
"""


class BrandMatcherTests(unittest.TestCase):
    def test_hebrew_manufacturer(self):
        self.assertTrue(is_leiman_manufacturer("ליימן שליסל בע\"מ"))
        self.assertTrue(is_leiman_manufacturer("לימן שליסל"))

    def test_english_manufacturer(self):
        self.assertTrue(is_leiman_manufacturer("Leiman Schlissel Ltd."))
        self.assertTrue(is_leiman_manufacturer("SCHLISSEL"))

    def test_unrelated_manufacturer_rejected(self):
        self.assertFalse(is_leiman_manufacturer("תנובה"))
        self.assertFalse(is_leiman_manufacturer("Strauss Group"))

    def test_item_name_fallback_returns_medium_confidence(self):
        self.assertTrue(is_leiman_product("תנובה", "חלבה ליימן שליסל 500"))
        self.assertEqual(match_confidence("תנובה", "חלבה ליימן שליסל 500"), "Medium")
        self.assertEqual(match_confidence("ליימן שליסל", "חלבה"), "High")
        self.assertEqual(match_confidence("תנובה", "חלב 1 ליטר"), "Low")


class XmlParserTests(unittest.TestCase):
    def test_parse_price_file_filters_by_brand(self):
        items = parse_price_file(PRICE_XML.encode("utf-8"))
        self.assertEqual(len(items), 2)
        codes = {i["barcode"] for i in items}
        self.assertEqual(codes, {"7290000100011", "7290000100028"})
        first = items[0]
        self.assertEqual(first["regular_price"], 39.90)
        self.assertEqual(first["unit_price"], 7.98)
        self.assertEqual(first["quantity"], 500.0)
        self.assertEqual(first["unit_qty"], "גרמים")

    def test_parse_price_file_handles_gzip(self):
        gz = gzip.compress(PRICE_XML.encode("utf-8"))
        items = parse_price_file(gz)
        self.assertEqual(len(items), 2)

    def test_parse_promo_file_keeps_only_wanted_codes(self):
        promos = parse_promo_file(
            PROMO_XML.encode("utf-8"),
            item_codes={"7290000100011"},
        )
        self.assertEqual(len(promos), 1)
        promo = promos[0]
        self.assertEqual(promo["item_code"], "7290000100011")
        self.assertEqual(promo["discounted_price"], 29.90)
        self.assertEqual(promo["promo_desc"], "1+1 על חלבה")

    def test_parse_promo_file_returns_nothing_when_no_match(self):
        self.assertEqual(parse_promo_file(PROMO_XML.encode("utf-8"), set()), [])


# ── Runner tests with a stub collector ───────────────────────────────

class StubCollector(BaseCollector):
    retailer_code = "shufersal"
    retailer_name = "שופרסל"

    def __init__(self, observations: List[RawObservation]) -> None:
        super().__init__()
        self._observations = observations

    def collect(self, target_date: Optional[date] = None) -> CollectorResult:
        result = self._result(target_date)
        result.observations = list(self._observations)
        return result.finalize("ok" if self._observations else "partial")


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        # Fresh database per test.
        if os.path.exists(_TMP_DB):
            os.remove(_TMP_DB)
        rpm_db.init_db()
        # Seed retailers (runner expects them to exist).
        with rpm_db.connection_scope() as conn:
            for retailer in [
                {"code": "shufersal", "name_he": "שופרסל",
                 "name_en": "Shufersal", "source_url": "https://example.com"},
            ]:
                rpm_db.upsert_retailer(conn, retailer)

    def test_runner_persists_observations_and_creates_products(self):
        today = date(2026, 4, 10)
        obs = [
            RawObservation(
                retailer_code="shufersal",
                observation_date=today.isoformat(),
                barcode="7290000100011",
                source_product_name="חלבה פיסטוק 500 גרם",
                manufacturer_name="ליימן שליסל",
                regular_price=39.90,
                promo_price=29.90,
                promo_type="1+1",
                unit_price=7.98,
                size_value=500, size_unit="gr",
                in_stock=True,
                branch="store-001",
            ),
        ]
        summary = run_collectors(
            target_date=today,
            collectors=[StubCollector(obs)],
            rebuild_alerts=False,
        )
        self.assertEqual(summary["observations_written"], 1)
        self.assertEqual(summary["products_created"], 1)

        with rpm_db.connection_scope() as conn:
            products = conn.execute(
                "SELECT canonical_name, barcode, brand FROM rpm_products"
            ).fetchall()
            self.assertEqual(len(products), 1)
            self.assertEqual(products[0]["barcode"], "7290000100011")

            observations = conn.execute(
                "SELECT regular_price, promo_price, promo_type, match_confidence, branch "
                "FROM rpm_price_observations"
            ).fetchall()
            self.assertEqual(len(observations), 1)
            self.assertAlmostEqual(observations[0]["regular_price"], 39.90, places=2)
            self.assertAlmostEqual(observations[0]["promo_price"], 29.90, places=2)
            self.assertEqual(observations[0]["promo_type"], "1+1")
            self.assertEqual(observations[0]["branch"], "store-001")

            log = conn.execute(
                "SELECT status, products_collected FROM rpm_collection_log"
            ).fetchall()
            self.assertEqual(len(log), 1)
            self.assertEqual(log[0]["status"], "ok")
            self.assertEqual(log[0]["products_collected"], 1)

    def test_runner_records_failure_log_without_writing_observations(self):
        class FailingCollector(StubCollector):
            def collect(self, target_date=None):
                raise RuntimeError("HTTP 500")

        summary = run_collectors(
            target_date=date(2026, 4, 10),
            collectors=[FailingCollector([])],
            rebuild_alerts=False,
        )
        self.assertEqual(summary["observations_written"], 0)
        self.assertEqual(summary["collectors"][0]["status"], "failed")
        self.assertIn("HTTP 500", summary["collectors"][0]["error_message"])


def tearDownModule() -> None:
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
