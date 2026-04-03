"""FDA openAPI endpoints for the dashboard."""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional
import httpx

from ops_dashboard.services.fda_client import (
    get_adverse_events,
    get_adverse_events_by_reaction,
    get_adverse_events_by_drug,
    get_adverse_events_by_seriousness,
    get_adverse_events_over_time,
    get_drug_recalls,
    get_recalls_by_classification,
    get_recalls_by_status,
    get_recalls_by_reason,
    search_drug_labels,
)

router = APIRouter()


@router.get("/adverse-events")
async def adverse_events(
    search: Optional[str] = Query(None, description="openFDA search expression"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Recent drug adverse event reports."""
    try:
        data = await get_adverse_events(search=search, limit=limit, skip=skip)
        results = data.get("results", [])
        meta = data.get("meta", {})
        return {"results": results, "meta": meta}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="FDA API error")


@router.get("/adverse-events/top-reactions")
async def top_reactions(limit: int = Query(10, ge=1, le=25)):
    """Top adverse event reactions by count."""
    try:
        return await get_adverse_events_by_reaction(limit=limit)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/adverse-events/top-drugs")
async def top_drugs(limit: int = Query(10, ge=1, le=25)):
    """Top drugs in adverse event reports."""
    try:
        return await get_adverse_events_by_drug(limit=limit)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/adverse-events/seriousness")
async def seriousness_breakdown():
    """Adverse events by seriousness (1=serious, 2=not serious)."""
    try:
        return await get_adverse_events_by_seriousness()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/adverse-events/timeline")
async def adverse_event_timeline(
    search: Optional[str] = Query(None),
    limit: int = Query(12, ge=1, le=100),
):
    """Adverse event counts over time."""
    try:
        return await get_adverse_events_over_time(search=search, limit=limit)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/recalls")
async def recalls(
    search: Optional[str] = Query(None, description="openFDA search expression"),
    limit: int = Query(10, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    """Recent drug recall/enforcement reports."""
    try:
        data = await get_drug_recalls(search=search, limit=limit, skip=skip)
        results = data.get("results", [])
        meta = data.get("meta", {})
        return {"results": results, "meta": meta}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="FDA API error")


@router.get("/recalls/by-classification")
async def recalls_by_class():
    """Recall counts by classification (Class I/II/III)."""
    try:
        return await get_recalls_by_classification()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/recalls/by-status")
async def recalls_by_status():
    """Recall counts by status."""
    try:
        return await get_recalls_by_status()
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/recalls/top-reasons")
async def top_recall_reasons(limit: int = Query(10, ge=1, le=25)):
    """Top reasons for drug recalls."""
    try:
        return await get_recalls_by_reason(limit=limit)
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="FDA API error")


@router.get("/drug-label")
async def drug_label(
    drug_name: str = Query(..., description="Brand name to search"),
    limit: int = Query(5, ge=1, le=20),
):
    """Search FDA drug labeling by brand name."""
    try:
        data = await search_drug_labels(drug_name=drug_name, limit=limit)
        results = data.get("results", [])
        meta = data.get("meta", {})
        return {"results": results, "meta": meta}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"results": [], "meta": {}}
        raise HTTPException(status_code=e.response.status_code, detail="FDA API error")
