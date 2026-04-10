"""FastAPI router that exposes the retail price monitor to the dashboard."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ops_dashboard.retail_price_monitor import analytics
from ops_dashboard.retail_price_monitor.config import ALERT_THRESHOLDS, BRAND_NAME

router = APIRouter()


@router.get("/summary")
def get_summary(date: Optional[str] = Query(None, description="YYYY-MM-DD")):
    """Executive-screen summary for a given date (defaults to latest)."""

    summary = analytics.daily_summary(date)
    if not summary.get("date"):
        raise HTTPException(status_code=404, detail="No price observations available yet")
    return summary


@router.get("/morning-brief")
def get_morning_brief(date: Optional[str] = Query(None)):
    brief = analytics.morning_brief(date)
    if not brief.get("date"):
        raise HTTPException(status_code=404, detail="No price observations available yet")
    return brief


@router.get("/comparison")
def get_comparison(date: Optional[str] = Query(None)):
    """Per-product comparison rows (one row per product, prices for each retailer)."""

    return analytics.product_comparison_for_date(date)


@router.get("/products")
def get_products():
    return {"brand": BRAND_NAME, "products": analytics.list_products()}


@router.get("/products/{product_id}/trend")
def get_product_trend(product_id: int, days: int = Query(30, ge=2, le=365)):
    trend = analytics.product_trend(product_id, days=days)
    if not trend["series"]:
        raise HTTPException(status_code=404, detail="No trend data for this product")
    return trend


@router.get("/alerts")
def get_alerts(date: Optional[str] = Query(None), limit: int = Query(200, ge=1, le=1000)):
    return {"date": date, "alerts": analytics.alerts_for_date(date, limit=limit)}


@router.get("/anomalies")
def get_anomalies(date: Optional[str] = Query(None)):
    return analytics.anomalies_report(date)


@router.get("/retailers")
def get_retailers():
    return {"retailers": analytics.list_retailers()}


@router.get("/categories")
def get_categories():
    return {"categories": analytics.list_categories()}


@router.get("/config")
def get_config():
    """Expose the alert thresholds so the dashboard can document them."""

    return {"brand": BRAND_NAME, "alert_thresholds": ALERT_THRESHOLDS}


@router.post("/alerts/rebuild")
def rebuild_alerts(date: Optional[str] = Query(None)):
    """Recompute alerts for a given day (defaults to the latest snapshot)."""

    return analytics.generate_alerts_for_date(date)
