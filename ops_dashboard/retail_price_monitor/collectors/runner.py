"""Orchestrates every configured collector and persists the results.

The runner is the only piece of the collectors package that touches the
database. It walks every registered collector, wraps each run in a safe
try/except boundary, persists observations + a collection-log entry, and
then asks the analytics layer to recompute alerts for the day that was just
written.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from typing import Dict, List, Optional, Type

from ops_dashboard.retail_price_monitor.analytics import generate_alerts_for_date
from ops_dashboard.retail_price_monitor.config import BRAND_NAME, MANUFACTURER
from ops_dashboard.retail_price_monitor.database import (
    connection_scope,
    init_db,
    insert_collection_log,
    insert_observations,
    update_retailer_status,
)
from ops_dashboard.retail_price_monitor.collectors.base import (
    BaseCollector,
    CollectorResult,
    RawObservation,
)
from ops_dashboard.retail_price_monitor.collectors.placeholder import (
    CarrefourCollector,
    MahsaneiCollector,
    VictoryCollector,
)
from ops_dashboard.retail_price_monitor.collectors.published_prices import (
    HatziHinamCollector,
    RamiLevyCollector,
    TivTaamCollector,
    YenotBitanCollector,
    YochananofCollector,
)
from ops_dashboard.retail_price_monitor.collectors.shufersal import ShufersalCollector


#: Default set of collectors. Tests can pass their own list to ``run_collectors``.
DEFAULT_COLLECTORS: List[Type[BaseCollector]] = [
    ShufersalCollector,
    RamiLevyCollector,
    YochananofCollector,
    HatziHinamCollector,
    YenotBitanCollector,
    TivTaamCollector,
    CarrefourCollector,
    VictoryCollector,
    MahsaneiCollector,
]


def run_collectors(
    target_date: Optional[date] = None,
    collectors: Optional[List[BaseCollector]] = None,
    rebuild_alerts: bool = True,
) -> Dict[str, object]:
    """Run every collector for ``target_date`` and persist their output.

    :param collectors: pre-instantiated collectors (used by tests). When
        ``None`` the defaults from :data:`DEFAULT_COLLECTORS` are used.
    :param rebuild_alerts: if ``True`` (default) the analytics alert engine
        is re-run for the affected day after the write completes.
    """

    init_db()
    td = target_date or date.today()

    if collectors is None:
        collectors = [cls() for cls in DEFAULT_COLLECTORS]

    results: List[CollectorResult] = []
    for collector in collectors:
        result = BaseCollector.safe_run(collector, td)
        results.append(result)

    totals = _persist_results(td, results)

    if rebuild_alerts and totals["observations_written"] > 0:
        generate_alerts_for_date(td.isoformat())

    return {
        "date": td.isoformat(),
        "collectors": [_result_summary(r) for r in results],
        **totals,
    }


# ── persistence helpers ──────────────────────────────────────────────

def _persist_results(td: date, results: List[CollectorResult]) -> Dict[str, int]:
    observations_written = 0
    products_created = 0
    log_rows: List[tuple] = []

    with connection_scope() as conn:
        retailer_map = _load_retailer_map(conn)

        for result in results:
            retailer_id = retailer_map.get(result.retailer_code)
            if retailer_id is None:
                # Unknown retailer code — still log the run so it is visible.
                log_rows.append((
                    td.isoformat(), 0, "failed", 0,
                    f"Retailer code {result.retailer_code} is not registered",
                    result.started_at, result.finished_at or datetime.utcnow().isoformat(),
                ))
                continue

            rows, created = _observations_to_rows(conn, retailer_id, result.observations)
            products_created += created
            if rows:
                insert_observations(conn, rows)
                observations_written += len(rows)

            log_rows.append((
                td.isoformat(), retailer_id, result.status, len(rows),
                result.error_message, result.started_at,
                result.finished_at or datetime.utcnow().isoformat(),
            ))

            update_retailer_status(
                conn, retailer_id,
                result.finished_at or datetime.utcnow().isoformat(),
                result.status,
            )

        if log_rows:
            insert_collection_log(conn, log_rows)

    return {
        "observations_written": observations_written,
        "products_created": products_created,
    }


def _load_retailer_map(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute("SELECT code, id FROM rpm_retailers").fetchall()
    return {r["code"]: r["id"] for r in rows}


def _observations_to_rows(
    conn: sqlite3.Connection,
    retailer_id: int,
    observations: List[RawObservation],
) -> tuple:
    """Convert :class:`RawObservation` instances into INSERT-ready tuples.

    Unknown barcodes are inserted into ``rpm_products`` with confidence info
    so the dashboard's "suspicious matches" screen can flag them for review.
    """

    rows: List[tuple] = []
    created = 0

    for obs in observations:
        product_id = _upsert_product_from_observation(conn, obs)
        if product_id is None:
            continue
        if obs.match_confidence == "Medium" or obs.notes == "auto-created":
            created += 1

        rows.append((
            obs.observation_date,
            datetime.utcnow().time().isoformat(timespec="seconds"),
            retailer_id,
            obs.branch,
            obs.region,
            obs.source_product_name,
            product_id,
            obs.regular_price,
            obs.promo_price,
            obs.promo_type,
            obs.unit_price,
            1 if obs.in_stock else 0 if obs.in_stock is not None else None,
            obs.product_url,
            obs.match_confidence,
            obs.notes,
            obs.collected_at,
        ))

    return rows, created


def _upsert_product_from_observation(
    conn: sqlite3.Connection, obs: RawObservation
) -> Optional[int]:
    barcode = obs.barcode
    if not barcode:
        return None

    existing = conn.execute(
        "SELECT id FROM rpm_products WHERE barcode = ?", (barcode,)
    ).fetchone()
    if existing:
        return existing["id"]

    cur = conn.execute(
        """
        INSERT INTO rpm_products (
            canonical_name, brand, manufacturer, barcode,
            size_value, size_unit, active
        ) VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            obs.source_product_name or f"SKU {barcode}",
            BRAND_NAME,
            obs.manufacturer_name or MANUFACTURER,
            barcode,
            obs.size_value,
            obs.size_unit,
        ),
    )
    obs.notes = "auto-created"
    return cur.lastrowid


def _result_summary(result: CollectorResult) -> dict:
    return {
        "retailer_code":  result.retailer_code,
        "status":         result.status,
        "observations":   len(result.observations),
        "error_message":  result.error_message,
        "started_at":     result.started_at,
        "finished_at":    result.finished_at,
        "meta":           result.meta,
    }
