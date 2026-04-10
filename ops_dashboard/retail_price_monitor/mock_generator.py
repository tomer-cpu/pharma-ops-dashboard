"""Mock daily-collection generator.

In a real deployment the collector would fetch prices from each retailer's
public digital surface. For local development and demos we instead synthesise
a plausible history of daily snapshots driven by deterministic random walks.

Nothing in this module performs any network activity — it only populates the
local SQLite database used by the dashboard.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import List, Tuple

from ops_dashboard.retail_price_monitor.config import (
    BRAND_NAME,
    HISTORY_DAYS,
    MANUFACTURER,
    PRODUCT_CATALOG,
    RETAILER_PRICE_PROFILE,
    RETAILERS,
)
from ops_dashboard.retail_price_monitor.database import (
    connection_scope,
    has_observations,
    insert_collection_log,
    insert_observations,
    upsert_product,
    upsert_retailer,
)

# A stable seed keeps the mock history consistent across restarts of the
# FastAPI application. Production code would read real observations instead.
MOCK_SEED = 20260410


PROMO_TYPES_HE = [
    "1+1",
    "2+1",
    "מבצע שבוע",
    "מחיר מועדון",
    "מחיר מיוחד",
    "הנחת מזומן",
]


def _round_price(value: float) -> float:
    # Israeli shelf prices are almost always ``x.90`` or ``x.99`` — snap to
    # that to make the mock data feel authentic in the UI.
    base = round(value - 0.5)
    return max(0.9, base + random.choice([0.90, 0.95, 0.99]))


def _slug_branch(retailer_code: str) -> Tuple[str, str]:
    branches = {
        "shufersal":   ("שופרסל דיל", "מרכז"),
        "rami_levy":   ("רמי לוי הוד השרון", "שרון"),
        "yochananof":  ("יוחננוף גבעת שמואל", "מרכז"),
        "carrefour":   ("קרפור גבעתיים", "מרכז"),
        "victory":     ("ויקטורי פתח תקווה", "מרכז"),
        "tiv_taam":    ("טיב טעם ראשון לציון", "מרכז"),
        "hatzi_hinam": ("חצי חינם כפר סבא", "שרון"),
        "mahsanei":    ("מחסני השוק נס ציונה", "שפלה"),
        "yenot_bitan": ("יינות ביתן רמת גן", "מרכז"),
    }
    return branches.get(retailer_code, ("סניף ראשי", "מרכז"))


def _build_price_path(base_price: float, days: int, noise: float, rng: random.Random) -> List[float]:
    """Generate a smooth daily price walk around ``base_price``."""

    prices: List[float] = []
    current = base_price
    for i in range(days):
        drift = rng.gauss(0, noise * base_price * 0.4)
        current = max(base_price * 0.75, min(base_price * 1.25, current + drift))
        if i % 14 == 13:  # mild mean reversion every two weeks
            current = (current + base_price) / 2
        prices.append(current)
    return prices


def _generate_history() -> Tuple[List[tuple], List[tuple]]:
    """Return ``(observations, collection_logs)`` tuples ready for insertion."""

    rng = random.Random(MOCK_SEED)
    today = date.today()
    start = today - timedelta(days=HISTORY_DAYS - 1)

    observations: List[tuple] = []
    collection_logs: List[tuple] = []

    with connection_scope() as conn:
        # Seed master data
        retailer_ids = {}
        for retailer in RETAILERS:
            retailer_ids[retailer["code"]] = upsert_retailer(conn, retailer)

        product_ids: List[int] = []
        for product in PRODUCT_CATALOG:
            product_ids.append(upsert_product(conn, product, BRAND_NAME, MANUFACTURER))

        # Pre-compute price walks so each (retailer, product) pair has a
        # coherent story across days.
        walks: dict = {}
        for retailer in RETAILERS:
            profile = RETAILER_PRICE_PROFILE[retailer["code"]]
            for product, product_id in zip(PRODUCT_CATALOG, product_ids):
                base = product["base_price"] * profile["mult"]
                walks[(retailer["code"], product_id)] = _build_price_path(
                    base, HISTORY_DAYS, profile["noise"], rng
                )

        # Generate one snapshot per day per retailer
        for day_index in range(HISTORY_DAYS):
            d = start + timedelta(days=day_index)
            run_date = d.isoformat()
            collection_started = datetime.combine(d, time(5, 30)).isoformat()

            for retailer in RETAILERS:
                retailer_code = retailer["code"]
                retailer_id = retailer_ids[retailer_code]
                profile = RETAILER_PRICE_PROFILE[retailer_code]
                branch, region = _slug_branch(retailer_code)

                # Very occasionally simulate a total collection failure so
                # that the collection-failure alert path is exercised.
                failure = rng.random() < 0.01
                finished = datetime.combine(d, time(6, 15)).isoformat()
                if failure:
                    collection_logs.append((
                        run_date, retailer_id, "failed", 0,
                        "Source temporarily unavailable",
                        collection_started, finished,
                    ))
                    continue

                collected_for_day = 0
                for product, product_id in zip(PRODUCT_CATALOG, product_ids):
                    # Simulate sporadic missing listings (~4% of the time)
                    if rng.random() < 0.04:
                        continue

                    price_path = walks[(retailer_code, product_id)]
                    regular = _round_price(price_path[day_index])

                    promo_price = None
                    promo_type = None
                    if rng.random() < profile["promo_freq"]:
                        discount = rng.uniform(0.08, 0.25)
                        promo_price = _round_price(regular * (1 - discount))
                        promo_type = rng.choice(PROMO_TYPES_HE)

                    # Unit price per 100g when the product has a weight
                    unit_price = None
                    size = product.get("size_value")
                    unit = product.get("size_unit")
                    price_for_unit = promo_price or regular
                    if size and unit == "gr" and size > 0:
                        unit_price = round(price_for_unit / size * 100, 2)

                    # Occasional out-of-stock
                    in_stock = 0 if rng.random() < 0.05 else 1

                    source_name = product["name_he"]
                    url = f"{retailer['source_url']}/product/{product['barcode']}"

                    observations.append((
                        run_date,
                        "06:05:00",
                        retailer_id,
                        branch,
                        region,
                        source_name,
                        product_id,
                        regular,
                        promo_price,
                        promo_type,
                        unit_price,
                        in_stock,
                        url,
                        "High",  # deterministic catalogue = full confidence
                        None,
                        datetime.combine(d, time(6, 5)).isoformat(),
                    ))
                    collected_for_day += 1

                status = "ok" if collected_for_day > 0 else "partial"
                collection_logs.append((
                    run_date, retailer_id, status, collected_for_day,
                    None, collection_started, finished,
                ))

        insert_observations(conn, observations)
        insert_collection_log(conn, collection_logs)

    return observations, collection_logs


def seed_mock_data(force: bool = False) -> bool:
    """Populate the DB with a mock history. Returns ``True`` when data was
    actually generated."""

    if not force and has_observations():
        return False
    _generate_history()
    return True
