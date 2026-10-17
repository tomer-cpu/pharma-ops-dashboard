"""Column contract for the CSV exports, mirroring the daily_metrics table."""

KEY_FIELDS = ("date", "site", "product_line")

INTEGER_FIELDS = (
    "batches_produced", "batches_rejected", "compliance_audits", "compliance_passed",
    "rft_batches", "total_deviations", "critical_deviations", "capa_open",
    "investigations", "audit_findings",
    "supply_units", "demand_units", "otif_orders_total", "otif_orders_met",
    "sla_total_orders", "sla_met_orders",
    "scheduled_batches", "completed_scheduled", "production_output_units",
    "backorders", "total_orders", "forecast_demand", "actual_demand",
    "waste_units", "total_produced_units", "rework_units",
)

REAL_FIELDS = (
    "theoretical_yield", "actual_yield", "capa_closed_days", "investigation_days",
    "lead_time_days", "response_time_hours", "order_cycle_days",
    "available_capacity", "used_capacity",
    "cogs_amount", "revenue_amount", "inventory_value", "carrying_cost_rate",
    "cost_per_batch_amount", "copq_amount", "scrap_cost_amount",
    "planned_cost", "actual_cost",
    "oee_score", "downtime_hours", "available_hours", "changeover_hours",
    "line_output", "line_capacity",
    "supplier_risk", "stockout_risk_score", "batch_failure_prob", "service_risk",
)

NUMERIC_FIELDS = INTEGER_FIELDS + REAL_FIELDS
ALL_FIELDS = KEY_FIELDS + NUMERIC_FIELDS

# (part, whole): part may never exceed whole
PART_OF_WHOLE = (
    ("batches_rejected", "batches_produced"),
    ("rft_batches", "batches_produced"),
    ("compliance_passed", "compliance_audits"),
    ("critical_deviations", "total_deviations"),
    ("otif_orders_met", "otif_orders_total"),
    ("sla_met_orders", "sla_total_orders"),
    ("completed_scheduled", "scheduled_batches"),
    ("backorders", "total_orders"),
    ("downtime_hours", "available_hours"),
    ("waste_units", "total_produced_units"),
)

# Fields expressed as a 0-100 score/percentage
PERCENT_FIELDS = (
    "oee_score", "supplier_risk", "stockout_risk_score",
    "batch_failure_prob", "service_risk",
)
