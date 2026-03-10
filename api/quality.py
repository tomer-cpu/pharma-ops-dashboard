from fastapi import APIRouter, Query
from typing import Optional
from ops_dashboard.data.database import query_metrics, query_metrics_previous_period, get_targets
from ops_dashboard.models.schemas import KPIValue, TimeSeriesPoint, TimeSeriesData, SiteBreakdown, CategoryBreakdown

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


def _compute_quality_kpis(rows, prev_rows, targets):
    n = len(rows) or 1
    pn = len(prev_rows) or 1

    # Batch Rejection Rate
    tp = sum(r["batches_produced"] for r in rows) or 1
    tr_ = sum(r["batches_rejected"] for r in rows)
    pp = sum(r["batches_produced"] for r in prev_rows) or 1
    pr = sum(r["batches_rejected"] for r in prev_rows)
    batch_rej = _safe_div(tr_, tp) * 100
    prev_batch_rej = _safe_div(pr, pp) * 100

    # Yield Rate
    tty = sum(r["theoretical_yield"] for r in rows) or 1
    tay = sum(r["actual_yield"] for r in rows)
    pty = sum(r["theoretical_yield"] for r in prev_rows) or 1
    pay = sum(r["actual_yield"] for r in prev_rows)
    yield_r = _safe_div(tay, tty) * 100
    prev_yield = _safe_div(pay, pty) * 100

    # Compliance Score
    ta = sum(r["compliance_audits"] for r in rows) or 1
    tcp = sum(r["compliance_passed"] for r in rows)
    pa = sum(r["compliance_audits"] for r in prev_rows) or 1
    pcp = sum(r["compliance_passed"] for r in prev_rows)
    comp = _safe_div(tcp, ta) * 100
    prev_comp = _safe_div(pcp, pa) * 100

    # Right First Time
    rft = _safe_div(sum(r["rft_batches"] for r in rows), tp) * 100
    prev_rft = _safe_div(sum(r["rft_batches"] for r in prev_rows), pp) * 100

    # Deviation Rate (per 100 batches)
    dev = _safe_div(sum(r["total_deviations"] for r in rows), tp) * 100
    prev_dev = _safe_div(sum(r["total_deviations"] for r in prev_rows), pp) * 100

    # CAPA Closure Time
    capa_n = sum(r["capa_open"] for r in rows) or 1
    capa_days = sum(r["capa_closed_days"] for r in rows)
    capa_t = _safe_div(capa_days, capa_n)
    pcapa_n = sum(r["capa_open"] for r in prev_rows) or 1
    pcapa_d = sum(r["capa_closed_days"] for r in prev_rows)
    prev_capa = _safe_div(pcapa_d, pcapa_n)

    # Investigation Cycle Time
    inv_n = sum(r["investigations"] for r in rows) or 1
    inv_d = sum(r["investigation_days"] for r in rows)
    inv_t = _safe_div(inv_d, inv_n)
    pinv_n = sum(r["investigations"] for r in prev_rows) or 1
    pinv_d = sum(r["investigation_days"] for r in prev_rows)
    prev_inv = _safe_div(pinv_d, pinv_n)

    # Audit Findings Rate (avg per day)
    af = sum(r["audit_findings"] for r in rows) / n
    prev_af = sum(r["audit_findings"] for r in prev_rows) / pn

    # Critical Deviations %
    td = sum(r["total_deviations"] for r in rows) or 1
    cd = sum(r["critical_deviations"] for r in rows)
    crit = _safe_div(cd, td) * 100
    ptd = sum(r["total_deviations"] for r in prev_rows) or 1
    pcd = sum(r["critical_deviations"] for r in prev_rows)
    prev_crit = _safe_div(pcd, ptd) * 100

    return [
        _kpi("batch_rejection_rate", "Batch Rejection Rate", batch_rej, prev_batch_rej, "%", "<=", targets),
        _kpi("yield_rate", "Yield Rate", yield_r, prev_yield, "%", ">=", targets),
        _kpi("compliance_score", "Compliance Score", comp, prev_comp, "%", ">=", targets),
        _kpi("right_first_time", "Right First Time (RFT)", rft, prev_rft, "%", ">=", targets),
        _kpi("deviation_rate", "Deviation Rate", dev, prev_dev, "per 100", "<=", targets),
        _kpi("capa_closure_time", "CAPA Closure Time", capa_t, prev_capa, "days", "<=", targets),
        _kpi("investigation_cycle_time", "Investigation Cycle Time", inv_t, prev_inv, "days", "<=", targets),
        _kpi("audit_findings_rate", "Audit Findings Rate", af, prev_af, "count", "<=", targets),
        _kpi("critical_deviations_pct", "Critical Deviations %", crit, prev_crit, "%", "<=", targets),
    ]


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/kpis")
def quality_kpis(
    site: Optional[str] = Query(None),
    product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    kpis = _compute_quality_kpis(rows, prev_rows, targets)
    return [k for k in kpis if targets.get(k.metric_name, {}).get("enabled", True)]


@router.get("/batch-rejections")
def batch_rejection_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily:
            daily[d] = {"produced": 0, "rejected": 0}
        daily[d]["produced"] += r["batches_produced"]
        daily[d]["rejected"] += r["batches_rejected"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["rejected"], v["produced"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="batch_rejection_rate", data_points=points, unit="%")


@router.get("/yield-by-site")
def yield_by_site(
    product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(None, product_line, time_range, date_from, date_to)
    site_data = {}
    for r in rows:
        s = r["site"]
        if s not in site_data:
            site_data[s] = {"theo": 0, "actual": 0}
        site_data[s]["theo"] += r["theoretical_yield"]
        site_data[s]["actual"] += r["actual_yield"]
    return [SiteBreakdown(site=s, value=round(_safe_div(d["actual"], d["theo"]) * 100, 2)) for s, d in sorted(site_data.items())]


@router.get("/compliance-breakdown")
def compliance_breakdown(
    site: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, None, time_range, date_from, date_to)
    by_product = {}
    for r in rows:
        p = r["product_line"]
        if p not in by_product:
            by_product[p] = {"audits": 0, "passed": 0}
        by_product[p]["audits"] += r["compliance_audits"]
        by_product[p]["passed"] += r["compliance_passed"]
    return [CategoryBreakdown(category=p, value=round(_safe_div(d["passed"], d["audits"]) * 100, 2)) for p, d in sorted(by_product.items())]


@router.get("/deviation-trend")
def deviation_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily:
            daily[d] = {"devs": 0, "produced": 0}
        daily[d]["devs"] += r["total_deviations"]
        daily[d]["produced"] += r["batches_produced"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["devs"], v["produced"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="deviation_rate", data_points=points, unit="per 100")


@router.get("/rft-trend")
def rft_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily:
            daily[d] = {"rft": 0, "produced": 0}
        daily[d]["rft"] += r["rft_batches"]
        daily[d]["produced"] += r["batches_produced"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["rft"], v["produced"]) * 100, 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="right_first_time", data_points=points, unit="%")


@router.get("/capa-trend")
def capa_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily:
            daily[d] = {"open": 0, "days": 0}
        daily[d]["open"] += r["capa_open"]
        daily[d]["days"] += r["capa_closed_days"]
    points = [TimeSeriesPoint(timestamp=d, value=round(_safe_div(v["days"], v["open"]), 1)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="capa_closure_time", data_points=points, unit="days")
