"""Pydantic models for openFDA API responses."""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any


# ── Generic openFDA wrapper ─────────────────────────────────────

class FDAMeta(BaseModel):
    disclaimer: Optional[str] = None
    terms: Optional[str] = None
    license: Optional[str] = None
    last_updated: Optional[str] = None
    results: Optional[Dict[str, Any]] = None


class FDACountItem(BaseModel):
    term: str
    count: int


# ── Drug Adverse Events ─────────────────────────────────────────

class DrugInfo(BaseModel):
    medicinalproduct: Optional[str] = None
    drugindication: Optional[str] = None
    drugcharacterization: Optional[str] = None
    activesubstance: Optional[Dict[str, Any]] = None
    openfda: Optional[Dict[str, Any]] = None


class Reaction(BaseModel):
    reactionmeddrapt: Optional[str] = None
    reactionoutcome: Optional[str] = None


class AdverseEvent(BaseModel):
    safetyreportid: Optional[str] = None
    receivedate: Optional[str] = None
    receiptdate: Optional[str] = None
    serious: Optional[str] = None
    seriousnessdeath: Optional[str] = None
    seriousnesshospitalization: Optional[str] = None
    patient: Optional[Dict[str, Any]] = None


class AdverseEventSummary(BaseModel):
    """Simplified adverse event for dashboard display."""
    report_id: Optional[str] = None
    receive_date: Optional[str] = None
    serious: bool = False
    seriousness: List[str] = []
    drugs: List[str] = []
    reactions: List[str] = []
    country: Optional[str] = None


# ── Drug Enforcement / Recalls ──────────────────────────────────

class DrugRecall(BaseModel):
    recall_number: Optional[str] = None
    reason_for_recall: Optional[str] = None
    status: Optional[str] = None
    distribution_pattern: Optional[str] = None
    product_description: Optional[str] = None
    classification: Optional[str] = None  # Class I, II, III
    recalling_firm: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    voluntary_mandated: Optional[str] = None
    report_date: Optional[str] = None
    recall_initiation_date: Optional[str] = None


# ── Drug Labeling ───────────────────────────────────────────────

class DrugLabel(BaseModel):
    id: Optional[str] = None
    effective_time: Optional[str] = None
    purpose: Optional[List[str]] = None
    indications_and_usage: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    dosage_and_administration: Optional[List[str]] = None
    adverse_reactions: Optional[List[str]] = None
    brand_name: Optional[str] = None
    generic_name: Optional[str] = None
    manufacturer_name: Optional[str] = None
    product_type: Optional[str] = None
    route: Optional[List[str]] = None


# ── Drug NDC ────────────────────────────────────────────────────

class DrugNDC(BaseModel):
    product_ndc: Optional[str] = None
    brand_name: Optional[str] = None
    generic_name: Optional[str] = None
    labeler_name: Optional[str] = None
    dosage_form: Optional[str] = None
    route: Optional[List[str]] = None
    product_type: Optional[str] = None
    marketing_category: Optional[str] = None
    active_ingredients: Optional[List[Dict[str, str]]] = None
    packaging: Optional[List[Dict[str, Any]]] = None
    listing_expiration_date: Optional[str] = None


# ── Drug Shortages ─────────────────────────────────────────────

class DrugShortage(BaseModel):
    generic_name: Optional[str] = None
    proprietary_name: Optional[str] = None
    status: Optional[str] = None  # "Currently in Shortage", "Resolved"
    initial_posting_date: Optional[str] = None
    update_date: Optional[str] = None
    dosage_form: Optional[str] = None
    presentation: Optional[str] = None
    therapeutic_category: Optional[List[str]] = None
    company_name: Optional[str] = None
    shortage_reason: Optional[str] = None
    resolved_note: Optional[str] = None
    availability: Optional[str] = None


class ShortagesResponse(BaseModel):
    total: int = 0
    skip: int = 0
    limit: int = 10
    shortages: List[DrugShortage] = []


# ── API response wrappers ───────────────────────────────────────

class FDASearchResponse(BaseModel):
    meta: Optional[FDAMeta] = None
    total: int = 0
    skip: int = 0
    limit: int = 10
    results: List[Dict[str, Any]] = []


class FDACountResponse(BaseModel):
    meta: Optional[FDAMeta] = None
    results: List[FDACountItem] = []


class AdverseEventsResponse(BaseModel):
    total: int = 0
    skip: int = 0
    limit: int = 10
    events: List[AdverseEventSummary] = []


class RecallsResponse(BaseModel):
    total: int = 0
    skip: int = 0
    limit: int = 10
    recalls: List[DrugRecall] = []


class LabelsResponse(BaseModel):
    total: int = 0
    skip: int = 0
    limit: int = 10
    labels: List[DrugLabel] = []


class NDCResponse(BaseModel):
    total: int = 0
    skip: int = 0
    limit: int = 10
    products: List[DrugNDC] = []
