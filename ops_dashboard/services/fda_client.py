"""Async HTTP client for the openFDA API (https://open.fda.gov/apis/).

Supports all major drug endpoints: adverse events, enforcement/recalls,
labeling, and NDC directory.  Results are normalised into dashboard-friendly
Pydantic models.

Rate limits (without API key): 40 requests/minute, 1 000 requests/day.
With an API key: 240 requests/minute.  Set the FDA_API_KEY env-var to use one.

When the live API is unreachable (e.g. no outbound internet), the client
automatically falls back to built-in demo data so the dashboard stays usable.
"""

import os
import logging
import random
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ops_dashboard.models.fda_schemas import (
    AdverseEventSummary,
    AdverseEventsResponse,
    DrugLabel,
    DrugNDC,
    DrugRecall,
    DrugShortage,
    FDACountItem,
    FDACountResponse,
    FDASearchResponse,
    LabelsResponse,
    NDCResponse,
    RecallsResponse,
    ShortagesResponse,
)

logger = logging.getLogger(__name__)

FDA_BASE_URL = "https://api.fda.gov"

# Optional API key — raises rate-limit from 40 to 240 req/min
FDA_API_KEY: Optional[str] = os.environ.get("FDA_API_KEY")

# Reusable async client (created lazily)
_client: Optional[httpx.AsyncClient] = None

# Track whether the live API is reachable
_live_api_available: Optional[bool] = None


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
    global _live_api_available

    if FDA_API_KEY:
        params["api_key"] = FDA_API_KEY

    # Remove None/empty values
    params = {k: v for k, v in params.items() if v is not None and v != ""}

    url = f"{FDA_BASE_URL}{endpoint}"
    client = _get_client()
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        _live_api_available = True
        return resp.json()
    except Exception as e:
        logger.warning("FDA API unreachable (%s), using demo data", e)
        _live_api_available = False
        raise


def _is_demo_mode() -> bool:
    return _live_api_available is False


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

    try:
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
    except Exception:
        # Return empty for generic search in demo mode
        return FDASearchResponse(total=0, skip=skip, limit=limit, results=[])


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

    try:
        data = await _fda_get(endpoint, params)
        items = [FDACountItem(term=str(r.get("term", "")), count=r.get("count", 0)) for r in data.get("results", [])]
        return FDACountResponse(meta=data.get("meta"), results=items)
    except Exception:
        return _demo_count(endpoint, count_field, limit)


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
    try:
        resp = await fda_search("/drug/event.json", search=search, limit=limit, skip=skip)
        if resp.results:
            events = [_parse_adverse_event(r) for r in resp.results]
            return AdverseEventsResponse(total=resp.total, skip=skip, limit=limit, events=events)
    except Exception:
        pass
    return _demo_adverse_events(limit, skip)


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
    try:
        resp = await fda_search("/drug/enforcement.json", search=search, limit=limit, skip=skip)
        if resp.results:
            recalls = [_parse_recall(r) for r in resp.results]
            return RecallsResponse(total=resp.total, skip=skip, limit=limit, recalls=recalls)
    except Exception:
        pass
    return _demo_recalls(limit, skip)


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
    try:
        resp = await fda_search("/drug/label.json", search=search, limit=limit, skip=skip)
        if resp.results:
            labels = [_parse_label(r) for r in resp.results]
            return LabelsResponse(total=resp.total, skip=skip, limit=limit, labels=labels)
    except Exception:
        pass
    return _demo_labels(limit, skip)


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
    try:
        resp = await fda_search("/drug/ndc.json", search=search, limit=limit, skip=skip)
        if resp.results:
            products = [_parse_ndc(r) for r in resp.results]
            return NDCResponse(total=resp.total, skip=skip, limit=limit, products=products)
    except Exception:
        pass
    return _demo_ndc(limit, skip)


# ── Drug Shortages ──────────────────────────────────────────────

def _parse_shortage(raw: Dict[str, Any]) -> DrugShortage:
    # therapeutic_category is an array in the FDA response
    tc = raw.get("therapeutic_category")
    if isinstance(tc, str):
        tc = [tc]

    return DrugShortage(
        generic_name=raw.get("generic_name"),
        proprietary_name=raw.get("proprietary_name"),
        status=raw.get("status"),
        initial_posting_date=raw.get("initial_posting_date"),
        update_date=raw.get("update_date"),
        dosage_form=raw.get("dosage_form"),
        presentation=raw.get("presentation"),
        therapeutic_category=tc,
        company_name=raw.get("company_name"),
        shortage_reason=raw.get("shortage_reason"),
        resolved_note=raw.get("resolved_note"),
        availability=raw.get("availability"),
    )


