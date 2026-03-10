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


def _compute_service_kpis(rows, prev_rows, targets):
    n = len(rows) or 1
    pn = len(prev_rows) or 1

    # Supply vs Demand
    ts = sum(r["supply_units"] for r in rows)
    td = sum(r["demand_units"] for r in rows) or 1
    ps = sum(r["supply_units"] for r in prev_rows) or 1
    pd_ = sum(r["demand_units"] for r in prev_rows) or 1
    sd = _safe_div(ts, td) * 100
    prev_sd = _safe_div(ps, pd_) * 100

    # OTIF
    tot = sum(r["otif_orders_total"] for r in rows) or 1
    tom = sum(r["otif_orders_met"] for r in rows)
    pot = sum(r["otif_orders_total"] for r in prev_rows) or 1
    pom = sum(r["otif_orders_met"] for r in prev_rows)
    otif = _safe_div(tom, tot) * 100
    prev_otif = _safe_div(pom, pot) * 100

    # Lead Time
    avg_lead = sum(r["lead_time_days"] for r in rows) / n
    prev_lead = sum(r["lead_time_days"] for r in prev_rows) / pn if prev_rows else avg_lead

    # SLA Adherence
    tst = sum(r["sla_total_orders"] for r in rows) or 1
    tsm = sum(r["sla_met_orders"] for r in rows)
    pst = sum(r["sla_total_orders"] for r in prev_rows) or 1
    psm = sum(r["sla_met_orders"] for r in prev_rows)
    sla = _safe_div(tsm, tst) * 100
    prev_sla = _safe_div(psm, pst) * 100

    # Response Time
    avg_resp = sum(r["response_time_hours"] for r in rows) / n
    prev_resp = sum(r["response_time_hours"] for r in prev_rows) / pn if prev_rows else avg_resp

    # Schedule Adherence
    tsb = sum(r["scheduled_batches"] for r in rows) or 1
    tcs = sum(r["completed_scheduled"] for r in rows)
    psb = sum(r["scheduled_batches"] for r in prev_rows) or 1
    pcs = sum(r["completed_scheduled"] for r in prev_rows)
    sched = _safe_div(tcs, tsb) * 100
    prev_sched = _safe_div(pcs, psb) * 100

    # Production Throughput (avg per day)
    throughput = sum(r["production_output_units"] for r in rows) / n
    prev_throughput = sum(r["production_output_units"] for r in prev_rows) / pn if prev_rows else throughput

    # Backorder Rate
    tbo = sum(r["backorders"] for r in rows)
    tto = sum(r["total_orders"] for r in rows) or 1
    pbo = sum(r["backorders"] for r in prev_rows)
    pto = sum(r["total_orders"] for r in prev_rows) or 1
    bo = _safe_div(tbo, tto) * 100
    prev_bo = _safe_div(pbo, pto) * 100

    # Order Cycle Time
    avg_oct = sum(r["order_cycle_days"] for r in rows) / n
    prev_oct = sum(r["order_cycle_days"] for r in prev_rows) / pn if prev_rows else avg_oct

    # Forecast Accuracy
    tfd = sum(r["forecast_demand"] for r in rows) or 1
    tad = sum(r["actual_demand"] for r in rows) or 1
    fc_acc = (1 - abs(tfd - tad) / tad) * 100
    pfd = sum(r["forecast_demand"] for r in prev_rows) or 1
    pad = sum(r["actual_demand"] for r in prev_rows) or 1
    prev_fc = (1 - abs(pfd - pad) / pad) * 100

    # Capacity Utilization
    tac = sum(r["available_capacity"] for r in rows) or 1
    tuc = sum(r["used_capacity"] for r in rows)
    pac = sum(r["available_capacity"] for r in prev_rows) or 1
    puc = sum(r["used_capacity"] for r in prev_rows)
    cap_u = _safe_div(tuc, tac) * 100
    prev_cap = _safe_div(puc, pac) * 100

    return [
        _kpi("supply_vs_demand", "Supply vs Demand", sd, prev_sd, "%", ">=", targets),
        _kpi("otif_rate", "OTIF Rate", otif, prev_otif, "%", ">=", targets),
        _kpi("lead_time", "Lead Time", avg_lead, prev_lead, "days", "<=", targets),
        _kpi("sla_adherence", "SLA Adherence", sla, prev_sla, "%", ">=", targets),
        _kpi("response_time", "Response Time", avg_resp, prev_resp, "hours", "<=", targets),
        _kpi("schedule_adherence", "Schedule Adherence", sched, prev_sched, "%", ">=", targets),
        _kpi("production_throughput", "Production Throughput", throughput, prev_throughput, "units", ">=", targets),
        _kpi("backorder_rate", "Backorder Rate", bo, prev_bo, "%", "<=", targets),
        _kpi("order_cycle_time", "Order Cycle Time", avg_oct, prev_oct, "days", "<=", targets),
        _kpi("forecast_accuracy", "Forecast Accuracy", fc_acc, prev_fc, "%", ">=", targets),
        _kpi("capacity_utilization", "Capacity Utilization", cap_u, prev_cap, "%", ">=", targets),
    ]


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/kpis")
def service_kpis(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    kpis = _compute_service_kpis(rows, prev_rows, targets)
    return [k for k in kpis if targets.get(k.metric_name, {}).get("enabled", True)]


@router.get("/supply-demand")
def supply_demand_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"supply": 0, "demand": 0}
        daily[d]["supply"] += r["supply_units"]
        daily[d]["demand"] += r["demand_units"]
    supply_pts = [TimeSeriesPoint(timestamp=d, value=v["supply"]) for d, v in sorted(daily.items())]
    demand_pts = [TimeSeriesPoint(timestamp=d, value=v["demand"]) for d, v in sorted(daily.items())]
    return {
        "supply": TimeSeriesData(metric_name="supply", data_points=supply_pts, unit="units"),
        "demand": TimeSeriesData(metric_name="demand", data_points=demand_pts, unit="units"),
    }


