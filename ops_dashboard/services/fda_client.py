"""Async HTTP client for the openFDA API (https://open.fda.gov/apis/).

Supports all major drug endpoints: adverse events, enforcement/recalls,
labeling, and NDC directory.  Results are normalised into dashboard-friendly
Pydantic models.

Rate limits (without API key): 40 requests/minute, 1 000 requests/day.
With an API key: 240 requests/minute.  Set the FDA_API_KEY env-var to use one.
"""

import os
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ops_dashboard.models.fda_schemas import (
    AdverseEventSummary,
    AdverseEventsResponse,
    DrugLabel,
    DrugNDC,
    DrugRecall,
    FDACountItem,
    FDACountResponse,
    FDASearchResponse,
    LabelsResponse,
    NDCResponse,
    RecallsResponse,
)

logger = logging.getLogger(__name__)

FDA_BASE_URL = "https://api.fda.gov"

# Optional API key — raises rate-limit from 40 to 240 req/min
FDA_API_KEY: Optional[str] = os.environ.get("FDA_API_KEY")

# Reusable async client (created lazily)
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_client() -> None:
    """Shutdown hook — close the shared HTTP client."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ── Low-level helpers ────────────────────────────────────────────

async def _fda_get(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a GET against the openFDA API and return the parsed JSON."""
    if FDA_API_KEY:
        params["api_key"] = FDA_API_KEY

    # Remove None/empty values
    params = {k: v for k, v in params.items() if v is not None and v != ""}

    url = f"{FDA_BASE_URL}{endpoint}"
    client = _get_client()
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


# ── Generic search & count ───────────────────────────────────────

