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


def _compute_risk_kpis(rows, prev_rows, targets):
    n = len(rows) or 1
    pn = len(prev_rows) or 1

    # Supplier Risk Score (avg)
    sr = sum(r["supplier_risk"] for r in rows) / n
    prev_sr = sum(r["supplier_risk"] for r in prev_rows) / pn if prev_rows else sr

    # Stockout Risk (avg)
    so = sum(r["stockout_risk_score"] for r in rows) / n
    prev_so = sum(r["stockout_risk_score"] for r in prev_rows) / pn if prev_rows else so

    # Batch Failure Prediction (avg)
    bf = sum(r["batch_failure_prob"] for r in rows) / n
    prev_bf = sum(r["batch_failure_prob"] for r in prev_rows) / pn if prev_rows else bf

    # Service Risk Index (avg)
    sri = sum(r["service_risk"] for r in rows) / n
    prev_sri = sum(r["service_risk"] for r in prev_rows) / pn if prev_rows else sri

    return [
        _kpi("supplier_risk_score", "Supplier Risk Score", sr, prev_sr, "score", "<=", targets),
        _kpi("stockout_risk", "Stockout Risk", so, prev_so, "%", "<=", targets),
        _kpi("batch_failure_prediction", "Batch Failure Prediction", bf, prev_bf, "%", "<=", targets),
        _kpi("service_risk_index", "Service Risk Index", sri, prev_sri, "score", "<=", targets),
    ]


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/kpis")
def risk_kpis(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    kpis = _compute_risk_kpis(rows, prev_rows, targets)
    return [k for k in kpis if targets.get(k.metric_name, {}).get("enabled", True)]


@router.get("/supplier-trend")
def supplier_trend(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    daily = {}
    for r in rows:
        d = r["date"]
        if d not in daily: daily[d] = []
        daily[d].append(r["supplier_risk"])
    points = [TimeSeriesPoint(timestamp=d, value=round(sum(v) / len(v), 2)) for d, v in sorted(daily.items())]
    return TimeSeriesData(metric_name="supplier_risk_score", data_points=points, unit="score")


@router.get("/risk-heatmap")
def risk_heatmap(
    product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    """All 4 risk scores averaged by site — suitable for a grouped bar or heatmap."""
    rows = query_metrics(None, product_line, time_range, date_from, date_to)
    site_data = {}
    for r in rows:
        s = r["site"]
        if s not in site_data:
            site_data[s] = {"sr": [], "so": [], "bf": [], "sri": []}
        site_data[s]["sr"].append(r["supplier_risk"])
        site_data[s]["so"].append(r["stockout_risk_score"])
        site_data[s]["bf"].append(r["batch_failure_prob"])
        site_data[s]["sri"].append(r["service_risk"])

    result = []
    for s in sorted(site_data):
        d = site_data[s]
        result.append({
            "site": s,
            "supplier_risk": round(sum(d["sr"]) / len(d["sr"]), 2),
            "stockout_risk": round(sum(d["so"]) / len(d["so"]), 2),
            "batch_failure": round(sum(d["bf"]) / len(d["bf"]), 2),
            "service_risk": round(sum(d["sri"]) / len(d["sri"]), 2),
        })
    return result
