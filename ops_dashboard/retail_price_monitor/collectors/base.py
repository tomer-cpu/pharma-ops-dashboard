"""Shared data types and the base class for retail-price collectors."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


DEFAULT_TIMEOUT = 20
DEFAULT_USER_AGENT = "LeimanSchlisselPriceMonitor/1.0 (+https://example.com/contact)"


# ── data types ────────────────────────────────────────────────────────

@dataclass
class RawObservation:
    """Normalised row emitted by a collector before it hits the database."""

    retailer_code: str
    observation_date: str
    barcode: str
    source_product_name: str
    manufacturer_name: Optional[str] = None
    regular_price: Optional[float] = None
    promo_price: Optional[float] = None
    promo_type: Optional[str] = None
    unit_price: Optional[float] = None
    size_value: Optional[float] = None
    size_unit: Optional[str] = None
    in_stock: Optional[bool] = None
    branch: Optional[str] = None
    region: Optional[str] = None
    product_url: Optional[str] = None
    match_confidence: str = "High"
    notes: Optional[str] = None
    collected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CollectorResult:
    retailer_code: str
    status: str  # 'ok' | 'partial' | 'failed' | 'skipped'
    observations: List[RawObservation] = field(default_factory=list)
    error_message: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def finalize(self, status: str, error: Optional[str] = None) -> "CollectorResult":
        self.status = status
        self.error_message = error
        self.finished_at = datetime.utcnow().isoformat()
        return self


# ── base class ────────────────────────────────────────────────────────

class BaseCollector:
    """Abstract base class. Subclasses implement :meth:`collect`."""

    retailer_code: str = ""
    retailer_name: str = ""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_USER_AGENT):
        self.timeout = timeout
        self.user_agent = user_agent

    # Subclasses override these -----------------------------------

    def collect(self, target_date: Optional[date] = None) -> CollectorResult:
        raise NotImplementedError

    # Shared HTTP helper ------------------------------------------

    def http_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
        merged = {"User-Agent": self.user_agent}
        if headers:
            merged.update(headers)
        req = urllib.request.Request(url, headers=merged)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    # Utility for subclasses --------------------------------------

    def _result(self, target_date: Optional[date]) -> CollectorResult:
        iso = (target_date or date.today()).isoformat()
        return CollectorResult(
            retailer_code=self.retailer_code,
            status="pending",
            observations=[],
            meta={"observation_date": iso},
        )

    @staticmethod
    def safe_run(collector: "BaseCollector", target_date: Optional[date]) -> CollectorResult:
        """Run a collector and convert any exception into a ``failed`` result."""

        try:
            result = collector.collect(target_date)
            if result.status == "pending":
                result.finalize("ok" if result.observations else "partial")
            return result
        except urllib.error.URLError as exc:
            result = collector._result(target_date)
            return result.finalize("failed", f"Network error: {exc.reason}")
        except Exception as exc:  # pragma: no cover - defensive path
            result = collector._result(target_date)
            return result.finalize("failed", f"{type(exc).__name__}: {exc}")