async def fda_search(
    endpoint: str,
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> FDASearchResponse:
    """Generic openFDA search returning raw results + pagination info."""
    params: Dict[str, Any] = {"limit": min(limit, 1000), "skip": skip}
    if search:
        params["search"] = search

    data = await _fda_get(endpoint, params)
    meta = data.get("meta", {})
    total = meta.get("results", {}).get("total", 0)
    return FDASearchResponse(
        meta=meta,
        total=total,
        skip=skip,
        limit=limit,
        results=data.get("results", []),
    )


async def fda_count(
    endpoint: str,
    count_field: str,
    search: Optional[str] = None,
    limit: int = 10,
) -> FDACountResponse:
    """Count occurrences of *count_field* values (top-N)."""
    params: Dict[str, Any] = {"count": count_field, "limit": min(limit, 1000)}
    if search:
        params["search"] = search

    data = await _fda_get(endpoint, params)
    items = [FDACountItem(term=str(r.get("term", "")), count=r.get("count", 0)) for r in data.get("results", [])]
    return FDACountResponse(meta=data.get("meta"), results=items)


# ── Drug Adverse Events ─────────────────────────────────────────

def _parse_adverse_event(raw: Dict[str, Any]) -> AdverseEventSummary:
    patient = raw.get("patient", {})
    drugs = patient.get("drug", [])
    reactions = patient.get("reaction", [])

    seriousness = []
    if raw.get("serious") == "1":
        if raw.get("seriousnessdeath") == "1":
            seriousness.append("Death")
        if raw.get("seriousnesshospitalization") == "1":
            seriousness.append("Hospitalization")
        if raw.get("seriousnesslifethreatening") == "1":
            seriousness.append("Life-Threatening")
        if raw.get("seriousnessdisabling") == "1":
            seriousness.append("Disabling")
        if raw.get("seriousnesscongenitalanomali") == "1":
            seriousness.append("Congenital Anomaly")
        if raw.get("seriousnessother") == "1":
            seriousness.append("Other Serious")
        if not seriousness:
            seriousness.append("Serious")

    return AdverseEventSummary(
        report_id=raw.get("safetyreportid"),
        receive_date=raw.get("receivedate"),
        serious=raw.get("serious") == "1",
        seriousness=seriousness,
        drugs=[d.get("medicinalproduct", "Unknown") for d in drugs[:10]],
        reactions=[r.get("reactionmeddrapt", "Unknown") for r in reactions[:10]],
        country=raw.get("occurcountry"),
    )


async def get_adverse_events(
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> AdverseEventsResponse:
    """Fetch drug adverse event reports."""
    resp = await fda_search("/drug/event.json", search=search, limit=limit, skip=skip)
    events = [_parse_adverse_event(r) for r in resp.results]
    return AdverseEventsResponse(total=resp.total, skip=skip, limit=limit, events=events)


async def count_adverse_events(
    count_field: str = "patient.reaction.reactionmeddrapt.exact",
    search: Optional[str] = None,
    limit: int = 10,
) -> FDACountResponse:
    """Count adverse events by a field (default: reaction type)."""
    return await fda_count("/drug/event.json", count_field, search=search, limit=limit)


# ── Drug Enforcement / Recalls ──────────────────────────────────

def _parse_recall(raw: Dict[str, Any]) -> DrugRecall:
    return DrugRecall(
        recall_number=raw.get("recall_number"),
        reason_for_recall=raw.get("reason_for_recall"),
        status=raw.get("status"),
        distribution_pattern=raw.get("distribution_pattern"),
        product_description=raw.get("product_description"),
        classification=raw.get("classification"),
        recalling_firm=raw.get("recalling_firm"),
        city=raw.get("city"),
        state=raw.get("state"),
        country=raw.get("country"),
        voluntary_mandated=raw.get("voluntary_mandated"),
        report_date=raw.get("report_date"),
        recall_initiation_date=raw.get("recall_initiation_date"),
    )


async def get_drug_recalls(
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> RecallsResponse:
    """Fetch drug enforcement / recall reports."""
    resp = await fda_search("/drug/enforcement.json", search=search, limit=limit, skip=skip)
    recalls = [_parse_recall(r) for r in resp.results]
    return RecallsResponse(total=resp.total, skip=skip, limit=limit, recalls=recalls)


async def count_drug_recalls(
    count_field: str = "classification.exact",
    search: Optional[str] = None,
    limit: int = 10,
) -> FDACountResponse:
    """Count drug recalls by a field (default: classification)."""
    return await fda_count("/drug/enforcement.json", count_field, search=search, limit=limit)


# ── Drug Labeling ───────────────────────────────────────────────

def _parse_label(raw: Dict[str, Any]) -> DrugLabel:
    openfda = raw.get("openfda", {})
    return DrugLabel(
        id=raw.get("id"),
        effective_time=raw.get("effective_time"),
        purpose=raw.get("purpose"),
        indications_and_usage=raw.get("indications_and_usage"),
        warnings=raw.get("warnings"),
        dosage_and_administration=raw.get("dosage_and_administration"),
        adverse_reactions=raw.get("adverse_reactions"),
        brand_name=openfda.get("brand_name", [None])[0] if openfda.get("brand_name") else None,
        generic_name=openfda.get("generic_name", [None])[0] if openfda.get("generic_name") else None,
        manufacturer_name=openfda.get("manufacturer_name", [None])[0] if openfda.get("manufacturer_name") else None,
        product_type=openfda.get("product_type", [None])[0] if openfda.get("product_type") else None,
        route=openfda.get("route"),
    )


async def get_drug_labels(
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> LabelsResponse:
    """Fetch drug labeling information."""
    resp = await fda_search("/drug/label.json", search=search, limit=limit, skip=skip)
    labels = [_parse_label(r) for r in resp.results]
    return LabelsResponse(total=resp.total, skip=skip, limit=limit, labels=labels)


# ── Drug NDC Directory ──────────────────────────────────────────

def _parse_ndc(raw: Dict[str, Any]) -> DrugNDC:
    return DrugNDC(
        product_ndc=raw.get("product_ndc"),
        brand_name=raw.get("brand_name"),
        generic_name=raw.get("generic_name"),
        labeler_name=raw.get("labeler_name"),
        dosage_form=raw.get("dosage_form"),
        route=raw.get("route"),
        product_type=raw.get("product_type"),
        marketing_category=raw.get("marketing_category"),
        active_ingredients=raw.get("active_ingredients"),
        packaging=raw.get("packaging"),
        listing_expiration_date=raw.get("listing_expiration_date"),
    )


async def get_drug_ndc(
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> NDCResponse:
    """Fetch drug NDC directory entries."""
    resp = await fda_search("/drug/ndc.json", search=search, limit=limit, skip=skip)
    products = [_parse_ndc(r) for r in resp.results]
    return NDCResponse(total=resp.total, skip=skip, limit=limit, products=products)
