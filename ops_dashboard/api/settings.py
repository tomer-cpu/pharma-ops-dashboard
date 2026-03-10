from fastapi import APIRouter, HTTPException
from typing import List
from ops_dashboard.data.database import (
    get_targets, update_target, METRIC_DISPLAY_NAMES, METRIC_CATEGORIES,
    get_sites, add_site, update_site, delete_site,
    get_product_lines, add_product_line, delete_product_line,
)
from ops_dashboard.models.schemas import (
    TargetUpdate, TargetConfig,
    SiteCreate, SiteUpdate, SiteConfig,
    ProductLineCreate, ProductLineConfig,
    GenerateDataRequest,
)
from ops_dashboard.data.mock_generator import backfill_mock_data

router = APIRouter()


# ── Metric Targets ──────────────────────────────────────────────

@router.get("/targets")
def get_all_targets():
    targets = get_targets()
    result = []
    for name, cfg in targets.items():
        result.append(TargetConfig(
            metric_name=name,
            display_name=METRIC_DISPLAY_NAMES.get(name, name),
            value=cfg["value"],
            direction=cfg["direction"],
            unit=cfg["unit"],
            category=METRIC_CATEGORIES.get(name, ""),
            weight=cfg.get("weight", 10),
            enabled=cfg.get("enabled", True),
        ))
    cat_order = {"quality": 0, "service": 1, "cost": 2, "efficiency": 3, "risk": 4}
    return sorted(result, key=lambda t: (cat_order.get(t.category, 9), t.metric_name))


@router.put("/targets")
def update_targets(updates: List[TargetUpdate]):
    for u in updates:
        update_target(u.metric_name, u.value, u.weight, u.enabled)
    return {"status": "ok", "updated": len(updates)}


# ── Sites ───────────────────────────────────────────────────────

@router.get("/sites")
def list_sites():
    sites = get_sites(include_inactive=False)
    return [SiteConfig(
        name=s["name"],
        volume_mult=s["volume_mult"],
        cost_mult=s["cost_mult"],
        quality_offset=s["quality_offset"],
        active=bool(s["active"]),
    ) for s in sites]


@router.post("/sites")
def create_site(site: SiteCreate):
    if not site.name.strip():
        raise HTTPException(status_code=400, detail="Site name cannot be empty")
    add_site(site.name.strip(), site.volume_mult, site.cost_mult, site.quality_offset)
    return {"status": "ok", "name": site.name.strip()}


@router.put("/sites/{name}")
def modify_site(name: str, site: SiteUpdate):
    update_site(name, site.volume_mult, site.cost_mult, site.quality_offset)
    return {"status": "ok", "name": name}


@router.delete("/sites/{name}")
def remove_site(name: str):
    delete_site(name)
    return {"status": "ok", "name": name}


# ── Product Lines ───────────────────────────────────────────────

@router.get("/product-lines")
def list_product_lines():
    products = get_product_lines(include_inactive=False)
    return [ProductLineConfig(
        name=p["name"],
        active=bool(p["active"]),
    ) for p in products]


@router.post("/product-lines")
def create_product_line(product: ProductLineCreate):
    if not product.name.strip():
        raise HTTPException(status_code=400, detail="Product line name cannot be empty")
    add_product_line(product.name.strip())
    return {"status": "ok", "name": product.name.strip()}


@router.delete("/product-lines/{name}")
def remove_product_line(name: str):
    delete_product_line(name)
    return {"status": "ok", "name": name}


# ── Mock Data Generation ────────────────────────────────────────

@router.post("/generate-data")
def generate_data(request: GenerateDataRequest):
    count = backfill_mock_data(request.sites, request.product_lines)
    return {"status": "ok", "records_generated": count}
