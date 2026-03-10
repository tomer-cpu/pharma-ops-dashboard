from enum import Enum


class MetricCategory(str, Enum):
    QUALITY = "quality"
    SERVICE = "service"
    COST = "cost"


class TimeRange(str, Enum):
    LAST_7D = "7d"
    LAST_30D = "30d"
    LAST_90D = "90d"
    LAST_365D = "365d"


class AggregationPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
