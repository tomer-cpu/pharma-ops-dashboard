"""SQLite storage for the retail price monitor.

The schema is append-only for observations so that daily snapshots accumulate
into a history table, matching the spec requirement that no historical data is
overwritten.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable

from ops_dashboard.retail_price_monitor.config import RPM_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS rpm_products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT    NOT NULL,
    name_en         TEXT,
    brand           TEXT    NOT NULL,
    manufacturer    TEXT    NOT NULL,
    barcode         TEXT    UNIQUE,
    size_value      REAL,
    size_unit       TEXT,
    category        TEXT,
    subcategory     TEXT,
    package_type    TEXT,
    internal_id     TEXT,
    base_price      REAL,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rpm_products_barcode  ON rpm_products(barcode);
CREATE INDEX IF NOT EXISTS idx_rpm_products_category ON rpm_products(category);

CREATE TABLE IF NOT EXISTS rpm_retailers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT    UNIQUE NOT NULL,
    name_he         TEXT    NOT NULL,
    name_en         TEXT    NOT NULL,
    source_url      TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    last_collected  TEXT,
    last_status     TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rpm_price_observations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_date    TEXT    NOT NULL,
    observation_time    TEXT    NOT NULL,
    retailer_id         INTEGER NOT NULL,
    branch              TEXT,
    region              TEXT,
    source_product_name TEXT    NOT NULL,
    product_id          INTEGER,
    regular_price       REAL,
    promo_price         REAL,
    promo_type          TEXT,
    unit_price          REAL,
    in_stock            INTEGER,
    product_url         TEXT,
    match_confidence    TEXT NOT NULL DEFAULT 'High',
    notes               TEXT,
    collected_at        TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (retailer_id) REFERENCES rpm_retailers(id),
    FOREIGN KEY (product_id)  REFERENCES rpm_products(id)
);

CREATE INDEX IF NOT EXISTS idx_rpm_obs_date        ON rpm_price_observations(observation_date);
CREATE INDEX IF NOT EXISTS idx_rpm_obs_product     ON rpm_price_observations(product_id);
CREATE INDEX IF NOT EXISTS idx_rpm_obs_retailer    ON rpm_price_observations(retailer_id);
CREATE INDEX IF NOT EXISTS idx_rpm_obs_date_prod   ON rpm_price_observations(observation_date, product_id);

CREATE TABLE IF NOT EXISTS rpm_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_date   TEXT    NOT NULL,
    alert_type   TEXT    NOT NULL,  -- price_jump, price_drop, promo_start, promo_end,
                                    --   cheapest, most_expensive, missing_product, new_product,
                                    --   collection_failure, high_volatility
    severity     TEXT    NOT NULL,  -- info / warning / critical
    product_id   INTEGER,
    retailer_id  INTEGER,
    title        TEXT    NOT NULL,
    description  TEXT,
    pct_change   REAL,
    metric_value REAL,
    created_at   TEXT    DEFAULT (datetime('now')),
    FOREIGN KEY (product_id)  REFERENCES rpm_products(id),
    FOREIGN KEY (retailer_id) REFERENCES rpm_retailers(id)
);

CREATE INDEX IF NOT EXISTS idx_rpm_alerts_date ON rpm_alerts(alert_date);
CREATE INDEX IF NOT EXISTS idx_rpm_alerts_type ON rpm_alerts(alert_type);

CREATE TABLE IF NOT EXISTS rpm_collection_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date            TEXT    NOT NULL,
    retailer_id         INTEGER NOT NULL,
    status              TEXT    NOT NULL,  -- ok / partial / failed / skipped
    products_collected  INTEGER DEFAULT 0,
    error_message       TEXT,
    started_at          TEXT,
    finished_at         TEXT,
    FOREIGN KEY (retailer_id) REFERENCES rpm_retailers(id)
);

CREATE INDEX IF NOT EXISTS idx_rpm_log_date ON rpm_collection_log(run_date);
"""


# ── Connection helpers ────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(RPM_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(RPM_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def connection_scope():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection_scope() as conn:
        conn.executescript(SCHEMA)


def has_observations() -> bool:
    with connection_scope() as conn:
        row = conn.execute("SELECT COUNT(*) FROM rpm_price_observations").fetchone()
    return bool(row and row[0] > 0)


# ── Insert helpers ────────────────────────────────────────────────────────

def upsert_retailer(conn: sqlite3.Connection, retailer: dict) -> int:
    existing = conn.execute(
        "SELECT id FROM rpm_retailers WHERE code = ?", (retailer["code"],)
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO rpm_retailers (code, name_he, name_en, source_url)
        VALUES (?, ?, ?, ?)
        """,
        (retailer["code"], retailer["name_he"], retailer["name_en"], retailer.get("source_url")),
    )
    return cur.lastrowid


def upsert_product(conn: sqlite3.Connection, product: dict, brand: str, manufacturer: str) -> int:
    existing = conn.execute(
        "SELECT id FROM rpm_products WHERE barcode = ?", (product["barcode"],)
    ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO rpm_products (
            canonical_name, name_en, brand, manufacturer, barcode,
            size_value, size_unit, category, subcategory, package_type, base_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            product["name_he"],
            product.get("name_en"),
            brand,
            manufacturer,
            product["barcode"],
            product.get("size_value"),
            product.get("size_unit"),
            product.get("category"),
            product.get("subcategory"),
            product.get("package"),
            product.get("base_price"),
        ),
    )
    return cur.lastrowid


def insert_observations(conn: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO rpm_price_observations (
            observation_date, observation_time, retailer_id, branch, region,
            source_product_name, product_id, regular_price, promo_price, promo_type,
            unit_price, in_stock, product_url, match_confidence, notes, collected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_collection_log(conn: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO rpm_collection_log (
            run_date, retailer_id, status, products_collected,
            error_message, started_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def insert_alerts(conn: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO rpm_alerts (
            alert_date, alert_type, severity, product_id, retailer_id,
            title, description, pct_change, metric_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def clear_alerts_for_date(conn: sqlite3.Connection, date: str) -> None:
    conn.execute("DELETE FROM rpm_alerts WHERE alert_date = ?", (date,))


def update_retailer_status(
    conn: sqlite3.Connection, retailer_id: int, collected_at: str, status: str
) -> None:
    conn.execute(
        "UPDATE rpm_retailers SET last_collected = ?, last_status = ? WHERE id = ?",
        (collected_at, status, retailer_id),
    )
