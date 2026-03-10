from fastapi import APIRouter, Query
from typing import Optional
from ops_dashboard.data.database import query_metrics, query_metrics_previous_period, get_targets, METRIC_DISPLAY_NAMES, METRIC_CATEGORIES
from ops_dashboard.api.quality import _compute_quality_kpis
from ops_dashboard.api.service import _compute_service_kpis
from ops_dashboard.api.cost import _compute_cost_kpis
from ops_dashboard.api.efficiency import _compute_efficiency_kpis
from ops_dashboard.api.risk import _compute_risk_kpis
from ops_dashboard.models.schemas import Alert, MetricScore

router = APIRouter()


def _safe_div(a, b, default=0):
    return a / b if b else default


def _normalize_score(value, target, direction):
    """Normalize a metric value to 0-100 score based on target."""
    if direction == ">=":
        if value >= target:
            return min(100, 50 + (value - target) / max(target, 1) * 50)
        else:
            return max(0, (value / max(target, 1)) * 50)
    else:  # "<="
        if value <= target:
            return min(100, 50 + (target - value) / max(target, 1) * 50)
        else:
            return max(0, (1 - (value - target) / max(target, 1)) * 50)


def _compute_raw_metrics(rows):
    """Compute all 35 raw metric values from rows."""
    if not rows:
        return {}
    n = len(rows)
    tp = sum(r["batches_produced"] for r in rows) or 1
    tr = sum(r["batches_rejected"] for r in rows)
    tty = sum(r["theoretical_yield"] for r in rows) or 1
    tay = sum(r["actual_yield"] for r in rows)
    ta = sum(r["compliance_audits"] for r in rows) or 1
    tcp = sum(r["compliance_passed"] for r in rows)
    td = sum(r["total_deviations"] for r in rows)
    cd = sum(r["critical_deviations"] for r in rows)
    capa_n = sum(r["capa_open"] for r in rows) or 1
    capa_d = sum(r["capa_closed_days"] for r in rows)
    inv_n = sum(r["investigations"] for r in rows) or 1
    inv_d = sum(r["investigation_days"] for r in rows)

    ts = sum(r["supply_units"] for r in rows)
    tdem = sum(r["demand_units"] for r in rows) or 1
    tot_t = sum(r["otif_orders_total"] for r in rows) or 1
    tot_m = sum(r["otif_orders_met"] for r in rows)
    tst = sum(r["sla_total_orders"] for r in rows) or 1
    tsm = sum(r["sla_met_orders"] for r in rows)
    tsb = sum(r["scheduled_batches"] for r in rows) or 1
    tcs = sum(r["completed_scheduled"] for r in rows)
    tbo = sum(r["backorders"] for r in rows)
    tto = sum(r["total_orders"] for r in rows) or 1
    tfd = sum(r["forecast_demand"] for r in rows) or 1
    tad = sum(r["actual_demand"] for r in rows) or 1
    tac_cap = sum(r["available_capacity"] for r in rows) or 1
    tuc = sum(r["used_capacity"] for r in rows)

    tw = sum(r["waste_units"] for r in rows)
    tpu = sum(r["total_produced_units"] for r in rows) or 1
    trw = sum(r["rework_units"] for r in rows)
    tpc = sum(r["planned_cost"] for r in rows) or 1
    tact = sum(r["actual_cost"] for r in rows)

    tah = sum(r["available_hours"] for r in rows) or 1
    tdh = sum(r["downtime_hours"] for r in rows)
    tlo = sum(r["line_output"] for r in rows)
    tlc = sum(r["line_capacity"] for r in rows) or 1

    return {
        # Quality (9)
        "batch_rejection_rate": round(_safe_div(tr, tp) * 100, 2),
        "yield_rate": round(_safe_div(tay, tty) * 100, 2),
        "compliance_score": round(_safe_div(tcp, ta) * 100, 2),
        "right_first_time": round(_safe_div(sum(r["rft_batches"] for r in rows), tp) * 100, 2),
        "deviation_rate": round(_safe_div(td, tp) * 100, 2),
        "capa_closure_time": round(_safe_div(capa_d, capa_n), 2),
        "investigation_cycle_time": round(_safe_div(inv_d, inv_n), 2),
        "audit_findings_rate": round(sum(r["audit_findings"] for r in rows) / n, 2),
        "critical_deviations_pct": round(_safe_div(cd, td or 1) * 100, 2),
        # Service (11)
        "supply_vs_demand": round(_safe_div(ts, tdem) * 100, 2),
        "otif_rate": round(_safe_div(tot_m, tot_t) * 100, 2),
        "lead_time": round(sum(r["lead_time_days"] for r in rows) / n, 2),
        "sla_adherence": round(_safe_div(tsm, tst) * 100, 2),
        "response_time": round(sum(r["response_time_hours"] for r in rows) / n, 2),
        "schedule_adherence": round(_safe_div(tcs, tsb) * 100, 2),
        "production_throughput": round(sum(r["production_output_units"] for r in rows) / n, 2),
        "backorder_rate": round(_safe_div(tbo, tto) * 100, 2),
        "order_cycle_time": round(sum(r["order_cycle_days"] for r in rows) / n, 2),
        "forecast_accuracy": round((1 - abs(tfd - tad) / tad) * 100, 2),
        "capacity_utilization": round(_safe_div(tuc, tac_cap) * 100, 2),
        # Cost (7)
        "waste_percentage": round(_safe_div(tw, tpu) * 100, 2),
        "cost_per_batch": round(sum(r["cost_per_batch_amount"] for r in rows) / n, 2),
        "copq": round(sum(r["copq_amount"] for r in rows) / n, 2),
        "scrap_cost": round(sum(r["scrap_cost_amount"] for r in rows) / n, 2),
        "rework_rate": round(_safe_div(trw, tpu) * 100, 2),
        "inventory_carrying_cost": round(sum(r["inventory_value"] * r["carrying_cost_rate"] / 365 for r in rows) / n, 2),
        "production_cost_variance": round(abs(tact - tpc) / tpc * 100, 2),
        # Efficiency (4)
        "oee": round(sum(r["oee_score"] for r in rows) / n * 100, 2),
        "downtime_rate": round(_safe_div(tdh, tah) * 100, 2),
        "changeover_time": round(sum(r["changeover_hours"] for r in rows) / n, 2),
        "line_efficiency": round(_safe_div(tlo, tlc) * 100, 2),
        # Risk (4)
        "supplier_risk_score": round(sum(r["supplier_risk"] for r in rows) / n, 2),
        "stockout_risk": round(sum(r["stockout_risk_score"] for r in rows) / n, 2),
        "batch_failure_prediction": round(sum(r["batch_failure_prob"] for r in rows) / n, 2),
        "service_risk_index": round(sum(r["service_risk"] for r in rows) / n, 2),
    }


