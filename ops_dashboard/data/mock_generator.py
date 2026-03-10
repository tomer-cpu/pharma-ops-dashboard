import math
import random
from datetime import datetime, timedelta
from ops_dashboard.config import SITES, PRODUCT_LINES, DATE_RANGE_DAYS, SITE_PROFILES
from ops_dashboard.data.database import insert_metrics_batch, has_data, get_sites, get_product_lines, get_existing_combos


def _noise(std=1.0):
    return random.gauss(0, std)


def _seasonal(day_index, amplitude=1.0, period=90):
    return amplitude * math.sin(2 * math.pi * day_index / period)


def _weekly(day_of_week):
    """Lower volume on weekends."""
    if day_of_week >= 5:
        return 0.6
    return 1.0


def _clamp(value, low, high):
    return max(low, min(high, value))


def generate_mock_data(site_list=None, product_list=None, site_profiles=None):
    """Generate 365 days of metrics for given site/product combinations.
    Falls back to config defaults if no lists provided.
    Returns list of tuples with 57 columns matching database insert order."""
    records = []
    today = datetime.now().date()
    start_date = today - timedelta(days=DATE_RANGE_DAYS)

    sites = site_list or SITES
    products = product_list or PRODUCT_LINES
    profiles = site_profiles or SITE_PROFILES

    for site in sites:
        profile = profiles.get(site, {"volume_mult": 1.0, "cost_mult": 1.0, "quality_offset": 0.0})
        vol_m = profile.get("volume_mult", 1.0)
        cost_m = profile.get("cost_mult", 1.0)
        q_off = profile.get("quality_offset", 0.0)

        for product in products:
            # Product-specific seed for consistency
            prod_seed = hash(f"{site}-{product}") % 1000
            random.seed(prod_seed)
            base_noise_offsets = [random.gauss(0, 0.3) for _ in range(30)]
            random.seed()

            for day_i in range(DATE_RANGE_DAYS + 1):
                current_date = start_date + timedelta(days=day_i)
                dow = current_date.weekday()
                weekly_factor = _weekly(dow)
                trend = day_i / DATE_RANGE_DAYS  # 0 to 1 over the year
                is_anomaly = random.random() < 0.015  # 1.5% chance

                # ══════════════════════════════════════════════════
                # QUALITY METRICS
                # ══════════════════════════════════════════════════

                batches_produced = int(_clamp(
                    (80 + trend * 5 + _seasonal(day_i, 10) + _noise(8)) * vol_m * weekly_factor,
                    20, 200
                ))
                reject_rate = _clamp(
                    (3.0 - trend * 0.8 - q_off * 0.3 + _seasonal(day_i, 0.5, 120) + _noise(0.8))
                    * (3.0 if is_anomaly else 1.0),
                    0.3, 15.0
                )
                batches_rejected = int(_clamp(batches_produced * reject_rate / 100, 0, batches_produced))

                theoretical_yield = _clamp(
                    (1000 + trend * 50 + _seasonal(day_i, 30) + _noise(20)) * vol_m * weekly_factor,
                    300, 2000
                )
                yield_efficiency = _clamp(
                    (0.94 + trend * 0.02 + q_off * 0.005 + _noise(0.015))
                    * (0.8 if is_anomaly else 1.0),
                    0.75, 0.995
                )
                actual_yield = theoretical_yield * yield_efficiency

                compliance_audits = int(_clamp(
                    (5 + _seasonal(day_i, 1, 30) + _noise(1)) * weekly_factor,
                    1, 15
                ))
                pass_rate = _clamp(
                    0.96 + trend * 0.01 + q_off * 0.003 + _noise(0.015),
                    0.80, 1.0
                )
                compliance_passed = int(_clamp(compliance_audits * pass_rate, 0, compliance_audits))

                # Right First Time
                rft_rate = _clamp(
                    0.88 + trend * 0.04 + q_off * 0.005 + _noise(0.025)
                    - (0.10 if is_anomaly else 0),
                    0.70, 0.99
                )
                rft_batches = int(_clamp(batches_produced * rft_rate, 0, batches_produced))

                # Deviations
                dev_per_100 = _clamp(
                    3.5 - trend * 1.0 - q_off * 0.3 + _noise(0.8)
                    + (4.0 if is_anomaly else 0),
                    0.2, 12.0
                )
                total_deviations = int(_clamp(batches_produced * dev_per_100 / 100, 0, batches_produced // 2))
                crit_frac = _clamp(0.05 + _noise(0.02) + (0.08 if is_anomaly else 0), 0.01, 0.20)
                critical_deviations = int(_clamp(total_deviations * crit_frac, 0, total_deviations))

                # CAPA
                capa_open = int(_clamp(2 + _noise(1.5) + _seasonal(day_i, 0.5, 60), 0, 8))
                avg_capa_days = _clamp(35 - trend * 8 + q_off * (-1.5) + _noise(5), 10, 60)
                capa_closed_days = round(capa_open * avg_capa_days, 1)

                # Investigations
                investigations = int(_clamp(1.5 + _noise(1) + _seasonal(day_i, 0.3, 45), 0, 6))
                avg_inv_days = _clamp(22 - trend * 5 + _noise(4), 8, 40)
                investigation_days = round(investigations * avg_inv_days, 1)

                # Audit Findings
                audit_findings = int(_clamp(
                    3.5 - trend * 1.2 - q_off * 0.4 + _noise(1.2)
                    + (3 if is_anomaly else 0),
                    0, 10
                ))

                # ══════════════════════════════════════════════════
                # SERVICE METRICS
                # ══════════════════════════════════════════════════

                supply_units = int(_clamp(
                    (800 + trend * 50 + _seasonal(day_i, 100) + _noise(50)) * vol_m * weekly_factor,
                    200, 1500
                ))
                demand_ratio = _clamp(0.88 + trend * 0.05 + _noise(0.08), 0.6, 1.15)
                demand_units = int(_clamp(supply_units / demand_ratio, 200, 1800))

                otif_total = int(_clamp(
                    (60 + trend * 5 + _seasonal(day_i, 8) + _noise(5)) * vol_m * weekly_factor,
                    10, 150
                ))
                otif_rate = _clamp(
                    0.92 + trend * 0.03 + q_off * 0.005 + _noise(0.02),
                    0.75, 0.995
                )
                otif_met = int(_clamp(otif_total * otif_rate, 0, otif_total))

                lead_time = _clamp(
                    14.0 - trend * 3.0 + _seasonal(day_i, 1.5, 60) + _noise(1.5)
                    + (8.0 if is_anomaly else 0),
                    3.0, 30.0
                )

                sla_total = int(_clamp(
                    (50 + trend * 5 + _noise(5)) * vol_m * weekly_factor,
                    5, 120
                ))
                sla_rate = _clamp(
                    0.94 + trend * 0.02 + q_off * 0.004 + _noise(0.02),
                    0.78, 0.995
                )
                sla_met = int(_clamp(sla_total * sla_rate, 0, sla_total))

                response_time = _clamp(
                    4.5 - trend * 1.0 + _seasonal(day_i, 0.5, 45) + _noise(1.0)
                    + (5.0 if is_anomaly else 0),
                    0.5, 15.0
                )

                # Schedule Adherence
                scheduled_batches = int(_clamp(
                    batches_produced * _clamp(1.05 + _noise(0.05), 0.95, 1.15),
                    20, 220
                ))
                sched_rate = _clamp(0.87 + trend * 0.04 + q_off * 0.003 + _noise(0.03), 0.70, 0.99)
                completed_scheduled = int(_clamp(scheduled_batches * sched_rate, 0, scheduled_batches))

                # Production Throughput
                production_output = int(_clamp(
                    (450 + trend * 50 + _seasonal(day_i, 40) + _noise(30)) * vol_m * weekly_factor,
                    100, 1000
                ))

                # Backorders
                total_orders_day = int(_clamp(
                    (40 + trend * 3 + _noise(4)) * vol_m * weekly_factor,
                    5, 100
                ))
                backorder_pct = _clamp(
                    0.06 - trend * 0.02 + _noise(0.015)
                    + (0.08 if is_anomaly else 0),
                    0.005, 0.18
                )
                backorders = int(_clamp(total_orders_day * backorder_pct, 0, total_orders_day))

                # Order Cycle Time
                order_cycle = _clamp(
                    9.0 - trend * 2.5 + _seasonal(day_i, 1.0, 50) + _noise(1.2)
                    + (4.0 if is_anomaly else 0),
                    2.0, 20.0
                )

                # Forecast Accuracy
                forecast_dem = int(_clamp(demand_units * _clamp(1.0 + _noise(0.05), 0.9, 1.1), 100, 2000))
                actual_dem = demand_units

                # Capacity Utilization
                avail_cap = _clamp((1000 + _noise(50)) * vol_m, 500, 2000)
                used_cap = _clamp(
                    avail_cap * _clamp(0.75 + trend * 0.06 + _noise(0.05), 0.50, 0.95),
                    200, avail_cap
                )

                # ══════════════════════════════════════════════════
                # COST METRICS
                # ══════════════════════════════════════════════════

                cogs = _clamp(
                    (125000 + trend * 10000 + _seasonal(day_i, 15000) + _noise(12000)) * cost_m * weekly_factor,
                    30000, 300000
                )
                revenue = cogs * _clamp(1.35 + trend * 0.05 + _noise(0.05), 1.1, 1.6)

                total_produced = int(_clamp(
                    (500 + trend * 30 + _seasonal(day_i, 40) + _noise(25)) * vol_m * weekly_factor,
                    100, 1200
                ))
                waste_rate = _clamp(
                    0.04 - trend * 0.01 - q_off * 0.003 + _noise(0.008)
                    + (0.06 if is_anomaly else 0),
                    0.005, 0.15
                )
                waste_units = int(_clamp(total_produced * waste_rate, 0, total_produced))

                inventory_value = _clamp(
                    (2000000 + trend * 200000 + _seasonal(day_i, 300000, 120) + _noise(150000)) * cost_m,
                    500000, 5000000
                )
                carrying_rate = _clamp(0.18 + _noise(0.01), 0.12, 0.25)

                # Cost per Batch
                cpb = _clamp(
                    (48000 - trend * 3000 + _noise(4000)) * cost_m
                    + (15000 if is_anomaly else 0),
                    25000, 80000
                )

                # COPQ
                copq_val = _clamp(
                    (90000 - trend * 15000 + _noise(12000)) * cost_m * (1 + reject_rate / 10)
                    + (40000 if is_anomaly else 0),
                    20000, 200000
                )

                # Scrap Cost
                scrap_val = _clamp(
                    (20000 - trend * 4000 + _noise(5000)) * cost_m * (1 + waste_rate * 5)
                    + (15000 if is_anomaly else 0),
                    3000, 60000
                )

                # Rework units
                rework_pct = _clamp(
                    0.035 - trend * 0.01 - q_off * 0.002 + _noise(0.008)
                    + (0.04 if is_anomaly else 0),
                    0.005, 0.12
                )
                rework_u = int(_clamp(total_produced * rework_pct, 0, total_produced // 3))

                # Planned vs Actual Cost
                planned_c = _clamp(cogs * _clamp(1.0 + _noise(0.02), 0.95, 1.05), 25000, 320000)
                actual_c = cogs

                # ══════════════════════════════════════════════════
                # EFFICIENCY METRICS
                # ══════════════════════════════════════════════════

                oee = _clamp(
                    0.78 + trend * 0.06 + q_off * 0.01 + _noise(0.03)
                    - (0.12 if is_anomaly else 0),
                    0.45, 0.96
                )

                avail_hrs = _clamp(16 + _noise(1), 8, 24) * weekly_factor
                downtime_pct = _clamp(
                    0.06 - trend * 0.02 + _noise(0.015)
                    + (0.10 if is_anomaly else 0),
                    0.01, 0.20
                )
                downtime_hrs = round(avail_hrs * downtime_pct, 2)

                changeover = _clamp(
                    4.5 - trend * 1.0 + _noise(0.8)
                    + (3.0 if is_anomaly else 0),
                    1.0, 10.0
                )

                line_cap = _clamp(1000 * vol_m + _noise(30), 500, 1800)
                line_eff_rate = _clamp(
                    0.84 + trend * 0.05 + q_off * 0.008 + _noise(0.025)
                    - (0.08 if is_anomaly else 0),
                    0.55, 0.98
                )
                line_out = line_cap * line_eff_rate * weekly_factor

                # ══════════════════════════════════════════════════
                # RISK METRICS
                # ══════════════════════════════════════════════════

                sup_risk = _clamp(
                    28 + _seasonal(day_i, 6, 70) + _noise(5)
                    + (15 if is_anomaly else 0)
                    - trend * 3,
                    5, 80
                )

                stockout_r = _clamp(
                    12 - trend * 3 + _noise(3) + _seasonal(day_i, 2, 40)
                    + (8 if is_anomaly else 0)
                    - (demand_ratio - 0.9) * 20,
                    1, 40
                )

                batch_fail = _clamp(
                    4.5 - trend * 1.2 + _noise(1.2)
                    + reject_rate * 0.5
                    + (5 if is_anomaly else 0),
                    0.5, 20
                )

                svc_risk = _clamp(
                    22 + _seasonal(day_i, 4, 55) + _noise(4)
                    + (lead_time - 10) * 1.5
                    - trend * 4
                    + (12 if is_anomaly else 0),
                    3, 70
                )

                # ══════════════════════════════════════════════════
                # BUILD RECORD (57 columns)
                # ══════════════════════════════════════════════════

                records.append((
                    current_date.isoformat(), site, product,
                    # Quality original (6)
                    batches_produced, batches_rejected,
                    round(theoretical_yield, 2), round(actual_yield, 2),
                    compliance_audits, compliance_passed,
                    # Quality new (8)
                    rft_batches, total_deviations, critical_deviations,
                    capa_open, round(capa_closed_days, 1),
                    investigations, round(investigation_days, 1),
                    audit_findings,
                    # Service original (8)
                    supply_units, demand_units,
                    otif_total, otif_met,
                    round(lead_time, 2), sla_total, sla_met, round(response_time, 2),
                    # Service new (10)
                    scheduled_batches, completed_scheduled, production_output,
                    backorders, total_orders_day, round(order_cycle, 2),
                    forecast_dem, actual_dem,
                    round(avail_cap, 2), round(used_cap, 2),
                    # Cost original (6)
                    round(cogs, 2), round(revenue, 2),
                    waste_units, total_produced,
                    round(inventory_value, 2), round(carrying_rate, 4),
                    # Cost new (6)
                    round(cpb, 2), round(copq_val, 2), round(scrap_val, 2),
                    rework_u, round(planned_c, 2), round(actual_c, 2),
                    # Efficiency (6)
                    round(oee, 4), round(downtime_hrs, 2), round(avail_hrs, 2),
                    round(changeover, 2), round(line_out, 2), round(line_cap, 2),
                    # Risk (4)
                    round(sup_risk, 2), round(stockout_r, 2),
                    round(batch_fail, 2), round(svc_risk, 2),
                ))

    return records


def seed_mock_data():
    """Seed mock data if database is empty."""
    if has_data():
        return False
    records = generate_mock_data()
    insert_metrics_batch(records)
    return True


def backfill_mock_data(site_names=None, product_names=None):
    """Generate mock data only for site/product combos that don't have data yet.
    Reads sites and products from DB tables. Returns count of new records."""
    db_sites = get_sites()
    db_products = get_product_lines()
    existing = get_existing_combos()

    # Build profiles dict from DB
    profiles = {}
    target_sites = []
    for s in db_sites:
        profiles[s["name"]] = {
            "volume_mult": s["volume_mult"],
            "cost_mult": s["cost_mult"],
            "quality_offset": s["quality_offset"],
        }
        if site_names is None or s["name"] in site_names:
            target_sites.append(s["name"])

    target_products = []
    for p in db_products:
        if product_names is None or p["name"] in product_names:
            target_products.append(p["name"])

    # Find combos that need data
    new_sites = []
    new_products = []
    for site in target_sites:
        for prod in target_products:
            if (site, prod) not in existing:
                if site not in new_sites:
                    new_sites.append(site)
                if prod not in new_products:
                    new_products.append(prod)

    if not new_sites or not new_products:
        return 0

    # Generate data only for new combos
    all_records = generate_mock_data(
        site_list=new_sites,
        product_list=new_products,
        site_profiles=profiles,
    )

    # Filter out any combos that already exist
    records = [r for r in all_records if (r[1], r[2]) not in existing]

    if records:
        insert_metrics_batch(records)
    return len(records)