@router.get("/otif-trend")
def otif_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"total": 0, "met": 0}
        daily[d]["total"] += r["otif_orders_total"]
        daily[d]["met"] += r["otif_orders_met"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["met"], v["total"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="otif_rate", data_points=points, unit="%")


@router.get("/lead-time-trend")
def lead_time_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = []
        daily[d].append(r["lead_time_days"])
    points = [TimeSeriesPoint(timestamp=d, value=round(sum(v) / len(v), 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="lead_time", data_points=points, unit="days")


@router.get("/sla-trend")
def sla_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"total": 0, "met": 0}
        daily[d]["total"] += r["sla_total_orders"]
        daily[d]["met"] += r["sla_met_orders"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["met"], v["total"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="sla_adherence", data_points=points, unit="%")


@router.get("/response-time-distribution")
def response_time_distribution(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    buckets = {"0-2h": 0, "2-4h": 0, "4-6h": 0, "6-8h": 0, "8-10h": 0, "10h+": 0}
    for r in rows:
        rt = r["response_time_hours"]
        if rt < 2: buckets["0-2h"] += 1
        elif rt < 4: buckets["2-4h"] += 1
        elif rt < 6: buckets["4-6h"] += 1
        elif rt < 8: buckets["6-8h"] += 1
        elif rt < 10: buckets["8-10h"] += 1
        else: buckets["10h+"] += 1
    return [{"bucket": k, "count": v} for k, v in buckets.items()]


@router.get("/lead-time-by-site")
def lead_time_by_site(
    product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(None, product_line, time_range, date_from, date_to)
    site_data = {}
    for r in rows:
        s = r["site"]
        if s not in site_data: site_data[s] = []
        site_data[s].append(r["lead_time_days"])
    return [SiteBreakdown(site=s, value=round(sum(v) / len(v), 2)) for s, v in sorted(site_data.items())]


# ── New chart endpoints ──────────────────────────────────────────

@router.get("/schedule-trend")
def schedule_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"sched": 0, "done": 0}
        daily[d]["sched"] += r["scheduled_batches"]
        daily[d]["done"] += r["completed_scheduled"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["done"], v["sched"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="schedule_adherence", data_points=points, unit="%")


@router.get("/backorder-trend")
def backorder_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"bo": 0, "total": 0}
        daily[d]["bo"] += r["backorders"]
        daily[d]["total"] += r["total_orders"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["bo"], v["total"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="backorder_rate", data_points=points, unit="%")


@router.get("/capacity-trend")
def capacity_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = {"avail": 0, "used": 0}
        daily[d]["avail"] += r["available_capacity"]
        daily[d]["used"] += r["used_capacity"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["used"], v["avail"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="capacity_utilization", data_points=points, unit="%")