@router.get("/dashboard")
def dashboard_summary(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    prev_rows = query_metrics_previous_period(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    return {
        "quality": [k.model_dump() for k in _compute_quality_kpis(rows, prev_rows, targets)],
        "service": [k.model_dump() for k in _compute_service_kpis(rows, prev_rows, targets)],
        "cost": [k.model_dump() for k in _compute_cost_kpis(rows, prev_rows, targets)],
        "efficiency": [k.model_dump() for k in _compute_efficiency_kpis(rows, prev_rows, targets)],
        "risk": [k.model_dump() for k in _compute_risk_kpis(rows, prev_rows, targets)],
    }


@router.get("/health-score")
def health_score(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    targets = get_targets()

    if not rows:
        return {"score": 0, "label": "No Data", "breakdown": []}

    metrics = _compute_raw_metrics(rows)

    # Only score enabled metrics
    enabled_targets = {k: v for k, v in targets.items() if v.get("enabled", True)}
    total_weight = sum(t.get("weight", 3) for t in enabled_targets.values() if t.get("weight", 3) > 0)
    if total_weight == 0:
        total_weight = 1

    breakdown = []
    score = 0
    for metric_name, current_val in metrics.items():
        t = targets.get(metric_name, {})
        if not t:
            continue
        enabled = t.get("enabled", True)
        if not enabled:
            continue  # Skip disabled metrics entirely
        t_val = t.get("value", 50)
        t_dir = t.get("direction", ">=")
        t_weight = t.get("weight", 3)
        t_unit = t.get("unit", "%")

        raw_score = _normalize_score(current_val, t_val, t_dir)
        weighted_contrib = (t_weight / total_weight) * raw_score

        breached = False
        if t_dir == ">=" and current_val < t_val:
            breached = True
        elif t_dir == "<=" and current_val > t_val:
            breached = True

        if not breached:
            status = "on_target"
        else:
            gap = abs(current_val - t_val)
            status = "critical" if gap > t_val * 0.1 else "warning"

        breakdown.append(MetricScore(
            metric_name=metric_name,
            display_name=METRIC_DISPLAY_NAMES.get(metric_name, metric_name),
            category=METRIC_CATEGORIES.get(metric_name, ""),
            current_value=current_val,
            target_value=t_val,
            target_direction=t_dir,
            unit=t_unit,
            score=round(raw_score, 1),
            weight=t_weight,
            weighted_contribution=round(weighted_contrib, 2),
            status=status,
        ))

        score += weighted_contrib

    score = round(min(100, max(0, score)), 1)
    label = "Excellent" if score >= 80 else "Good" if score >= 60 else "Fair" if score >= 40 else "Needs Attention"

    cat_order = {"quality": 0, "service": 1, "cost": 2, "efficiency": 3, "risk": 4}
    breakdown.sort(key=lambda m: (cat_order.get(m.category, 9), m.metric_name))

    return {
        "score": score,
        "label": label,
        "total_weight": total_weight,
        "breakdown": [b.model_dump() for b in breakdown],
    }


@router.get("/alerts")
def get_alerts(
    site: Optional[str] = Query(None), product_line: Optional[str] = Query(None),
    time_range: Optional[str] = Query("30d"), date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
):
    rows = query_metrics(site, product_line, time_range, date_from, date_to)
    targets = get_targets()
    if not rows:
        return []

    computed = _compute_raw_metrics(rows)
    alerts = []
    for metric_name, current_val in computed.items():
        t = targets.get(metric_name)
        if not t or not t.get("enabled", True):
            continue
        target_val = t["value"]
        direction = t["direction"]

        breached = (direction == ">=" and current_val < target_val) or (direction == "<=" and current_val > target_val)
        if breached:
            gap = abs(current_val - target_val)
            severity = "critical" if gap > target_val * 0.1 else "warning"
            unit = t["unit"]
            alerts.append(Alert(
                metric_name=metric_name,
                display_name=METRIC_DISPLAY_NAMES.get(metric_name, metric_name),
                category=METRIC_CATEGORIES.get(metric_name, ""),
                current_value=current_val, target_value=target_val, target_direction=direction,
                severity=severity,
                message=f"{METRIC_DISPLAY_NAMES.get(metric_name, metric_name)} is {current_val}{unit} (target: {direction} {target_val}{unit})",
            ))

    return sorted(alerts, key=lambda a: 0 if a.severity == "critical" else 1)
