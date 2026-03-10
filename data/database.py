import sqlite3
import os
from datetime import datetime, timedelta
from ops_dashboard.config import OPS_DB_PATH, DEFAULT_TARGETS, SITES, PRODUCT_LINES, SITE_PROFILES


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    site TEXT NOT NULL,
    product_line TEXT NOT NULL,

    -- Quality metrics (original)
    batches_produced INTEGER DEFAULT 0,
    batches_rejected INTEGER DEFAULT 0,
    theoretical_yield REAL DEFAULT 0,
    actual_yield REAL DEFAULT 0,
    compliance_audits INTEGER DEFAULT 0,
    compliance_passed INTEGER DEFAULT 0,

    -- Quality metrics (new)
    rft_batches INTEGER DEFAULT 0,
    total_deviations INTEGER DEFAULT 0,
    critical_deviations INTEGER DEFAULT 0,
    capa_open INTEGER DEFAULT 0,
    capa_closed_days REAL DEFAULT 0,
    investigations INTEGER DEFAULT 0,
    investigation_days REAL DEFAULT 0,
    audit_findings INTEGER DEFAULT 0,

    -- Service metrics (original)
    supply_units INTEGER DEFAULT 0,
    demand_units INTEGER DEFAULT 0,
    otif_orders_total INTEGER DEFAULT 0,
    otif_orders_met INTEGER DEFAULT 0,
    lead_time_days REAL DEFAULT 0,
    sla_total_orders INTEGER DEFAULT 0,
    sla_met_orders INTEGER DEFAULT 0,
    response_time_hours REAL DEFAULT 0,

    -- Service metrics (new)
    scheduled_batches INTEGER DEFAULT 0,
    completed_scheduled INTEGER DEFAULT 0,
    production_output_units INTEGER DEFAULT 0,
    backorders INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    order_cycle_days REAL DEFAULT 0,
    forecast_demand INTEGER DEFAULT 0,
    actual_demand INTEGER DEFAULT 0,
    available_capacity REAL DEFAULT 0,
    used_capacity REAL DEFAULT 0,

    -- Cost metrics (original)
    cogs_amount REAL DEFAULT 0,
    revenue_amount REAL DEFAULT 0,
    waste_units INTEGER DEFAULT 0,
    total_produced_units INTEGER DEFAULT 0,
    inventory_value REAL DEFAULT 0,
    carrying_cost_rate REAL DEFAULT 0.18,

    -- Cost metrics (new)
    cost_per_batch_amount REAL DEFAULT 0,
    copq_amount REAL DEFAULT 0,
    scrap_cost_amount REAL DEFAULT 0,
    rework_units INTEGER DEFAULT 0,
    planned_cost REAL DEFAULT 0,
    actual_cost REAL DEFAULT 0,

    -- Efficiency metrics (new)
    oee_score REAL DEFAULT 0,
    downtime_hours REAL DEFAULT 0,
    available_hours REAL DEFAULT 0,
    changeover_hours REAL DEFAULT 0,
    line_output REAL DEFAULT 0,
    line_capacity REAL DEFAULT 0,

    -- Risk metrics (new)
    supplier_risk REAL DEFAULT 0,
    stockout_risk_score REAL DEFAULT 0,
    batch_failure_prob REAL DEFAULT 0,
    service_risk REAL DEFAULT 0,

    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(date, site, product_line)
);

CREATE INDEX IF NOT EXISTS idx_metrics_date ON daily_metrics(date);
CREATE INDEX IF NOT EXISTS idx_metrics_site ON daily_metrics(site);
CREATE INDEX IF NOT EXISTS idx_metrics_product ON daily_metrics(product_line);

