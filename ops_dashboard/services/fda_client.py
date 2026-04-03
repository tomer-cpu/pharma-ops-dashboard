"""
Client for the openFDA public API.

Endpoints used:
  - Drug adverse events:  https://api.fda.gov/drug/event.json
  - Drug recalls:         https://api.fda.gov/drug/enforcement.json
  - Drug labeling:        https://api.fda.gov/drug/label.json

No API key is required for basic usage (rate-limited to ~240 requests/min).
An optional API key can be set via the FDA_API_KEY environment variable.

Docs: https://open.fda.gov/apis/
"""

import os
import httpx
from typing import Any

FDA_BASE = "https://api.fda.gov"
FDA_API_KEY = os.getenv("FDA_API_KEY", "")
TIMEOUT = 15.0


def _base_params() -> dict[str, str]:
    params: dict[str, str] = {}
    if FDA_API_KEY:
        params["api_key"] = FDA_API_KEY
    return params


async def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    """Make a GET request to the openFDA API."""
    url = f"{FDA_BASE}{path}"
    merged = _base_params()
    if params:
        merged.update(params)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, params=merged)
        resp.raise_for_status()
        return resp.json()


# ── Drug Adverse Events ──────────────────────────────────────────────

async def get_adverse_events(
    search: str | None = None,
    limit: int = 10,
    skip: int = 0,
) -> dict:
    """Fetch drug adverse event reports."""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    return await _get("/drug/event.json", params)


async def get_adverse_events_by_reaction(limit: int = 10) -> list[dict]:
    """Top adverse-event reactions (count endpoint)."""
    params: dict[str, Any] = {
        "count": "patient.reaction.reactionmeddrapt.exact",
        "limit": limit,
    }
    data = await _get("/drug/event.json", params)
    return data.get("results", [])


async def get_adverse_events_by_drug(limit: int = 10) -> list[dict]:
    """Top drugs mentioned in adverse-event reports."""
    params: dict[str, Any] = {
        "count": "patient.drug.medicinalproduct.exact",
        "limit": limit,
    }
    data = await _get("/drug/event.json", params)
    return data.get("results", [])


async def get_adverse_events_by_seriousness(limit: int = 5) -> list[dict]:
    """Adverse events grouped by seriousness indicator."""
    params: dict[str, Any] = {
        "count": "serious",
        "limit": limit,
    }
    data = await _get("/drug/event.json", params)
    return data.get("results", [])


async def get_adverse_events_over_time(search: str | None = None, limit: int = 12) -> list[dict]:
    """Adverse events counted by received-date quarter."""
    params: dict[str, Any] = {
        "count": "receivedate",
        "limit": limit,
    }
    if search:
        params["search"] = search
    data = await _get("/drug/event.json", params)
    return data.get("results", [])


# ── Drug Enforcement / Recalls ───────────────────────────────────────

async def get_drug_recalls(
    search: str | None = None,
    limit: int = 10,
    skip: int = 0,
) -> dict:
    """Fetch drug enforcement (recall) reports."""
    params: dict[str, Any] = {"limit": limit, "skip": skip}
    if search:
        params["search"] = search
    return await _get("/drug/enforcement.json", params)


async def get_recalls_by_classification(limit: int = 5) -> list[dict]:
    """Recall counts grouped by classification (I, II, III)."""
    params: dict[str, Any] = {
        "count": "classification.exact",
        "limit": limit,
    }
    data = await _get("/drug/enforcement.json", params)
    return data.get("results", [])


async def get_recalls_by_status(limit: int = 5) -> list[dict]:
    """Recall counts grouped by status."""
    params: dict[str, Any] = {
        "count": "status.exact",
        "limit": limit,
    }
    data = await _get("/drug/enforcement.json", params)
    return data.get("results", [])


async def get_recalls_by_reason(limit: int = 10) -> list[dict]:
    """Top recall reasons."""
    params: dict[str, Any] = {
        "count": "reason_for_recall.exact",
        "limit": limit,
    }
    data = await _get("/drug/enforcement.json", params)
    return data.get("results", [])


# ── Drug Labeling ────────────────────────────────────────────────────

async def search_drug_labels(
    drug_name: str,
    limit: int = 5,
) -> dict:
    """Search drug labeling by product name."""
    params: dict[str, Any] = {
        "search": f'openfda.brand_name:"{drug_name}"',
        "limit": limit,
    }
    return await _get("/drug/label.json", params)
