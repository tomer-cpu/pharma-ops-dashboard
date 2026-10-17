"""Settings for the CSV -> Base44 sync service, read from environment variables.

Secrets (Base44 signing secret, SMB password) are only ever read from the
environment and are never logged or written to the state database.
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: str = "") -> Tuple[str, ...]:
    raw = _env(name, default) or ""
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def load_dotenv(path: str) -> None:
    """Minimal KEY=VALUE loader so the service can run without extra packages.
    Existing environment variables win over the file."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class ConfigError(ValueError):
    pass


@dataclass
class SyncConfig:
    # Source: "local" (a folder or UNC path such as \\fileserver\exports) or "smb"
    source_type: str = "local"
    source_path: str = ""
    file_pattern: str = "*.csv"
    smb_server: Optional[str] = None
    smb_share: Optional[str] = None
    smb_username: Optional[str] = None
    smb_password: Optional[str] = field(default=None, repr=False)
    smb_require_encryption: bool = True

    # Change detection
    state_db_path: str = "csv_sync_state.db"
    # A file must be unchanged for this long before it is read (still being written otherwise)
    file_settle_seconds: int = 30

    # Validation
    allowed_sites: Tuple[str, ...] = ()
    allowed_product_lines: Tuple[str, ...] = ()
    date_formats: Tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y")
    # Reject the whole file if more than this fraction of rows is invalid
    max_invalid_ratio: float = 0.10
    max_file_bytes: int = 50 * 1024 * 1024

    # Base44 delivery
    base44_endpoint: str = ""
    base44_signing_secret: Optional[str] = field(default=None, repr=False)
    base44_ca_bundle: Optional[str] = None
    batch_size: int = 200
    request_timeout: float = 30.0
    max_retries: int = 5
    allow_insecure_http: bool = False  # tests / local development only

    poll_interval_seconds: int = 300

    @classmethod
    def from_env(cls) -> "SyncConfig":
        return cls(
            source_type=_env("CSV_SYNC_SOURCE_TYPE", "local").lower(),
            source_path=_env("CSV_SYNC_SOURCE_PATH", ""),
            file_pattern=_env("CSV_SYNC_FILE_PATTERN", "*.csv"),
            smb_server=_env("CSV_SYNC_SMB_SERVER"),
            smb_share=_env("CSV_SYNC_SMB_SHARE"),
            smb_username=_env("CSV_SYNC_SMB_USERNAME"),
            smb_password=_env("CSV_SYNC_SMB_PASSWORD"),
            smb_require_encryption=_env_bool("CSV_SYNC_SMB_REQUIRE_ENCRYPTION", True),
            state_db_path=_env("CSV_SYNC_STATE_DB", "csv_sync_state.db"),
            file_settle_seconds=_env_int("CSV_SYNC_FILE_SETTLE_SECONDS", 30),
            allowed_sites=_env_list("CSV_SYNC_ALLOWED_SITES"),
            allowed_product_lines=_env_list("CSV_SYNC_ALLOWED_PRODUCT_LINES"),
            date_formats=_env_list("CSV_SYNC_DATE_FORMATS", "%Y-%m-%d,%d/%m/%Y,%d.%m.%Y"),
            max_invalid_ratio=_env_float("CSV_SYNC_MAX_INVALID_RATIO", 0.10),
            max_file_bytes=_env_int("CSV_SYNC_MAX_FILE_BYTES", 50 * 1024 * 1024),
            base44_endpoint=_env("BASE44_INGEST_URL", ""),
            base44_signing_secret=_env("BASE44_SIGNING_SECRET"),
            base44_ca_bundle=_env("BASE44_CA_BUNDLE"),
            batch_size=_env_int("CSV_SYNC_BATCH_SIZE", 200),
            request_timeout=_env_float("CSV_SYNC_REQUEST_TIMEOUT", 30.0),
            max_retries=_env_int("CSV_SYNC_MAX_RETRIES", 5),
            allow_insecure_http=_env_bool("CSV_SYNC_ALLOW_INSECURE_HTTP", False),
            poll_interval_seconds=_env_int("CSV_SYNC_POLL_INTERVAL", 300),
        )

    def validate(self) -> None:
        errors = []
        if self.source_type not in ("local", "smb"):
            errors.append("CSV_SYNC_SOURCE_TYPE must be 'local' or 'smb'")
        if self.source_type == "local" and not self.source_path:
            errors.append("CSV_SYNC_SOURCE_PATH is required for the local source")
        if self.source_type == "smb":
            for name, value in (("CSV_SYNC_SMB_SERVER", self.smb_server),
                                ("CSV_SYNC_SMB_SHARE", self.smb_share),
                                ("CSV_SYNC_SMB_USERNAME", self.smb_username),
                                ("CSV_SYNC_SMB_PASSWORD", self.smb_password)):
                if not value:
                    errors.append(f"{name} is required for the smb source")
        if not self.base44_endpoint:
            errors.append("BASE44_INGEST_URL is required")
        elif not self.base44_endpoint.lower().startswith("https://") and not self.allow_insecure_http:
            errors.append("BASE44_INGEST_URL must use https://")
        if not self.base44_signing_secret or len(self.base44_signing_secret) < 32:
            errors.append("BASE44_SIGNING_SECRET is required and must be at least 32 characters")
        if not 0 <= self.max_invalid_ratio <= 1:
            errors.append("CSV_SYNC_MAX_INVALID_RATIO must be between 0 and 1")
        if self.batch_size < 1:
            errors.append("CSV_SYNC_BATCH_SIZE must be positive")
        if errors:
            raise ConfigError("; ".join(errors))
