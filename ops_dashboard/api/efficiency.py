from fastapi import APIRouter, Query
from typing import Optional
from ops_dashboard.data.database import query_metrics, query_metrics_previous_period, get_targets
from ops_dashboard.models.schemas import KPIValue, TimeSeriesPoint, TimeSeriesData, SiteBreakdown

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


def _compute_efficiency_kpis(rows, prev_rows, targets):
    n = len(rows) or 1
    pn = len(prev_rows) or 1

    # OEE (avg)
    oee = sum(r["oee_score"] for r in rows) / n * 100
    prev_oee = sum(r["oee_score"] for r in prev_rows) / pn * 100 if prev_rows else oee

    # Downtime Rate
    tah = sum(r["available_hours"] for r in rows) or 1
    tdh = sum(r["downtime_hours"] for r in rows)
    pah = sum(r["available_hours"] for r in prev_rows) or 1
    pdh = sum(r["downtime_hours"] for r in prev_rows)
    dt = _safe_div(tdh, tah) * 100
    prev_dt = _safe_div(pdh, pah) * 100

    # Changeover Time (avg)
    co = sum(r["changeover_hours"] for r in rows) / n
    prev_co = sum(r["changeover_hours"] for r in prev_rows) / pn if prev_rows else co

    # Line Efficiency
    tlo = sum(r["line_output"] for r in rows)
    tlc = sum(r["line_capacity"] for r in rows) or 1
    plo = sum(r["line_output"] for r in prev_rows)
    plc = sum(r["line_capacity"] for r in prev_rows) or 1
    le = _safe_div(tlo, tlc) * 100
    prev_le = _safe_div(plo, plc) * 100

    return [
        _kpi("oee", "OEE", oee, prev_oee, "%", ">=", targets),
        _kpi("downtime_rate", "Downtime Rate", dt, prev_dt, "%", "<=", targets),
        _kpi("changeover_time", "Changeover Time", co, prev_co, "hours", "<=", targets),
        _kpi("line_efficiency", "Line Efficiency", le, prev_le, "%", ">=", targets),
    ]


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/kpis")
def efficiency_kpis(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    kpis = _compute_efficiency_kpis(rows, prev_rows, targets)
    return [k for k in kpis if targets.get(k.metric_name, {}).get("enabled", True)]


@router.get("/oee-trend")
def oee_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = []
        daily[d].append(r["oee_score"])
    points = [TimeSeriesPoint(timestamp=d, value=round(sum(v) / len(v) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="oee", data_points=points, unit="%")


@router.get("/downtime-trend")
def downtime_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"dh": 0, "ah": 0}
        daily[d]["dh"] += r["downtime_hours"]
        daily[d]["ah"] += r["available_hours"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["dh"], v["ah"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="downtime_rate", data_points=points, unit="%")


@router.get("/oee-by-site")
def oee_by_site(
    product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(None, product_line, time_range, date_from, date_to)
    site_data = {}
    for r in rows:
        s = r["site"]
        if s not in site_data: site_data[s] = []
        site_data[s].append(r["oee_score"])
    return [SiteBreakdown(site=s, value=round(sum(v) / len(v) * 100, 2)) for s, v in sorted(site_data.items())]