async def get_drug_shortages(
    search: Optional[str] = None,
    limit: int = 10,
    skip: int = 0,
) -> ShortagesResponse:
    """Fetch drug shortage reports from openFDA."""
    try:
        resp = await fda_search("/drug/shortages.json", search=search, limit=limit, skip=skip)
        if resp.results:
            shortages = [_parse_shortage(r) for r in resp.results]
            return ShortagesResponse(total=resp.total, skip=skip, limit=limit, shortages=shortages)
    except Exception:
        pass
    return _demo_shortages(limit, skip)


async def count_drug_shortages(
    count_field: str = "status.exact",
    search: Optional[str] = None,
    limit: int = 10,
) -> FDACountResponse:
    """Count drug shortages by a field (default: status)."""
    return await fda_count("/drug/shortages.json", count_field, search=search, limit=limit)


# ═══════════════════════════════════════════════════════════════════
# Demo / fallback data — used when the live FDA API is unreachable
# ═══════════════════════════════════════════════════════════════════

_DEMO_DRUGS = [
    "METFORMIN HYDROCHLORIDE", "LISINOPRIL", "ATORVASTATIN CALCIUM",
    "AMLODIPINE BESYLATE", "OMEPRAZOLE", "LOSARTAN POTASSIUM",
    "GABAPENTIN", "HYDROCHLOROTHIAZIDE", "SERTRALINE HYDROCHLORIDE",
    "SIMVASTATIN", "MONTELUKAST SODIUM", "ESCITALOPRAM OXALATE",
    "LEVOTHYROXINE SODIUM", "PANTOPRAZOLE SODIUM", "ACETAMINOPHEN",
    "IBUPROFEN", "ASPIRIN", "AMOXICILLIN", "AZITHROMYCIN", "PREDNISONE",
]

_DEMO_REACTIONS = [
    "NAUSEA", "HEADACHE", "DIZZINESS", "FATIGUE", "DIARRHOEA",
    "VOMITING", "RASH", "PAIN", "DYSPNOEA", "ARTHRALGIA",
    "PRURITUS", "INSOMNIA", "COUGH", "ABDOMINAL PAIN", "PYREXIA",
    "WEIGHT INCREASED", "MYALGIA", "ANXIETY", "CONSTIPATION", "TREMOR",
]

_DEMO_COUNTRIES = ["US", "GB", "DE", "FR", "JP", "CA", "AU", "IT", "BR", "IN"]

_DEMO_FIRMS = [
    "Pfizer Inc", "Johnson & Johnson", "Novartis AG", "Roche Holding AG",
    "Merck & Co", "AbbVie Inc", "Sanofi SA", "GlaxoSmithKline plc",
    "AstraZeneca plc", "Bristol-Myers Squibb", "Eli Lilly", "Amgen Inc",
    "Teva Pharmaceutical", "Mylan NV", "Bayer AG",
]

_DEMO_RECALL_REASONS = [
    "Failed dissolution specifications",
    "Presence of foreign particulate matter",
    "cGMP deviations: equipment not properly cleaned between batches",
    "Microbial contamination detected in stability samples",
    "Incorrect expiration date printed on label",
    "Subpotent: out of specification results for assay at 12-month stability",
    "Cross-contamination with another product during manufacturing",
    "Labeling error: wrong dosage strength listed on carton",
    "Failed impurity/degradation specifications",
    "Presence of N-Nitrosodimethylamine (NDMA) above acceptable intake limit",
    "Defective container closure system: cracked vials observed",
    "Product may contain tablet fragments from a different product",
    "Failed content uniformity testing",
    "Superpotent: contains more active ingredient than specified",
    "Lack of assurance of sterility",
]


def _demo_adverse_events(limit: int, skip: int) -> AdverseEventsResponse:
    total = 2_847_312
    events = []
    for i in range(min(limit, 20)):
        idx = skip + i
        serious = random.random() < 0.6
        seriousness = []
        if serious:
            if random.random() < 0.05:
                seriousness.append("Death")
            if random.random() < 0.4:
                seriousness.append("Hospitalization")
            if random.random() < 0.1:
                seriousness.append("Life-Threatening")
            if random.random() < 0.15:
                seriousness.append("Disabling")
            if not seriousness:
                seriousness.append("Other Serious")

        n_drugs = random.randint(1, 4)
        n_reactions = random.randint(1, 5)
        year = random.randint(2019, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)

        events.append(AdverseEventSummary(
            report_id=f"{10000000 + idx}",
            receive_date=f"{year}{month:02d}{day:02d}",
            serious=serious,
            seriousness=seriousness,
            drugs=random.sample(_DEMO_DRUGS, min(n_drugs, len(_DEMO_DRUGS))),
            reactions=random.sample(_DEMO_REACTIONS, min(n_reactions, len(_DEMO_REACTIONS))),
            country=random.choice(_DEMO_COUNTRIES),
        ))

    return AdverseEventsResponse(total=total, skip=skip, limit=limit, events=events)