CREATE TABLE IF NOT EXISTS metric_targets (
    metric_name TEXT PRIMARY KEY,
    target_value REAL NOT NULL,
    direction TEXT NOT NULL,
    unit TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 10,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sites (
    name TEXT PRIMARY KEY,
    volume_mult REAL NOT NULL DEFAULT 1.0,
    cost_mult REAL NOT NULL DEFAULT 1.0,
    quality_offset REAL NOT NULL DEFAULT 0.0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_lines (
    name TEXT PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

METRIC_DISPLAY_NAMES = {
    # Quality
    "batch_rejection_rate":     "Batch Rejection Rate",
    "yield_rate":               "Yield Rate",
    "compliance_score":         "Compliance Score",
    "right_first_time":         "Right First Time (RFT)",
    "deviation_rate":           "Deviation Rate",
    "capa_closure_time":        "CAPA Closure Time",
    "investigation_cycle_time": "Investigation Cycle Time",
    "audit_findings_rate":      "Audit Findings Rate",
    "critical_deviations_pct":  "Critical Deviations %",
    # Service
    "supply_vs_demand":         "Supply vs Demand",
    "otif_rate":                "OTIF Rate",
    "lead_time":                "Lead Time",
    "sla_adherence":            "SLA Adherence",
    "response_time":            "Response Time",
    "schedule_adherence":       "Schedule Adherence",
    "production_throughput":    "Production Throughput",
    "backorder_rate":           "Backorder Rate",
    "order_cycle_time":         "Order Cycle Time",
    "forecast_accuracy":        "Forecast Accuracy",
    "capacity_utilization":     "Capacity Utilization",
    # Cost
    "waste_percentage":         "Waste %",
    "cost_per_batch":           "Cost per Batch",
    "copq":                     "Cost of Poor Quality",
    "scrap_cost":               "Scrap Cost",
    "rework_rate":              "Rework Rate",
    "inventory_carrying_cost":  "Inventory Carrying Cost",
    "production_cost_variance": "Production Cost Variance",
    # Efficiency
    "oee":                      "OEE",
    "downtime_rate":            "Downtime Rate",
    "changeover_time":          "Changeover Time",
    "line_efficiency":          "Line Efficiency",
    # Risk
    "supplier_risk_score":      "Supplier Risk Score",
    "stockout_risk":            "Stockout Risk",
    "batch_failure_prediction": "Batch Failure Prediction",
    "service_risk_index":       "Service Risk Index",
}

METRIC_CATEGORIES = {
    # Quality
    "batch_rejection_rate":     "quality",
    "yield_rate":               "quality",
    "compliance_score":         "quality",
    "right_first_time":         "quality",
    "deviation_rate":           "quality",
    "capa_closure_time":        "quality",
    "investigation_cycle_time": "quality",
    "audit_findings_rate":      "quality",
    "critical_deviations_pct":  "quality",
    # Service
    "supply_vs_demand":         "service",
    "otif_rate":                "service",
    "lead_time":                "service",
    "sla_adherence":            "service",
    "response_time":            "service",
    "schedule_adherence":       "service",
    "production_throughput":    "service",
    "backorder_rate":           "service",
    "order_cycle_time":         "service",
    "forecast_accuracy":        "service",
    "capacity_utilization":     "service",
    # Cost
    "waste_percentage":         "cost",
    "cost_per_batch":           "cost",
    "copq":                     "cost",
    "scrap_cost":               "cost",
    "rework_rate":              "cost",
    "inventory_carrying_cost":  "cost",
    "production_cost_variance": "cost",
    # Efficiency
    "oee":                      "efficiency",
    "downtime_rate":            "efficiency",
    "changeover_time":          "efficiency",
    "line_efficiency":          "efficiency",
    # Risk
    "supplier_risk_score":      "risk",
    "stockout_risk":            "risk",
    "batch_failure_prediction": "risk",
    "service_risk_index":       "risk",
}


def get_connection():
    os.makedirs(os.path.dirname(OPS_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(OPS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)

    # Migration: add weight column if missing (legacy DBs)
    for col, sql in [
        ("weight",  "ALTER TABLE metric_targets ADD COLUMN weight REAL NOT NULL DEFAULT 10"),
        ("enabled", "ALTER TABLE metric_targets ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"),
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Seed default targets if empty
    cursor = conn.execute("SELECT COUNT(*) FROM metric_targets")
    if cursor.fetchone()[0] == 0:
        for name, cfg in DEFAULT_TARGETS.items():
            conn.execute(
                "INSERT OR IGNORE INTO metric_targets (metric_name, target_value, direction, unit, weight, enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (name, cfg["value"], cfg["direction"], cfg["unit"], cfg.get("weight", 3), 1 if cfg.get("enabled", True) else 0),
            )

    # Seed sites if empty
    cursor = conn.execute("SELECT COUNT(*) FROM sites")
    if cursor.fetchone()[0] == 0:
        for site_name in SITES:
            profile = SITE_PROFILES.get(site_name, {})
            conn.execute(
                "INSERT OR IGNORE INTO sites (name, volume_mult, cost_mult, quality_offset) VALUES (?, ?, ?, ?)",
                (site_name, profile.get("volume_mult", 1.0), profile.get("cost_mult", 1.0), profile.get("quality_offset", 0.0)),
            )

    # Seed product lines if empty
    cursor = conn.execute("SELECT COUNT(*) FROM product_lines")
    if cursor.fetchone()[0] == 0:
        for pl_name in PRODUCT_LINES:
            conn.execute("INSERT OR IGNORE INTO product_lines (name) VALUES (?)", (pl_name,))

    conn.commit()
    conn.close()


def get_targets():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM metric_targets").fetchall()
    conn.close()
    result = {}
    for row in rows:
        keys = row.keys()
        result[row["metric_name"]] = {
            "value": row["target_value"],
            "direction": row["direction"],
            "unit": row["unit"],
            "weight": row["weight"] if "weight" in keys else 10,
            "enabled": bool(row["enabled"]) if "enabled" in keys else True,
        }
    return result


def update_target(metric_name, value, weight=None, enabled=None):
    conn = get_connection()
    parts = ["target_value = ?", "updated_at = datetime('now')"]
    params = [value]
    if weight is not None:
        parts.append("weight = ?")
        params.append(weight)
    if enabled is not None:
        parts.append("enabled = ?")
        params.append(1 if enabled else 0)
    params.append(metric_name)
    conn.execute(f"UPDATE metric_targets SET {', '.join(parts)} WHERE metric_name = ?", params)
    conn.commit()
    conn.close()


def _build_date_filter(time_range=None, date_from=None, date_to=None):
    today = datetime.now().date()
    if date_from and date_to:
        return date_from, date_to
    days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
    days = days_map.get(time_range, 30)
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def query_metrics(site=None, product_line=None, time_range="30d", date_from=None, date_to=None):
    d_from, d_to = _build_date_filter(time_range, date_from, date_to)
    conn = get_connection()
    sql = "SELECT * FROM daily_metrics WHERE date >= ? AND date <= ?"
    params = [d_from, d_to]
    if site:
        sql += " AND site = ?"
        params.append(site)
    if product_line:
        sql += " AND product_line = ?"
        params.append(product_line)
    sql += " ORDER BY date ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_metrics_previous_period(site=None, product_line=None, time_range="30d", date_from=None, date_to=None):
    """Query the same duration but for the previous period (for trend comparison)."""
    d_from, d_to = _build_date_filter(time_range, date_from, date_to)
    from datetime import date as dt_date
    start = dt_date.fromisoformat(d_from)
    end = dt_date.fromisoformat(d_to)
    duration = (end - start).days
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=duration)
    return query_metrics(site, product_line, date_from=prev_start.isoformat(), date_to=prev_end.isoformat())


def get_available_filters():
    conn = get_connection()
    sites = [r[0] for r in conn.execute("SELECT name FROM sites WHERE active = 1 ORDER BY name").fetchall()]
    products = [r[0] for r in conn.execute("SELECT name FROM product_lines WHERE active = 1 ORDER BY name").fetchall()]
    dates = conn.execute("SELECT MIN(date), MAX(date) FROM daily_metrics").fetchone()
    conn.close()
    return {
        "sites": sites,
        "product_lines": products,
        "date_range": {"min": dates[0], "max": dates[1]} if dates[0] else {},
    }


# Column list for insert (must match generate_mock_data tuple order)
_INSERT_COLUMNS = """date, site, product_line,
    batches_produced, batches_rejected, theoretical_yield, actual_yield,
    compliance_audits, compliance_passed,
    rft_batches, total_deviations, critical_deviations,
    capa_open, capa_closed_days, investigations, investigation_days, audit_findings,
    supply_units, demand_units, otif_orders_total, otif_orders_met,
    lead_time_days, sla_total_orders, sla_met_orders, response_time_hours,
    scheduled_batches, completed_scheduled, production_output_units,
    backorders, total_orders, order_cycle_days,
    forecast_demand, actual_demand, available_capacity, used_capacity,
    cogs_amount, revenue_amount, waste_units, total_produced_units,
    inventory_value, carrying_cost_rate,
    cost_per_batch_amount, copq_amount, scrap_cost_amount,
    rework_units, planned_cost, actual_cost,
    oee_score, downtime_hours, available_hours,
    changeover_hours, line_output, line_capacity,
    supplier_risk, stockout_risk_score, batch_failure_prob, service_risk"""

_INSERT_PLACEHOLDERS = ",".join(["?"] * 57)  # 57 columns


def insert_metrics_batch(records):
    conn = get_connection()
    conn.executemany(
        f"INSERT OR REPLACE INTO daily_metrics ({_INSERT_COLUMNS}) VALUES ({_INSERT_PLACEHOLDERS})",
        records,
    )
    conn.commit()
    conn.close()


def has_data():
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0]
    conn.close()
    return count > 0


# ── Sites CRUD ──────────────────────────────────────────────────

def get_sites(include_inactive=False):
    conn = get_connection()
    sql = "SELECT * FROM sites ORDER BY name"
    if not include_inactive:
        sql = "SELECT * FROM sites WHERE active = 1 ORDER BY name"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_site(name, volume_mult=1.0, cost_mult=1.0, quality_offset=0.0):
    conn = get_connection()
    existing = conn.execute("SELECT active FROM sites WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE sites SET volume_mult = ?, cost_mult = ?, quality_offset = ?, active = 1 WHERE name = ?",
            (volume_mult, cost_mult, quality_offset, name),
        )
    else:
        conn.execute(
            "INSERT INTO sites (name, volume_mult, cost_mult, quality_offset) VALUES (?, ?, ?, ?)",
            (name, volume_mult, cost_mult, quality_offset),
        )
    conn.commit()
    conn.close()


def update_site(name, volume_mult=None, cost_mult=None, quality_offset=None):
    conn = get_connection()
    updates = []
    params = []
    if volume_mult is not None:
        updates.append("volume_mult = ?")
        params.append(volume_mult)
    if cost_mult is not None:
        updates.append("cost_mult = ?")
        params.append(cost_mult)
    if quality_offset is not None:
        updates.append("quality_offset = ?")
        params.append(quality_offset)
    if updates:
        params.append(name)
        conn.execute(f"UPDATE sites SET {', '.join(updates)} WHERE name = ?", params)
        conn.commit()
    conn.close()


def delete_site(name):
    """Soft delete — set active=0."""
    conn = get_connection()
    conn.execute("UPDATE sites SET active = 0 WHERE name = ?", (name,))
    conn.commit()
    conn.close()


# ── Product Lines CRUD ──────────────────────────────────────────

def get_product_lines(include_inactive=False):
    conn = get_connection()
    sql = "SELECT * FROM product_lines ORDER BY name"
    if not include_inactive:
        sql = "SELECT * FROM product_lines WHERE active = 1 ORDER BY name"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_product_line(name):
    conn = get_connection()
    existing = conn.execute("SELECT active FROM product_lines WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.execute("UPDATE product_lines SET active = 1 WHERE name = ?", (name,))
    else:
        conn.execute("INSERT INTO product_lines (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def delete_product_line(name):
    """Soft delete — set active=0."""
    conn = get_connection()
    conn.execute("UPDATE product_lines SET active = 0 WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def get_existing_combos():
    """Return set of (site, product_line) combos that already have data."""
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT site, product_line FROM daily_metrics").fetchall()
    conn.close()
    return {(r[0], r[1]) for r in rows}
