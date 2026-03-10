import os

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OPS_DB_PATH = os.path.join(BASE_DIR, "data", "ops_metrics.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Server
HOST = "0.0.0.0"
PORT = 8085

# Mock data parameters
SITES = ["New Jersey", "Basel", "Dublin", "Singapore", "Hyderabad"]
PRODUCT_LINES = ["Oncology", "Cardiovascular", "Immunology", "CNS", "Respiratory"]
DATE_RANGE_DAYS = 365

# Default metric targets  (35 metrics across 5 categories, weights sum ≈ 100)
DEFAULT_TARGETS = {
    # ── Quality (9 metrics, ~25 weight) ─────────────────────────
    "batch_rejection_rate":       {"value": 2.0,   "direction": "<=", "unit": "%",       "weight": 3, "enabled": True},
    "yield_rate":                 {"value": 95.0,  "direction": ">=", "unit": "%",       "weight": 3, "enabled": True},
    "compliance_score":           {"value": 98.0,  "direction": ">=", "unit": "%",       "weight": 3, "enabled": True},
    "right_first_time":           {"value": 92.0,  "direction": ">=", "unit": "%",       "weight": 3, "enabled": True},
    "deviation_rate":             {"value": 2.0,   "direction": "<=", "unit": "per 100", "weight": 3, "enabled": True},
    "capa_closure_time":          {"value": 30.0,  "direction": "<=", "unit": "days",    "weight": 3, "enabled": True},
    "investigation_cycle_time":   {"value": 20.0,  "direction": "<=", "unit": "days",    "weight": 2, "enabled": True},
    "audit_findings_rate":        {"value": 3.0,   "direction": "<=", "unit": "count",   "weight": 2, "enabled": True},
    "critical_deviations_pct":    {"value": 5.0,   "direction": "<=", "unit": "%",       "weight": 3, "enabled": True},

    # ── Service (11 metrics, ~25 weight) ────────────────────────
    "lead_time":                  {"value": 10.0,  "direction": "<=", "unit": "days",    "weight": 3, "enabled": True},
    "otif_rate":                  {"value": 95.0,  "direction": ">=", "unit": "%",       "weight": 3, "enabled": True},
    "response_time":              {"value": 4.0,   "direction": "<=", "unit": "hours",   "weight": 2, "enabled": True},
    "sla_adherence":              {"value": 95.0,  "direction": ">=", "unit": "%",       "weight": 2, "enabled": True},
    "supply_vs_demand":           {"value": 100.0, "direction": ">=", "unit": "%",       "weight": 3, "enabled": True},
    "schedule_adherence":         {"value": 90.0,  "direction": ">=", "unit": "%",       "weight": 2, "enabled": True},
    "production_throughput":      {"value": 500.0, "direction": ">=", "unit": "units",   "weight": 2, "enabled": True},
    "backorder_rate":             {"value": 5.0,   "direction": "<=", "unit": "%",       "weight": 2, "enabled": True},
    "order_cycle_time":           {"value": 7.0,   "direction": "<=", "unit": "days",    "weight": 2, "enabled": True},
    "forecast_accuracy":          {"value": 85.0,  "direction": ">=", "unit": "%",       "weight": 2, "enabled": True},
    "capacity_utilization":       {"value": 80.0,  "direction": ">=", "unit": "%",       "weight": 2, "enabled": True},

    # ── Cost (7 metrics, ~18 weight) ────────────────────────────
    "waste_percentage":           {"value": 3.0,      "direction": "<=", "unit": "%",    "weight": 3, "enabled": True},
    "cost_per_batch":             {"value": 50000.0,  "direction": "<=", "unit": "$",    "weight": 3, "enabled": True},
    "copq":                       {"value": 100000.0, "direction": "<=", "unit": "$",    "weight": 3, "enabled": True},
    "scrap_cost":                 {"value": 25000.0,  "direction": "<=", "unit": "$",    "weight": 2, "enabled": True},
    "rework_rate":                {"value": 3.0,      "direction": "<=", "unit": "%",    "weight": 3, "enabled": True},
    "inventory_carrying_cost":    {"value": 200000.0, "direction": "<=", "unit": "$",    "weight": 2, "enabled": True},
    "production_cost_variance":   {"value": 5.0,      "direction": "<=", "unit": "%",    "weight": 2, "enabled": True},

    # ── Efficiency (4 metrics, ~16 weight) ──────────────────────
    "oee":                        {"value": 85.0,  "direction": ">=", "unit": "%",       "weight": 4, "enabled": True},
    "downtime_rate":              {"value": 5.0,   "direction": "<=", "unit": "%",       "weight": 4, "enabled": True},
    "changeover_time":            {"value": 4.0,   "direction": "<=", "unit": "hours",   "weight": 4, "enabled": True},
    "line_efficiency":            {"value": 90.0,  "direction": ">=", "unit": "%",       "weight": 4, "enabled": True},

    # ── Risk (4 metrics, ~16 weight) ────────────────────────────
    "supplier_risk_score":        {"value": 30.0,  "direction": "<=", "unit": "score",   "weight": 4, "enabled": True},
    "stockout_risk":              {"value": 10.0,  "direction": "<=", "unit": "%",       "weight": 4, "enabled": True},
    "batch_failure_prediction":   {"value": 5.0,   "direction": "<=", "unit": "%",       "weight": 4, "enabled": True},
    "service_risk_index":         {"value": 25.0,  "direction": "<=", "unit": "score",   "weight": 4, "enabled": True},
}

# Site-specific profiles for mock data generation
SITE_PROFILES = {
    "New Jersey": {"volume_mult": 1.2, "cost_mult": 1.3, "quality_offset": -0.5},
    "Basel": {"volume_mult": 1.0, "cost_mult": 1.4, "quality_offset": 1.0},
    "Dublin": {"volume_mult": 0.9, "cost_mult": 1.1, "quality_offset": 0.5},
    "Singapore": {"volume_mult": 1.1, "cost_mult": 0.8, "quality_offset": 1.5},
    "Hyderabad": {"volume_mult": 1.3, "cost_mult": 0.6, "quality_offset": 0.0},
}
