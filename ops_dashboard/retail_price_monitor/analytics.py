"""Analytics engine for the retail price monitor.

All aggregations, comparisons, trend detection and alert generation used by
both the API layer and the dashboard live here. Queries are intentionally
parameterised so that a future "live" data pipeline can replace the mock
generator without touching the analytics layer.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ops_dashboard.retail_price_monitor.config import ALERT_THRESHOLDS
from ops_dashboard.retail_price_monitor.database import (
    clear_alerts_for_date,
    connection_scope,
    insert_alerts,
)


# ── Small utilities ───────────────────────────────────────────────────────

def _effective_price(row: Dict[str, Any]) -> Optional[float]:
    """Return the price a shopper actually pays (promo if present)."""

    promo = row.get("promo_price")
    if promo is not None:
        return float(promo)
    regular = row.get("regular_price")
    return float(regular) if regular is not None else None


def _latest_observation_date(conn) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(observation_date) FROM rpm_price_observations"
    ).fetchone()
    return row[0] if row and row[0] else None


def _resolve_date(conn, requested: Optional[str]) -> Optional[str]:
    if requested:
        return requested
    return _latest_observation_date(conn)


def _pct(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / old * 100, 2)


# ── Low-level queries ────────────────────────────────────────────────────

def _observations_for_date(conn, target_date: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT o.*, p.canonical_name AS product_name, p.category AS product_category,
               p.barcode AS product_barcode, p.brand AS product_brand,
               p.size_value, p.size_unit, p.subcategory,
               r.code AS retailer_code, r.name_he AS retailer_name_he,
               r.name_en AS retailer_name_en
          FROM rpm_price_observations o
          JOIN rpm_products  p ON p.id = o.product_id
          JOIN rpm_retailers r ON r.id = o.retailer_id
         WHERE o.observation_date = ?
        """,
        (target_date,),
    ).fetchall()
    return [dict(r) for r in rows]


def _observations_in_range(
    conn, start_date: str, end_date: str, product_id: Optional[int] = None
) -> List[Dict[str, Any]]:
    params: list = [start_date, end_date]
    sql = (
        "SELECT o.*, p.canonical_name AS product_name, r.code AS retailer_code, "
        "       r.name_he AS retailer_name_he "
        "  FROM rpm_price_observations o "
        "  JOIN rpm_products  p ON p.id = o.product_id "
        "  JOIN rpm_retailers r ON r.id = o.retailer_id "
        " WHERE o.observation_date BETWEEN ? AND ?"
    )
    if product_id is not None:
        sql += " AND o.product_id = ?"
        params.append(product_id)
    sql += " ORDER BY o.observation_date ASC, r.name_en ASC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── Product-level comparisons ─────────────────────────────────────────────

