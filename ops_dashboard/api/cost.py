from fastapi import APIRouter, Query
from typing import Optional
from ops_dashboard.data.database import query_metrics, query_metrics_previous_period, get_targets
from ops_dashboard.models.schemas import KPIValue, TimeSeriesPoint, TimeSeriesData, CategoryBreakdown

router = APIRouter()


def _safe_div(a, b, default=0):
    return a / b if b else default


def _kpi(name, display, cur, prev, unit, direction, targets):
    t = targets.get(name, {})
    if direction == "<=":
        trend_good = cur <= prev
    else:
        trend_good = cur >= prev
    return KPIValue(
        metric_name=name, display_name=display,
        current_value=round(cur, 2), previous_value=round(prev, 2),
        unit=unit,
        trend="down" if cur < prev else ("up" if cur > prev else "flat"),
        trend_is_good=trend_good,
        target=t.get("value"), target_direction=t.get("direction"),
    )


def _compute_cost_kpis(rows, prev_rows, targets):
    n = len(rows) or 1
    pn = len(prev_rows) or 1

    # Waste %
    tw = sum(r["waste_units"] for r in rows)
    tp = sum(r["total_produced_units"] for r in rows) or 1
    pw = sum(r["waste_units"] for r in prev_rows)
    pp = sum(r["total_produced_units"] for r in prev_rows) or 1
    waste = _safe_div(tw, tp) * 100
    prev_waste = _safe_div(pw, pp) * 100

    # Cost per Batch (avg)
    avg_cpb = sum(r["cost_per_batch_amount"] for r in rows) / n
    prev_cpb = sum(r["cost_per_batch_amount"] for r in prev_rows) / pn if prev_rows else avg_cpb

    # COPQ (total)
    copq = sum(r["copq_amount"] for r in rows) / n
    prev_copq = sum(r["copq_amount"] for r in prev_rows) / pn if prev_rows else copq

    # Scrap Cost (avg daily)
    scrap = sum(r["scrap_cost_amount"] for r in rows) / n
    prev_scrap = sum(r["scrap_cost_amount"] for r in prev_rows) / pn if prev_rows else scrap

    # Rework Rate
    trw = sum(r["rework_units"] for r in rows)
    rework = _safe_div(trw, tp) * 100
    prw = sum(r["rework_units"] for r in prev_rows)
    prev_rework = _safe_div(prw, pp) * 100

    # Inventory Carrying Cost (daily avg)
    inv_cost = sum(r["inventory_value"] * r["carrying_cost_rate"] / 365 for r in rows) / n
    prev_inv = sum(r["inventory_value"] * r["carrying_cost_rate"] / 365 for r in prev_rows) / pn if prev_rows else inv_cost

    # Production Cost Variance
    tpc = sum(r["planned_cost"] for r in rows) or 1
    tac = sum(r["actual_cost"] for r in rows)
    ppc = sum(r["planned_cost"] for r in prev_rows) or 1
    pac = sum(r["actual_cost"] for r in prev_rows)
    var_ = abs(tac - tpc) / tpc * 100
    prev_var = abs(pac - ppc) / ppc * 100

    return [
        _kpi("waste_percentage", "Waste %", waste, prev_waste, "%", "<=", targets),
        _kpi("cost_per_batch", "Cost per Batch", avg_cpb, prev_cpb, "$", "<=", targets),
        _kpi("copq", "Cost of Poor Quality", copq, prev_copq, "$", "<=", targets),
        _kpi("scrap_cost", "Scrap Cost", scrap, prev_scrap, "$", "<=", targets),
        _kpi("rework_rate", "Rework Rate", rework, prev_rework, "%", "<=", targets),
        _kpi("inventory_carrying_cost", "Inventory Carrying Cost", inv_cost, prev_inv, "$", "<=", targets),
        _kpi("production_cost_variance", "Production Cost Variance", var_, prev_var, "%", "<=", targets),
    ]


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/kpis")
def cost_kpis(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    kpis = _compute_cost_kpis(rows, prev_rows, targets)
    return [k for k in kpis if targets.get(k.metric_name, {}).get("enabled", True)]


@router.get("/waste-trend")
def waste_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"waste": 0, "produced": 0}
        daily[d]["waste"] += r["waste_units"]
        daily[d]["produced"] += r["total_produced_units"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["waste"], v["produced"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="waste_percentage", data_points=points, unit="%")


@router.get("/cost-per-batch-trend")
def cpb_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = []
        daily[d].append(r["cost_per_batch_amount"])
    points = [TimeSeriesPoint(timestamp=d, value=round(sum(v) / len(v), 0)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="cost_per_batch", data_points=points, unit="$")


@router.get("/inventory-trend")
def inventory_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        daily[d] = daily.get(d, 0) + r["inventory_value"] * r["carrying_cost_rate"] / 365
    points = [TimeSeriesPoint(timestamp=d, value=round(v, 0)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="inventory_carrying_cost", data_points=points, unit="$")


@router.get("/breakdown")
def cost_breakdown_by_product(
    site: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, None, time_range, date_from, date_to)
    by_product = {}
    for r in rows:
        p = r["product_line"]
        by_product[p] = by_product.get(p, 0) + r["cogs_amount"]
    return [CategoryBreakdown(category=p, value=round(v, 0)) for p, v in sorted(by_product.items())]


@router.get("/rework-trend")
def rework_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"rw": 0, "prod": 0}
        daily[d]["rw"] += r["rework_units"]
        daily[d]["prod"] += r["total_produced_units"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["rw"], v["prod"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="rework_rate", data_points=points, unit="%")


@router.get("/copq-trend")
def copq_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        daily[d] = daily.get(d, 0) + r["copq_amount"]
    points = [TimeSeriesPoint(timestamp=d, value=round(v, 0)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="copq", data_points=points, unit="$")


@router.get("/variance-trend")
def variance_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"planned": 0, "actual": 0}
        daily[d]["planned"] += r["planned_cost"]
        daily[d]["actual"] += r["actual_cost"]
    points = [TimeSeriesPoint(timestamp=d, value=round(abs(v["actual"] - v["planned"]) / max(v["planned"], 1) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="production_cost_variance", data_points=points, unit="%")
