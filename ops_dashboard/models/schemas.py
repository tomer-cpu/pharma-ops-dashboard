from pydantic import BaseModel
from typing import List, Optional


class MetricFilters(BaseModel):
    site: Optional[str] = None
    product_line: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    time_range: Optional[str] = "30d"


class KPIValue(BaseModel):
    metric_name: str
    display_name: str
    current_value: float
    previous_value: float
    unit: str
    trend: str  # "up", "down", "flat"
    trend_is_good: bool
    target: Optional[float] = None
    target_direction: Optional[str] = None  # ">=" or "<="


class TimeSeriesPoint(BaseModel):
    timestamp: str
    value: float


class TimeSeriesData(BaseModel):
    metric_name: str
    data_points: List[TimeSeriesPoint]
    unit: str


class SiteBreakdown(BaseModel):
    site: str
    value: float


class CategoryBreakdown(BaseModel):
    category: str
    value: float


class Alert(BaseModel):
    metric_name: str
    display_name: str
    category: str
    current_value: float
    target_value: float
    target_direction: str
    severity: str  # "warning", "critical"
    message: str


class TargetUpdate(BaseModel):
    metric_name: str
    value: float
    weight: Optional[float] = None
    enabled: Optional[bool] = None


class TargetConfig(BaseModel):
    metric_name: str
    display_name: str
    value: float
    direction: str
    unit: str
    category: str
    weight: float
    enabled: bool = True


class MetricScore(BaseModel):
    metric_name: str
    display_name: str
    category: str
    current_value: float
    target_value: float
    target_direction: str
    unit: str
    score: float  # 0-100 normalized score
    weight: float  # user-defined weight
    weighted_contribution: float  # score * weight / total_weight
    status: str  # "on_target", "warning", "critical"


class SiteCreate(BaseModel):
    name: str
    volume_mult: float = 1.0
    cost_mult: float = 1.0
    quality_offset: float = 0.0


class SiteUpdate(BaseModel):
    volume_mult: Optional[float] = None
    cost_mult: Optional[float] = None
    quality_offset: Optional[float] = None


class SiteConfig(BaseModel):
    name: str
    volume_mult: float
    cost_mult: float
    quality_offset: float
    active: bool = True


class ProductLineCreate(BaseModel):
    name: str


class ProductLineConfig(BaseModel):
    name: str
    active: bool = True


class GenerateDataRequest(BaseModel):
    sites: Optional[List[str]] = None
    product_lines: Optional[List[str]] = None
