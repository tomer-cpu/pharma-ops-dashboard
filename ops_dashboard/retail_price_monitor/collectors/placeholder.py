"""Placeholder collectors for chains whose feed we have not yet implemented.

These exist so the runner has a first-class entry for every retailer in the
config. Each placeholder marks its run as ``skipped`` with a clear reason,
which surfaces in the dashboard alert stream and the collection log.

When a real adapter is added for a chain, simply replace the class in
``runner.DEFAULT_COLLECTORS``.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ops_dashboard.retail_price_monitor.collectors.base import (
    BaseCollector,
    CollectorResult,
)


class _SkippedCollector(BaseCollector):
    reason: str = "adapter not implemented"

    def collect(self, target_date: Optional[date] = None) -> CollectorResult:
        result = self._result(target_date)
        return result.finalize("skipped", self.reason)


class CarrefourCollector(_SkippedCollector):
    retailer_code = "carrefour"
    retailer_name = "קרפור"
    reason = (
        "Carrefour Israel transparency feed requires a chain-specific adapter "
        "(pending)."
    )


class VictoryCollector(_SkippedCollector):
    retailer_code = "victory"
    retailer_name = "ויקטורי"
    reason = (
        "Victory is published via Matrix Catalog; adapter pending."
    )


class MahsaneiCollector(_SkippedCollector):
    retailer_code = "mahsanei"
    retailer_name = "מחסני השוק"
    reason = (
        "Mahsanei HaShuk feed adapter pending."
    )