def _group_by_product(observations: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for row in observations:
        pid = row["product_id"]
        if pid is None:
            continue
        grouped.setdefault(pid, []).append(row)
    return grouped


def _product_snapshot(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the per-product comparison row for one date."""

    sample = rows[0]
    prices: List[float] = []
    per_retailer: List[Dict[str, Any]] = []
    promo_count = 0

    for row in rows:
        effective = _effective_price(row)
        if effective is None:
            continue
        prices.append(effective)
        if row.get("promo_price") is not None:
            promo_count += 1
        per_retailer.append({
            "retailer_code":  row["retailer_code"],
            "retailer_name":  row["retailer_name_he"],
            "regular_price":  row.get("regular_price"),
            "promo_price":    row.get("promo_price"),
            "effective_price": effective,
            "promo_type":     row.get("promo_type"),
            "in_stock":       bool(row.get("in_stock")),
            "unit_price":     row.get("unit_price"),
            "url":            row.get("product_url"),
            "match_confidence": row.get("match_confidence"),
        })

    if not prices:
        return {}

    min_price = min(prices)
    max_price = max(prices)
    avg_price = round(statistics.fmean(prices), 2)
    spread_pct = round((max_price - min_price) / min_price * 100, 2) if min_price else 0.0
    cov = round(statistics.pstdev(prices) / avg_price, 3) if avg_price else 0.0

    # Who is the cheapest / most expensive?
    sorted_by_price = sorted(per_retailer, key=lambda r: r["effective_price"])
    cheapest = sorted_by_price[0]
    most_expensive = sorted_by_price[-1]

    return {
        "product_id":      sample["product_id"],
        "product_name":    sample["product_name"],
        "barcode":         sample["product_barcode"],
        "brand":           sample["product_brand"],
        "category":        sample["product_category"],
        "subcategory":     sample.get("subcategory"),
        "size_value":      sample.get("size_value"),
        "size_unit":       sample.get("size_unit"),
        "retailers_count": len(per_retailer),
        "min_price":       round(min_price, 2),
        "max_price":       round(max_price, 2),
        "avg_price":       avg_price,
        "spread_pct":      spread_pct,
        "cov":             cov,
        "promo_count":     promo_count,
        "has_promo":       promo_count > 0,
        "cheapest_retailer": cheapest["retailer_name"],
        "cheapest_retailer_code": cheapest["retailer_code"],
        "most_expensive_retailer": most_expensive["retailer_name"],
        "per_retailer":    per_retailer,
    }


def product_comparison_for_date(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Return per-product comparison rows for a single day."""

    with connection_scope() as conn:
        resolved = _resolve_date(conn, target_date)
        if resolved is None:
            return {"date": None, "products": []}
        observations = _observations_for_date(conn, resolved)
        grouped = _group_by_product(observations)
        products = [_product_snapshot(rows) for rows in grouped.values()]
        products = [p for p in products if p]
        products.sort(key=lambda p: p["product_name"])
    return {"date": resolved, "products": products}


# ── Trend computation ─────────────────────────────────────────────────────

def _market_series(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse daily rows into a daily market aggregate for one product."""

    by_day: Dict[str, List[float]] = {}
    per_retailer: Dict[str, Dict[str, float]] = {}
    for row in observations:
        effective = _effective_price(row)
        if effective is None:
            continue
        d = row["observation_date"]
        by_day.setdefault(d, []).append(effective)
        per_retailer.setdefault(row["retailer_code"], {})[d] = effective

    series = []
    for day in sorted(by_day.keys()):
        prices = by_day[day]
        series.append({
            "date": day,
            "min":  round(min(prices), 2),
            "max":  round(max(prices), 2),
            "avg":  round(statistics.fmean(prices), 2),
            "count": len(prices),
        })
    return series, per_retailer


def product_trend(product_id: int, days: int = 30) -> Dict[str, Any]:
    with connection_scope() as conn:
        latest = _latest_observation_date(conn)
        if latest is None:
            return {"product_id": product_id, "series": [], "per_retailer": {}}
        end = date.fromisoformat(latest)
        start = end - timedelta(days=days - 1)
        observations = _observations_in_range(
            conn, start.isoformat(), end.isoformat(), product_id=product_id
        )

        product_row = conn.execute(
            "SELECT canonical_name, brand, barcode, category FROM rpm_products WHERE id = ?",
            (product_id,),
        ).fetchone()

    series, per_retailer = _market_series(observations)

    # Short-term change metrics
    def _avg_on(day_str: str) -> Optional[float]:
        match = next((p for p in series if p["date"] == day_str), None)
        return match["avg"] if match else None

    today_str = series[-1]["date"] if series else None
    change = {}
    if today_str:
        today_avg = _avg_on(today_str)
        change["today_avg"] = today_avg

        def _offset(days_back: int) -> Tuple[Optional[float], Optional[float]]:
            ref_day = (date.fromisoformat(today_str) - timedelta(days=days_back)).isoformat()
            ref_avg = _avg_on(ref_day)
            return ref_avg, _pct(ref_avg, today_avg)

        change["d1_ref"], change["d1_change_pct"] = _offset(1)
        change["d7_ref"], change["d7_change_pct"] = _offset(7)
        change["d30_ref"], change["d30_change_pct"] = _offset(30)

    trend_label = _label_trend(series)

    return {
        "product_id": product_id,
        "product_name": product_row["canonical_name"] if product_row else None,
        "barcode": product_row["barcode"] if product_row else None,
        "brand": product_row["brand"] if product_row else None,
        "category": product_row["category"] if product_row else None,
        "series": series,
        "per_retailer": per_retailer,
        "change": change,
        "trend_label": trend_label,
    }


def _label_trend(series: List[Dict[str, Any]]) -> str:
    if len(series) < 2:
        return "unknown"
    window = series[-ALERT_THRESHOLDS["trend_consecutive"] - 1:]
    if len(window) < 2:
        return "stable"
    ups = sum(
        1 for a, b in zip(window, window[1:]) if b["avg"] > a["avg"] * 1.005
    )
    downs = sum(
        1 for a, b in zip(window, window[1:]) if b["avg"] < a["avg"] * 0.995
    )
    required = ALERT_THRESHOLDS["trend_consecutive"]
    if ups >= required:
        return "rising"
    if downs >= required:
        return "falling"
    return "stable"


# ── Alert generation ─────────────────────────────────────────────────────

def _load_previous_day_map(conn, prev_date: str) -> Dict[Tuple[int, int], Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM rpm_price_observations WHERE observation_date = ?",
        (prev_date,),
    ).fetchall()
    return {(r["product_id"], r["retailer_id"]): dict(r) for r in rows}


def generate_alerts_for_date(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Recompute and persist the alerts for a given day.

    The function is idempotent — prior alerts for the day are wiped before
    the fresh ones are written. Returns a small summary for callers.
    """

    with connection_scope() as conn:
        resolved = _resolve_date(conn, target_date)
        if resolved is None:
            return {"date": None, "alerts_created": 0}
        prev_date = (date.fromisoformat(resolved) - timedelta(days=1)).isoformat()

        today_rows = _observations_for_date(conn, resolved)
        prev_map = _load_previous_day_map(conn, prev_date)

        grouped = _group_by_product(today_rows)

        alerts: List[tuple] = []

        # Per-product cross-retailer checks
        for product_id, rows in grouped.items():
            snapshot = _product_snapshot(rows)
            if not snapshot:
                continue

            product_name = snapshot["product_name"]
            avg_price = snapshot["avg_price"]
            cheapest_margin = ALERT_THRESHOLDS["cheapest_margin_pct"]
            expensive_margin = ALERT_THRESHOLDS["expensive_margin_pct"]

            # High cross-retailer volatility
            if snapshot["cov"] >= ALERT_THRESHOLDS["cross_retailer_cov"]:
                alerts.append((
                    resolved, "high_volatility", "warning", product_id, None,
                    f"פערי מחיר גבוהים בין הרשתות — {product_name}",
                    f"פער של {snapshot['spread_pct']}% בין הרשת הזולה ליקרה",
                    snapshot["spread_pct"], snapshot["cov"],
                ))

            # Cheapest / most expensive retailer flags (vs. market average)
            for entry in snapshot["per_retailer"]:
                price = entry["effective_price"]
                delta_pct = (price - avg_price) / avg_price * 100 if avg_price else 0
                if delta_pct <= -cheapest_margin:
                    alerts.append((
                        resolved, "cheapest", "info", product_id,
                        _retailer_id(conn, entry["retailer_code"]),
                        f"מחיר נמוך במיוחד — {product_name} ב{entry['retailer_name']}",
                        f"מחיר נמוך ב-{abs(round(delta_pct, 1))}% מהממוצע בשוק",
                        round(delta_pct, 2), price,
                    ))
                elif delta_pct >= expensive_margin:
                    alerts.append((
                        resolved, "most_expensive", "warning", product_id,
                        _retailer_id(conn, entry["retailer_code"]),
                        f"מחיר גבוה במיוחד — {product_name} ב{entry['retailer_name']}",
                        f"מחיר גבוה ב-{round(delta_pct, 1)}% מהממוצע בשוק",
                        round(delta_pct, 2), price,
                    ))

        # Day-over-day changes per (product, retailer)
        daily_threshold = ALERT_THRESHOLDS["daily_change_pct"]
        seen_today: set = set()
        for row in today_rows:
            key = (row["product_id"], row["retailer_id"])
            seen_today.add(key)
            today_price = _effective_price(row)
            prev_row = prev_map.get(key)
            prev_price = _effective_price(prev_row) if prev_row else None

            if today_price is None:
                continue

            # New product on that retailer
            if prev_row is None:
                alerts.append((
                    resolved, "new_product", "info", row["product_id"], row["retailer_id"],
                    f"מוצר חדש — {row['product_name']} ב{row['retailer_name_he']}",
                    "המוצר לא הופיע בתצפיות הקודמות של רשת זו",
                    None, today_price,
                ))
            else:
                change_pct = _pct(prev_price, today_price)
                if change_pct is not None:
                    if change_pct >= daily_threshold:
                        alerts.append((
                            resolved, "price_jump", "critical", row["product_id"], row["retailer_id"],
                            f"עליית מחיר חדה — {row['product_name']} ב{row['retailer_name_he']}",
                            f"עלייה של {change_pct}% ביממה האחרונה",
                            change_pct, today_price,
                        ))
                    elif change_pct <= -daily_threshold:
                        alerts.append((
                            resolved, "price_drop", "warning", row["product_id"], row["retailer_id"],
                            f"ירידת מחיר חדה — {row['product_name']} ב{row['retailer_name_he']}",
                            f"ירידה של {abs(change_pct)}% ביממה האחרונה",
                            change_pct, today_price,
                        ))

            # Promo start / end flags
            if prev_row is not None:
                prev_promo = prev_row.get("promo_price")
                if row.get("promo_price") is not None and prev_promo is None:
                    alerts.append((
                        resolved, "promo_start", "info", row["product_id"], row["retailer_id"],
                        f"מבצע חדש — {row['product_name']} ב{row['retailer_name_he']}",
                        f"{row.get('promo_type') or 'מבצע'} במחיר {row['promo_price']} ₪",
                        None, float(row["promo_price"]),
                    ))
                elif row.get("promo_price") is None and prev_promo is not None:
                    alerts.append((
                        resolved, "promo_end", "info", row["product_id"], row["retailer_id"],
                        f"סיום מבצע — {row['product_name']} ב{row['retailer_name_he']}",
                        "המוצר יצא מהמחיר המבצעי",
                        None, float(prev_promo),
                    ))

        # Missing products (present yesterday, absent today)
        for key, prev_row in prev_map.items():
            if key in seen_today:
                continue
            product_id, retailer_id = key
            alerts.append((
                resolved, "missing_product", "warning", product_id, retailer_id,
                f"מוצר לא אותר היום — {prev_row.get('source_product_name')}",
                "המוצר היה זמין אתמול אך לא אותר הבוקר",
                None, None,
            ))

        # Collection failures from the log
        failures = conn.execute(
            """
            SELECT l.*, r.name_he AS retailer_name_he
              FROM rpm_collection_log l
              JOIN rpm_retailers r ON r.id = l.retailer_id
             WHERE l.run_date = ? AND l.status = 'failed'
            """,
            (resolved,),
        ).fetchall()
        for fail in failures:
            alerts.append((
                resolved, "collection_failure", "critical", None, fail["retailer_id"],
                f"כשל באיסוף נתונים — {fail['retailer_name_he']}",
                fail["error_message"] or "המקור אינו זמין",
                None, None,
            ))

        clear_alerts_for_date(conn, resolved)
        if alerts:
            insert_alerts(conn, alerts)

    return {"date": resolved, "alerts_created": len(alerts)}


def _retailer_id(conn, code: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM rpm_retailers WHERE code = ?", (code,)).fetchone()
    return row["id"] if row else None


def alerts_for_date(target_date: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with connection_scope() as conn:
        resolved = _resolve_date(conn, target_date)
        if resolved is None:
            return []
        rows = conn.execute(
            """
            SELECT a.*, p.canonical_name AS product_name, r.name_he AS retailer_name_he
              FROM rpm_alerts a
         LEFT JOIN rpm_products  p ON p.id = a.product_id
         LEFT JOIN rpm_retailers r ON r.id = a.retailer_id
             WHERE a.alert_date = ?
             ORDER BY CASE a.severity
                          WHEN 'critical' THEN 0
                          WHEN 'warning'  THEN 1
                          ELSE 2 END,
                      a.id DESC
             LIMIT ?
            """,
            (resolved, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ── High-level dashboard rollups ──────────────────────────────────────────

def daily_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Executive screen rollup."""

    with connection_scope() as conn:
        resolved = _resolve_date(conn, target_date)
        if resolved is None:
            return {"date": None}
        prev = (date.fromisoformat(resolved) - timedelta(days=1)).isoformat()

        today_rows = _observations_for_date(conn, resolved)
        prev_map = _load_previous_day_map(conn, prev)

        # Scalar KPIs
        retailers_today = {r["retailer_id"] for r in today_rows}
        active_retailers_total = conn.execute(
            "SELECT COUNT(*) FROM rpm_retailers WHERE active = 1"
        ).fetchone()[0]

        products_count = len({r["product_id"] for r in today_rows if r["product_id"]})
        promo_count = sum(1 for r in today_rows if r.get("promo_price") is not None)

        significant_changes = 0
        threshold = ALERT_THRESHOLDS["daily_change_pct"]
        for row in today_rows:
            key = (row["product_id"], row["retailer_id"])
            prev_row = prev_map.get(key)
            if not prev_row:
                continue
            change = _pct(_effective_price(prev_row), _effective_price(row))
            if change is not None and abs(change) >= threshold:
                significant_changes += 1

        # Retailer averages (for cheapest / most expensive of the day)
        retailer_prices: Dict[str, List[float]] = {}
        retailer_names: Dict[str, str] = {}
        for row in today_rows:
            price = _effective_price(row)
            if price is None:
                continue
            code = row["retailer_code"]
            retailer_prices.setdefault(code, []).append(price)
            retailer_names[code] = row["retailer_name_he"]
        retailer_avgs = [
            {
                "code": code,
                "name": retailer_names[code],
                "avg_price": round(statistics.fmean(prices), 2),
                "sample_count": len(prices),
            }
            for code, prices in retailer_prices.items()
        ]
        retailer_avgs.sort(key=lambda x: x["avg_price"])
        cheapest = retailer_avgs[0] if retailer_avgs else None
        most_expensive = retailer_avgs[-1] if retailer_avgs else None

        # Per-product snapshots for top lists
        grouped = _group_by_product(today_rows)
        snapshots: List[Dict[str, Any]] = []
        prev_by_product: Dict[int, List[float]] = {}
        for row in _load_previous_day_map(conn, prev).values():
            if row["product_id"] is None:
                continue
            price = _effective_price(row)
            if price is not None:
                prev_by_product.setdefault(row["product_id"], []).append(price)

        for product_id, rows in grouped.items():
            snap = _product_snapshot(rows)
            if not snap:
                continue
            prev_prices = prev_by_product.get(product_id)
            prev_avg = round(statistics.fmean(prev_prices), 2) if prev_prices else None
            snap["prev_avg_price"] = prev_avg
            snap["day_change_pct"] = _pct(prev_avg, snap["avg_price"])
            snapshots.append(snap)

        top_spread = sorted(snapshots, key=lambda s: s["spread_pct"], reverse=True)[:10]
        top_drops = sorted(
            [s for s in snapshots if (s.get("day_change_pct") or 0) < 0],
            key=lambda s: s["day_change_pct"],
        )[:10]
        top_jumps = sorted(
            [s for s in snapshots if (s.get("day_change_pct") or 0) > 0],
            key=lambda s: s["day_change_pct"], reverse=True,
        )[:10]

        return {
            "date": resolved,
            "kpis": {
                "products_collected":   products_count,
                "retailers_active":     len(retailers_today),
                "retailers_total":      active_retailers_total,
                "promos_active":        promo_count,
                "significant_changes":  significant_changes,
            },
            "retailer_pricing": {
                "cheapest":       cheapest,
                "most_expensive": most_expensive,
                "all":            retailer_avgs,
            },
            "top_spread": _compact_snapshots(top_spread),
            "top_drops":  _compact_snapshots(top_drops),
            "top_jumps":  _compact_snapshots(top_jumps),
        }


def _compact_snapshots(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = (
        "product_id", "product_name", "barcode", "category",
        "min_price", "max_price", "avg_price", "spread_pct",
        "day_change_pct", "cheapest_retailer", "most_expensive_retailer",
        "retailers_count", "has_promo",
    )
    return [{k: snap.get(k) for k in keys} for snap in snapshots]


def morning_brief(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Human-readable operational summary for the morning digest."""

    summary = daily_summary(target_date)
    if not summary.get("date"):
        return {"date": None, "lines": ["אין נתונים זמינים"], "alerts": []}

    resolved = summary["date"]
    alerts = alerts_for_date(resolved, limit=10)

    kpis = summary["kpis"]
    cheapest = summary["retailer_pricing"].get("cheapest")
    expensive = summary["retailer_pricing"].get("most_expensive")
    top_spread = summary["top_spread"][0] if summary["top_spread"] else None

    lines = [
        f"נסרקו {kpis['retailers_active']} רשתות מתוך {kpis['retailers_total']}",
        f"אותרו {kpis['products_collected']} מוצרים של לימן שליסל",
        f"{kpis['promos_active']} מוצרים נמצאים כרגע במבצע",
        f"{kpis['significant_changes']} מוצרים הראו שינוי מחיר מהותי",
    ]
    if top_spread:
        lines.append(
            f"המוצר עם פער המחיר הגבוה ביותר: {top_spread['product_name']} "
            f"({top_spread['spread_pct']}%)"
        )
    if cheapest:
        lines.append(f"הרשת הזולה ביותר בממוצע: {cheapest['name']} ({cheapest['avg_price']} ₪)")
    if expensive:
        lines.append(f"הרשת היקרה ביותר בממוצע: {expensive['name']} ({expensive['avg_price']} ₪)")

    return {"date": resolved, "lines": lines, "alerts": alerts, "summary": summary}


def list_products() -> List[Dict[str, Any]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT id, canonical_name AS name, brand, barcode, category, subcategory,
                   size_value, size_unit
              FROM rpm_products
             WHERE active = 1
             ORDER BY canonical_name
            """
        ).fetchall()
    return [dict(r) for r in rows]


def list_retailers() -> List[Dict[str, Any]]:
    with connection_scope() as conn:
        rows = conn.execute(
            "SELECT id, code, name_he, name_en, source_url, last_collected, last_status, active "
            "FROM rpm_retailers ORDER BY name_en"
        ).fetchall()
    return [dict(r) for r in rows]


def list_categories() -> List[str]:
    with connection_scope() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM rpm_products WHERE category IS NOT NULL "
            "ORDER BY category"
        ).fetchall()
    return [r[0] for r in rows]


def anomalies_report(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Build the "חריגות" dashboard screen payload."""

    comparison = product_comparison_for_date(target_date)
    products = comparison["products"]

    high_variance = sorted(
        products, key=lambda p: p["cov"], reverse=True
    )[:10]

    resolved_date = comparison["date"]
    day_changes: List[Dict[str, Any]] = []
    if resolved_date:
        with connection_scope() as conn:
            prev = (date.fromisoformat(resolved_date) - timedelta(days=1)).isoformat()
            today_rows = _observations_for_date(conn, resolved_date)
            prev_map = _load_previous_day_map(conn, prev)

        prev_group: Dict[int, List[float]] = {}
        for row in prev_map.values():
            if row["product_id"] is None:
                continue
            p = _effective_price(row)
            if p is not None:
                prev_group.setdefault(row["product_id"], []).append(p)

        for snapshot in products:
            prev_prices = prev_group.get(snapshot["product_id"])
            if not prev_prices:
                continue
            prev_avg = statistics.fmean(prev_prices)
            change = _pct(prev_avg, snapshot["avg_price"])
            if change is None:
                continue
            if abs(change) >= ALERT_THRESHOLDS["daily_change_pct"]:
                day_changes.append({
                    **{k: snapshot[k] for k in (
                        "product_id", "product_name", "barcode",
                        "category", "avg_price", "min_price", "max_price",
                        "spread_pct",
                    )},
                    "day_change_pct": change,
                    "prev_avg_price": round(prev_avg, 2),
                })

    sharp_jumps = sorted(
        [c for c in day_changes if c["day_change_pct"] > 0],
        key=lambda c: c["day_change_pct"], reverse=True,
    )
    sharp_drops = sorted(
        [c for c in day_changes if c["day_change_pct"] < 0],
        key=lambda c: c["day_change_pct"],
    )

    # Low/medium match confidence observations
    suspicious_matches: List[Dict[str, Any]] = []
    if resolved_date:
        with connection_scope() as conn:
            rows = conn.execute(
                """
                SELECT o.source_product_name, o.match_confidence, o.observation_date,
                       p.canonical_name AS product_name, r.name_he AS retailer_name_he
                  FROM rpm_price_observations o
             LEFT JOIN rpm_products  p ON p.id = o.product_id
             LEFT JOIN rpm_retailers r ON r.id = o.retailer_id
                 WHERE o.observation_date = ?
                   AND o.match_confidence IN ('Low', 'Medium')
                """,
                (resolved_date,),
            ).fetchall()
        suspicious_matches = [dict(r) for r in rows]

    # Incomplete coverage (products appearing in fewer than half the retailers)
    with connection_scope() as conn:
        total_retailers = conn.execute(
            "SELECT COUNT(*) FROM rpm_retailers WHERE active = 1"
        ).fetchone()[0] or 1
    threshold = max(1, total_retailers // 2)
    incomplete = [
        {
            "product_id": p["product_id"],
            "product_name": p["product_name"],
            "retailers_count": p["retailers_count"],
            "missing_from": total_retailers - p["retailers_count"],
        }
        for p in products if p["retailers_count"] < threshold
    ]

    return {
        "date": resolved_date,
        "high_variance_products": high_variance,
        "sharp_jumps": sharp_jumps,
        "sharp_drops": sharp_drops,
        "incomplete_coverage": incomplete,
        "suspicious_matches": suspicious_matches,
    }
