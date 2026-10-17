"""Parse and validate CSV exports against the daily_metrics contract."""

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

from csv_sync.config import SyncConfig
from csv_sync.schema import (ALL_FIELDS, INTEGER_FIELDS, KEY_FIELDS, NUMERIC_FIELDS,
                             PART_OF_WHOLE, PERCENT_FIELDS)

# Windows exports are often UTF-8 with BOM, or a legacy code page
ENCODINGS = ("utf-8-sig", "cp1255", "cp1252")
MAX_TEXT_LEN = 100
# Cells starting with these could be executed as formulas if the data is re-exported to Excel
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class ValidationResult:
    records: List[Dict] = field(default_factory=list)
    errors: List[RowError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    total_rows: int = 0
    file_error: Optional[str] = None

    @property
    def invalid_ratio(self) -> float:
        return (self.total_rows - len(self.records)) / self.total_rows if self.total_rows else 0.0


def decode(data: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("File is not in a supported text encoding")


def normalize_header(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _parse_date(raw: str, formats) -> date:
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{raw}'")


def _parse_number(raw: str, as_int: bool):
    cleaned = raw.replace(",", "").replace(" ", "")
    value = float(cleaned)
    if math.isnan(value) or math.isinf(value):
        raise ValueError("not a finite number")
    if as_int:
        if value != int(value):
            raise ValueError("must be a whole number")
        return int(value)
    return value


class CSVValidator:
    def __init__(self, cfg: SyncConfig):
        self.cfg = cfg
        self.allowed_sites = {s.lower(): s for s in cfg.allowed_sites}
        self.allowed_product_lines = {p.lower(): p for p in cfg.allowed_product_lines}

    def validate(self, data: bytes, today: Optional[date] = None) -> ValidationResult:
        result = ValidationResult()
        today = today or date.today()
        try:
            text = decode(data)
        except ValueError as exc:
            result.file_error = str(exc)
            return result

        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)

        try:
            header = [normalize_header(h) for h in next(reader)]
        except StopIteration:
            result.file_error = "File is empty"
            return result

        missing = [k for k in KEY_FIELDS if k not in header]
        if missing:
            result.file_error = f"Missing required columns: {', '.join(missing)}"
            return result
        if len(set(header)) != len(header):
            result.file_error = "Duplicate column names in header"
            return result
        unknown = [h for h in header if h and h not in ALL_FIELDS]
        if unknown:
            result.warnings.append(f"Ignoring unknown columns: {', '.join(unknown)}")

        seen_keys: Dict[tuple, int] = {}
        for line_no, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue
            result.total_rows += 1
            if len(row) != len(header):
                result.errors.append(RowError(line_no, f"expected {len(header)} columns, got {len(row)}"))
                continue
            raw = {h: cell.strip() for h, cell in zip(header, row) if h in ALL_FIELDS}
            record, problems = self._validate_row(raw, today)
            if not problems:
                key = (record["date"], record["site"], record["product_line"])
                if key in seen_keys:
                    problems.append(f"duplicate of line {seen_keys[key]} for {'/'.join(key)}")
                else:
                    seen_keys[key] = line_no
            if problems:
                result.errors.append(RowError(line_no, "; ".join(problems)))
            else:
                result.records.append(record)
        return result

    def _validate_row(self, raw: Dict[str, str], today: date):
        problems: List[str] = []
        record: Dict = {}

        try:
            d = _parse_date(raw.get("date", ""), self.cfg.date_formats)
            if d > today:
                problems.append(f"date {d.isoformat()} is in the future")
            record["date"] = d.isoformat()
        except ValueError as exc:
            problems.append(f"date: {exc}")

        for name, allowed in (("site", self.allowed_sites),
                              ("product_line", self.allowed_product_lines)):
            value = raw.get(name, "")
            if not value:
                problems.append(f"{name} is empty")
            elif len(value) > MAX_TEXT_LEN:
                problems.append(f"{name} is longer than {MAX_TEXT_LEN} characters")
            elif value.startswith(FORMULA_PREFIXES):
                problems.append(f"{name} starts with a formula character")
            elif allowed and value.lower() not in allowed:
                problems.append(f"{name} '{value}' is not in the allowed list")
            else:
                record[name] = allowed.get(value.lower(), value) if allowed else value

        for name in NUMERIC_FIELDS:
            value = raw.get(name)
            if value is None or value == "":
                continue
            try:
                number = _parse_number(value, name in INTEGER_FIELDS)
            except ValueError as exc:
                problems.append(f"{name}: '{value}' {exc}")
                continue
            if number < 0:
                problems.append(f"{name} must not be negative")
            elif name in PERCENT_FIELDS and number > 100:
                problems.append(f"{name} must be between 0 and 100")
            record[name] = number

        for part, whole in PART_OF_WHOLE:
            if part in record and whole in record and record[part] > record[whole]:
                problems.append(f"{part} ({record[part]}) exceeds {whole} ({record[whole]})")

        return record, problems