def _demo_recalls(limit: int, skip: int) -> RecallsResponse:
    total = 18_432
    recalls = []
    classifications = ["Class I", "Class II", "Class III"]
    statuses = ["Ongoing", "Completed", "Terminated"]
    states = ["NJ", "CA", "NY", "TX", "PA", "IL", "OH", "IN", "NC", "MA"]

    for i in range(min(limit, 20)):
        idx = skip + i
        year = random.randint(2020, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        cls = random.choices(classifications, weights=[15, 55, 30])[0]

        recalls.append(DrugRecall(
            recall_number=f"D-{2000 + idx}-{year}",
            reason_for_recall=random.choice(_DEMO_RECALL_REASONS),
            status=random.choice(statuses),
            distribution_pattern="Nationwide" if random.random() < 0.6 else f"{random.choice(states)} and surrounding states",
            product_description=f"{random.choice(_DEMO_DRUGS)} Tablets, {random.choice(['10mg', '25mg', '50mg', '100mg', '250mg', '500mg'])}",
            classification=cls,
            recalling_firm=random.choice(_DEMO_FIRMS),
            city=random.choice(["New York", "San Francisco", "Chicago", "Houston", "Philadelphia", "Basel", "Dublin"]),
            state=random.choice(states),
            country="US",
            voluntary_mandated="Voluntary" if random.random() < 0.85 else "FDA Mandated",
            report_date=f"{year}{month:02d}{day:02d}",
            recall_initiation_date=f"{year}{month:02d}{max(1, day - random.randint(1, 14)):02d}",
        ))

    return RecallsResponse(total=total, skip=skip, limit=limit, recalls=recalls)


def _demo_labels(limit: int, skip: int) -> LabelsResponse:
    total = 142_876
    labels = []
    manufacturers = _DEMO_FIRMS
    routes = [["ORAL"], ["INTRAVENOUS"], ["TOPICAL"], ["SUBCUTANEOUS"], ["INTRAMUSCULAR"], ["OPHTHALMIC"], ["INHALATION"]]
    types = ["HUMAN PRESCRIPTION DRUG", "HUMAN OTC DRUG"]

    label_data = [
        ("METFORMIN HCL", "Metformin Hydrochloride", "Treatment of type 2 diabetes mellitus to improve glycemic control in adults.",
         "Lactic acidosis is a rare but serious complication. Risk increases with renal impairment, hepatic insufficiency, and conditions causing hypoxemia."),
        ("LISINOPRIL", "Lisinopril", "Treatment of hypertension, heart failure, and to improve survival after myocardial infarction.",
         "Can cause fetal toxicity when administered to a pregnant woman. Angioedema of the face, extremities, lips, tongue may occur."),
        ("ATORVASTATIN", "Atorvastatin Calcium", "Adjunct to diet for reduction of elevated total-C, LDL-C, and triglycerides in patients with hyperlipidemia.",
         "Skeletal muscle effects (e.g., myopathy and rhabdomyolysis): Advise patients to promptly report unexplained muscle pain, tenderness, or weakness."),
        ("OMEPRAZOLE", "Omeprazole", "Short-term treatment of active duodenal ulcer, gastric ulcer, and gastroesophageal reflux disease (GERD).",
         "Long-term use may increase risk of fundic gland polyps, hypomagnesemia, and Clostridium difficile associated diarrhea."),
        ("GABAPENTIN", "Gabapentin", "Management of postherpetic neuralgia in adults. Adjunctive therapy for partial onset seizures.",
         "Antiepileptic drugs increase the risk of suicidal thoughts or behavior. Monitor for emergence of depression and suicidal thoughts."),
        ("AMLODIPINE", "Amlodipine Besylate", "Treatment of hypertension and coronary artery disease including chronic stable angina and vasospastic angina.",
         "Symptomatic hypotension is possible, particularly in patients with severe aortic stenosis. Increased angina or myocardial infarction possible upon initiation."),
        ("LOSARTAN", "Losartan Potassium", "Treatment of hypertension. Nephropathy in type 2 diabetic patients. Stroke risk reduction in hypertensive patients.",
         "Fetal toxicity: Can cause injury and death to the developing fetus. Discontinue as soon as pregnancy is detected. Hypotension may occur."),
        ("SERTRALINE", "Sertraline Hydrochloride", "Treatment of major depressive disorder, OCD, panic disorder, PTSD, social anxiety disorder, and PMDD.",
         "Clinical worsening and suicide risk: Monitor for worsening and emergence of suicidal thoughts and behaviors. Serotonin syndrome risk with concomitant serotonergic drugs."),
        ("SIMVASTATIN", "Simvastatin", "Treatment of hyperlipidemia and mixed dyslipidemia. Reduction of cardiovascular mortality and events.",
         "Myopathy/rhabdomyolysis risk increases with higher doses. Contraindicated with strong CYP3A4 inhibitors. Liver enzyme abnormalities may occur."),
        ("LEVOTHYROXINE", "Levothyroxine Sodium", "Treatment of hypothyroidism as a replacement or supplemental therapy. TSH suppression in thyroid cancer.",
         "Not for treatment of obesity. Doses beyond the range of daily hormonal requirements may produce serious or life-threatening manifestations of toxicity."),
    ]

    for i in range(min(limit, len(label_data))):
        brand, generic, indication, warning = label_data[i % len(label_data)]
        labels.append(DrugLabel(
            id=f"label-{skip + i + 1000}",
            effective_time=f"{random.randint(2018, 2025)}{random.randint(1,12):02d}{random.randint(1,28):02d}",
            purpose=[f"Treatment and management of conditions as described in indications"],
            indications_and_usage=[indication],
            warnings=[warning],
            dosage_and_administration=[f"See full prescribing information for complete dosage and administration instructions."],
            adverse_reactions=[f"Most common adverse reactions reported in clinical trials include nausea, headache, dizziness, and fatigue."],
            brand_name=brand,
            generic_name=generic,
            manufacturer_name=random.choice(manufacturers),
            product_type=random.choice(types),
            route=random.choice(routes),
        ))

    return LabelsResponse(total=total, skip=skip, limit=limit, labels=labels)


def _demo_ndc(limit: int, skip: int) -> NDCResponse:
    total = 298_134
    products = []
    dosage_forms = ["TABLET", "CAPSULE", "SOLUTION", "INJECTION", "CREAM", "POWDER", "SUSPENSION", "SYRUP", "PATCH"]
    categories = ["ANDA", "NDA", "BLA", "OTC MONOGRAPH FINAL"]

    for i in range(min(limit, 20)):
        idx = skip + i
        drug = _DEMO_DRUGS[idx % len(_DEMO_DRUGS)]
        products.append(DrugNDC(
            product_ndc=f"{random.randint(10000, 99999)}-{random.randint(100, 999)}",
            brand_name=drug.split()[0].title(),
            generic_name=drug,
            labeler_name=random.choice(_DEMO_FIRMS),
            dosage_form=random.choice(dosage_forms),
            route=[random.choice(["ORAL", "INTRAVENOUS", "TOPICAL", "SUBCUTANEOUS"])],
            product_type="HUMAN PRESCRIPTION DRUG" if random.random() < 0.7 else "HUMAN OTC DRUG",
            marketing_category=random.choice(categories),
            active_ingredients=[{"name": drug, "strength": f"{random.choice(['10', '25', '50', '100', '250', '500'])}mg"}],
            packaging=None,
            listing_expiration_date=f"{random.randint(2025, 2028)}{random.randint(1,12):02d}{random.randint(1,28):02d}",
        ))

    return NDCResponse(total=total, skip=skip, limit=limit, products=products)


def _demo_shortages(limit: int, skip: int) -> ShortagesResponse:
    total = 312
    shortages = []

    shortage_data = [
        ("Amoxicillin", "AMOXIL", "Oral Suspension", "Increased demand", "Anti-infectives"),
        ("Doxycycline Hyclate", "VIBRAMYCIN", "Capsule", "Manufacturing delay", "Anti-infectives"),
        ("Albuterol Sulfate", "VENTOLIN HFA", "Inhalation Aerosol", "Increased demand", "Respiratory"),
        ("Methotrexate Sodium", "TREXALL", "Injection", "Raw material shortage", "Oncology"),
        ("Cisplatin", "PLATINOL", "Injection", "Manufacturing delay", "Oncology"),
        ("Vincristine Sulfate", "ONCOVIN", "Injection", "Discontinued by manufacturer", "Oncology"),
        ("Lidocaine HCl", "XYLOCAINE", "Injection", "Increased demand", "Anesthesia"),
        ("Sodium Bicarbonate", None, "Injection", "Increased demand", "Electrolytes"),
        ("Epinephrine", "EPIPEN", "Auto-Injector", "Manufacturing delay", "Emergency"),
        ("Ondansetron HCl", "ZOFRAN", "Injection", "Raw material shortage", "Antiemetics"),
        ("Furosemide", "LASIX", "Injection", "Manufacturing delay", "Cardiovascular"),
        ("Heparin Sodium", None, "Injection", "Raw material shortage", "Anticoagulants"),
        ("Morphine Sulfate", None, "Injection", "Regulatory delay", "Pain Management"),
        ("Fentanyl Citrate", "SUBLIMAZE", "Injection", "Regulatory delay", "Pain Management"),
        ("Hydromorphone HCl", "DILAUDID", "Injection", "Manufacturing delay", "Pain Management"),
        ("Norepinephrine Bitartrate", "LEVOPHED", "Injection", "Increased demand", "Vasopressors"),
        ("Vasopressin", "VASOSTRICT", "Injection", "Manufacturing delay", "Vasopressors"),
        ("Propofol", "DIPRIVAN", "Injectable Emulsion", "Increased demand", "Anesthesia"),
        ("Carboplatin", "PARAPLATIN", "Injection", "Manufacturing delay", "Oncology"),
        ("Fluorouracil", "ADRUCIL", "Injection", "Raw material shortage", "Oncology"),
    ]

    statuses = ["Currently in Shortage", "Currently in Shortage", "Currently in Shortage", "Resolved"]

    for i in range(min(limit, len(shortage_data))):
        idx = (skip + i) % len(shortage_data)
        generic, brand, form, reason, category = shortage_data[idx]
        status = random.choice(statuses)
        year = random.randint(2023, 2025)
        month = random.randint(1, 12)

        resolved = None
        if status == "Resolved":
            resolved = "Product is now available from all manufacturers."

        shortages.append(DrugShortage(
            generic_name=generic,
            proprietary_name=brand,
            status=status,
            initial_posting_date=f"{year}-{month:02d}-{random.randint(1,28):02d}",
            update_date=f"2026-{random.randint(1,3):02d}-{random.randint(1,28):02d}",
            dosage_form=form,
            presentation=f"{generic} {form}" if generic else form,
            therapeutic_category=[category],
            company_name=random.choice(_DEMO_FIRMS),
            shortage_reason=reason,
            resolved_note=resolved,
            availability="Limited supply" if status == "Currently in Shortage" else "Available",
        ))

    return ShortagesResponse(total=total, skip=skip, limit=limit, shortages=shortages)


def _demo_count(endpoint: str, count_field: str, limit: int) -> FDACountResponse:
    """Generate demo count data based on the endpoint and field."""
    if "event" in endpoint:
        if "reaction" in count_field:
            items = [(r, random.randint(50000, 500000)) for r in _DEMO_REACTIONS[:limit]]
        elif "drug" in count_field or "medicinalproduct" in count_field:
            items = [(d, random.randint(30000, 400000)) for d in _DEMO_DRUGS[:limit]]
        elif "country" in count_field:
            items = [(c, random.randint(10000, 2000000)) for c in _DEMO_COUNTRIES[:limit]]
        else:
            items = [(f"Term {i+1}", random.randint(1000, 100000)) for i in range(min(limit, 10))]
    elif "shortages" in endpoint:
        if "status" in count_field:
            items = [("Currently in Shortage", 234), ("Resolved", 78)]
        elif "therapeutic_category" in count_field or "category" in count_field:
            items = [("Oncology", 48), ("Anti-infectives", 35), ("Pain Management", 31),
                     ("Cardiovascular", 28), ("Anesthesia", 22), ("Respiratory", 18),
                     ("Vasopressors", 15), ("Anticoagulants", 12), ("Electrolytes", 10), ("Emergency", 8)]
        else:
            items = [(f"Term {i+1}", random.randint(5, 50)) for i in range(min(limit, 10))]
    elif "enforcement" in endpoint:
        if "classification" in count_field:
            items = [("Class I", 3241), ("Class II", 10892), ("Class III", 4299)]
        elif "status" in count_field:
            items = [("Ongoing", 5432), ("Completed", 11234), ("Terminated", 1766)]
        else:
            items = [(f"Term {i+1}", random.randint(500, 5000)) for i in range(min(limit, 10))]
    else:
        items = [(f"Term {i+1}", random.randint(1000, 50000)) for i in range(min(limit, 10))]

    items.sort(key=lambda x: x[1], reverse=True)
    return FDACountResponse(
        meta=None,
        results=[FDACountItem(term=t, count=c) for t, c in items[:limit]],
    )
