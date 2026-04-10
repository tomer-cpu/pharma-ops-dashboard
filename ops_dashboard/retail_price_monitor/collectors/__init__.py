"""Collectors for the Israeli "Price Transparency" law data feeds.

Every retail chain operating in Israel is obliged by law to publish daily
``PriceFull`` and ``PromoFull`` XML files describing every SKU it sells. The
feeds are hosted on well-known public endpoints — the chains do NOT require us
to scrape any consumer-facing website. This package contains one adapter per
chain that downloads the latest daily files, filters them for Leiman Schlissel
products, and normalises the output into ``RawObservation`` rows.

Design goals:

* No aggressive scraping — only documented transparency-law endpoints.
* Every collector is defensive: network or parsing errors are reported via
  the collection log and never crash the runner.
* Parsing is completely separated from fetching so that it can be unit
  tested against synthetic XML files without touching the network.
"""

from ops_dashboard.retail_price_monitor.collectors.base import (
    BaseCollector,
    CollectorResult,
    RawObservation,
)
from ops_dashboard.retail_price_monitor.collectors.runner import (
    DEFAULT_COLLECTORS,
    run_collectors,
)

__all__ = [
    "BaseCollector",
    "CollectorResult",
    "RawObservation",
    "DEFAULT_COLLECTORS",
    "run_collectors",
]
