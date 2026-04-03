"""FastAPI router exposing openFDA data to the dashboard.

Endpoints
─────────
GET /api/fda/adverse-events          — Drug adverse event reports
GET /api/fda/adverse-events/count    — Top reactions / drugs / countries
GET /api/fda/recalls                 — Drug enforcement / recall reports
GET /api/fda/recalls/count           — Recall classification breakdown
GET /api/fda/labels                  — Drug labeling (SPL) search
GET /api/fda/ndc                     — NDC directory search
GET /api/fda/search                  — Generic raw search on any endpoint
GET /api/fda/count                   — Generic raw count on any endpoint
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from ops_dashboard.services.fda_client import (
    close_client,
    count_adverse_events,
    count_drug_recalls,
    count_drug_shortages,
    fda_count,
    fda_search,
    get_adverse_events,
    get_drug_labels,
    get_drug_ndc,
    get_drug_recalls,
    get_drug_shortages,
)
from ops_dashboard.models.fda_schemas import (
    AdverseEventsResponse,
    FDACountResponse,
    FDASearchResponse,
    LabelsResponse,
    NDCResponse,
    RecallsResponse,
    ShortagesResponse,
)

router = APIRouter()

# ── Allowed endpoints for the generic proxy (whitelist) ──────────
ALLOWED_ENDPOINTS = {
    "drug_event": "/drug/event.json",
    "drug_label": "/drug/label.json",
    "drug_ndc": "/drug/ndc.json",
    "drug_enforcement": "/drug/enforcement.json",
    "drug_shortages": "/drug/shortages.json",
    "device_event": "/device/event.json",
    "device_recall": "/device/recall.json",
    "device_classification": "/device/classification.json",
    "device_enforcement": "/device/enforcement.json",
    "food_event": "/food/event.json",
    "food_enforcement": "/food/enforcement.json",
    "food_recall": "/food/recall.json",
}


def _resolve_endpoint(endpoint_key: str) -> str:
    if endpoint_key not in ALLOWED_ENDPOINTS:
        allowed = ", ".join(sorted(ALLOWED_ENDPOINTS.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown endpoint '{endpoint_key}'. Allowed: {allowed}",
        )
    return ALLOWED_ENDPOINTS[endpoint_key]


# ── Drug Adverse Events ─────────────────────────────────────────

@router.get("/adverse-events", response_model=AdverseEventsResponse)
async def adverse_events(
    search: Optional[str] = Query(None, description="openFDA search query, e.g. patient.drug.medicinalproduct:aspirin"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Drug adverse event reports with parsed drugs & reactions."""
    try:
        return await get_adverse_events(search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


@router.get("/adverse-events/count", response_model=FDACountResponse)
async def adverse_events_count(
    field: str = Query(
        "patient.reaction.reactionmeddrapt.exact",
        description="Field to count. Common: patient.reaction.reactionmeddrapt.exact, patient.drug.medicinalproduct.exact, occurcountry.exact",
    ),
    search: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=1000),
):
    """Count adverse events grouped by a field."""
    try:
        return await count_adverse_events(count_field=field, search=search, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


# ── Drug Recalls / Enforcement ──────────────────────────────────

@router.get("/recalls", response_model=RecallsResponse)
async def recalls(
    search: Optional[str] = Query(None, description="e.g. classification:\"Class I\"+AND+status:\"Ongoing\""),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Drug enforcement / recall reports."""
    try:
        return await get_drug_recalls(search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


@router.get("/recalls/count", response_model=FDACountResponse)
async def recalls_count(
    field: str = Query(
        "classification.exact",
        description="Field to count. Common: classification.exact, status.exact, voluntary_mandated.exact",
    ),
    search: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=1000),
):
    """Count drug recalls grouped by a field."""
    try:
        return await count_drug_recalls(count_field=field, search=search, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


# ── Drug Labeling ───────────────────────────────────────────────

@router.get("/labels", response_model=LabelsResponse)
async def labels(
    search: Optional[str] = Query(None, description="e.g. openfda.brand_name:advil"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Drug labeling (SPL) data — indications, warnings, dosage."""
    try:
        return await get_drug_labels(search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


# ── Drug NDC Directory ──────────────────────────────────────────

@router.get("/ndc", response_model=NDCResponse)
async def ndc(
    search: Optional[str] = Query(None, description="e.g. brand_name:tylenol"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """National Drug Code directory search."""
    try:
        return await get_drug_ndc(search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


# ── Drug Shortages ──────────────────────────────────────────────

@router.get("/shortages", response_model=ShortagesResponse)
async def shortages(
    search: Optional[str] = Query(None, description="e.g. generic_name:amoxicillin"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Drug shortage reports — currently in shortage and resolved."""
    try:
        return await get_drug_shortages(search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


@router.get("/shortages/count", response_model=FDACountResponse)
async def shortages_count(
    field: str = Query(
        "status.exact",
        description="Field to count. Common: status.exact, therapeutic_category.exact",
    ),
    search: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=1000),
):
    """Count drug shortages grouped by a field."""
    try:
        return await count_drug_shortages(count_field=field, search=search, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


# ── Generic proxy endpoints ─────────────────────────────────────

@router.get("/search", response_model=FDASearchResponse)
async def generic_search(
    endpoint: str = Query(..., description="Endpoint key, e.g. drug_event, device_recall, food_enforcement"),
    search: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Generic search on any whitelisted openFDA endpoint."""
    fda_path = _resolve_endpoint(endpoint)
    try:
        return await fda_search(fda_path, search=search, limit=limit, skip=skip)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")


@router.get("/count", response_model=FDACountResponse)
async def generic_count(
    endpoint: str = Query(..., description="Endpoint key, e.g. drug_event, drug_enforcement"),
    field: str = Query(..., description="Field to count"),
    search: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=1000),
):
    """Generic count on any whitelisted openFDA endpoint."""
    fda_path = _resolve_endpoint(endpoint)
    try:
        return await fda_count(fda_path, count_field=field, search=search, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FDA API error: {e}")
