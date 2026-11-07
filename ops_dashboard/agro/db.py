"""SQLite storage for Agroshtil grower offers."""
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from ops_dashboard.config import BASE_DIR

AGRO_DB_PATH = os.environ.get(
    "AGRO_DB_PATH", os.path.join(BASE_DIR, "data", "agro_offers.db")
)

# Item statuses
NEW = "new"                      # imported, offer not sent yet
SENT = "sent"                    # offer sent, awaiting reply
INTERESTED = "interested"
NOT_INTERESTED = "not_interested"
STATUSES = (NEW, SENT, INTERESTED, NOT_INTERESTED)
ANSWERED = (INTERESTED, NOT_INTERESTED)

DEFAULT_TEMPLATE = (
    "שלום {name}, כאן אגרושתיל 🌱\n"
    "הכנו עבורך הצעה לשתילים לעונה הקרובה:\n"
    "{items}\n\n"
    "לצפייה בהצעה ולתשובה בלחיצה אחת:\n{link}\n\n"
    "אפשר גם להשיב להודעה זו: 1 = מעוניין/ת, 2 = לא מעוניין/ת"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL UNIQUE,          -- normalized, 972XXXXXXXXX
    token TEXT NOT NULL UNIQUE,          -- secret for the public offer page
    created_at TEXT NOT NULL,
    sent_at TEXT,
    send_channel TEXT,
    responded_at TEXT,
    last_reply TEXT,
    needs_review INTEGER DEFAULT 0,      -- inbound reply we could not interpret
    customer_note TEXT
);

CREATE TABLE IF NOT EXISTS offer_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    vegetable TEXT NOT NULL,
    variety TEXT DEFAULT '',
    quantity TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    sent_at TEXT,
    responded_at TEXT,
    response_source TEXT              -- web / whatsapp / sms / manual
);
CREATE INDEX IF NOT EXISTS idx_items_customer ON offer_items(customer_id);

CREATE TABLE IF NOT EXISTS agro_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    direction TEXT NOT NULL,          -- out / in
    channel TEXT NOT NULL,
    phone TEXT,
    body TEXT,
    status TEXT,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    os.makedirs(os.path.dirname(AGRO_DB_PATH), exist_ok=True)
    c = sqlite3.connect(AGRO_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_agro_db():
    with conn() as c:
        c.executescript(SCHEMA)


# ── Phones ──────────────────────────────────────────────────────

def normalize_phone(raw: str) -> str | None:
    """Return an Israeli mobile in international form (9725XXXXXXXX) or None."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("972"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    # Israeli mobile: 5X + 7 digits
    if len(digits) == 9 and digits.startswith("5"):
        return "972" + digits
    return None


def display_phone(phone: str) -> str:
    if phone and phone.startswith("972") and len(phone) == 12:
        local = "0" + phone[3:]
        return f"{local[:3]}-{local[3:]}"
    return phone or ""


# ── Settings ────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with conn() as c:
        row = c.execute("SELECT value FROM agro_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with conn() as c:
        c.execute(
            "INSERT INTO agro_settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_template() -> str:
    return get_setting("template", DEFAULT_TEMPLATE)


# ── Import ──────────────────────────────────────────────────────

def import_rows(rows: list[dict]) -> dict:
    """Insert rows of {name, phone, vegetable, variety?, quantity?, notes?}.

    Rows are grouped per customer by phone. A vegetable+variety already on
    the customer's list and not yet answered is skipped (no duplicates).
    """
    created_customers = added_items = skipped = 0
    errors = []
    ts = now()
    with conn() as c:
        for idx, r in enumerate(rows, start=1):
            name = (r.get("name") or "").strip()
            vegetable = (r.get("vegetable") or "").strip()
            phone = normalize_phone(r.get("phone"))
            if not phone:
                errors.append({"row": idx, "error": f"מספר נייד לא תקין: {r.get('phone') or '(ריק)'}"})
                continue
            if not vegetable:
                errors.append({"row": idx, "error": "חסר ירק / גידול"})
                continue
            cust = c.execute("SELECT id, name FROM customers WHERE phone=?", (phone,)).fetchone()
            if cust is None:
                if not name:
                    errors.append({"row": idx, "error": "חסר שם לקוח"})
                    continue
                cur = c.execute(
                    "INSERT INTO customers(name, phone, token, created_at) VALUES(?,?,?,?)",
                    (name, phone, secrets.token_urlsafe(12), ts),
                )
                cust_id = cur.lastrowid
                created_customers += 1
            else:
                cust_id = cust["id"]
                if name and name != cust["name"]:
                    c.execute("UPDATE customers SET name=? WHERE id=?", (name, cust_id))
            variety = (r.get("variety") or "").strip()
            dup = c.execute(
                "SELECT 1 FROM offer_items WHERE customer_id=? AND vegetable=? AND variety=? "
                "AND status IN ('new','sent')",
                (cust_id, vegetable, variety),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            c.execute(
                "INSERT INTO offer_items(customer_id, vegetable, variety, quantity, notes, status, created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (cust_id, vegetable, variety, (r.get("quantity") or "").strip(),
                 (r.get("notes") or "").strip(), NEW, ts),
            )
            added_items += 1
    return {
        "created_customers": created_customers,
        "added_items": added_items,
        "skipped_duplicates": skipped,
        "errors": errors,
    }


# ── Queries ─────────────────────────────────────────────────────

def _customer_dict(row, items) -> dict:
    d = dict(row)
    d["phone_display"] = display_phone(d["phone"])
    d["items"] = items
    counts = {s: 0 for s in STATUSES}
    for it in items:
        counts[it["status"]] += 1
    d["counts"] = counts
    if counts[NEW]:
        d["status"] = "not_sent"
    elif counts[SENT]:
        d["status"] = "partial" if (counts[INTERESTED] or counts[NOT_INTERESTED]) else "awaiting"
    elif counts[INTERESTED]:
        d["status"] = "interested"
    elif counts[NOT_INTERESTED]:
        d["status"] = "not_interested"
    else:
        d["status"] = "empty"
    return d


def list_customers() -> list[dict]:
    with conn() as c:
        customers = c.execute("SELECT * FROM customers ORDER BY created_at DESC, id DESC").fetchall()
        items = c.execute("SELECT * FROM offer_items ORDER BY id").fetchall()
    by_cust: dict[int, list] = {}
    for it in items:
        by_cust.setdefault(it["customer_id"], []).append(dict(it))
    return [_customer_dict(cu, by_cust.get(cu["id"], [])) for cu in customers]


def get_customer(customer_id: int = None, token: str = None, phone: str = None) -> dict | None:
    with conn() as c:
        if customer_id is not None:
            row = c.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        elif token is not None:
            row = c.execute("SELECT * FROM customers WHERE token=?", (token,)).fetchone()
        else:
            row = c.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
        if row is None:
            return None
        items = [dict(i) for i in c.execute(
            "SELECT * FROM offer_items WHERE customer_id=? ORDER BY id", (row["id"],)
        ).fetchall()]
    return _customer_dict(row, items)


def stats() -> dict:
    with conn() as c:
        customers = c.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        rows = c.execute("SELECT status, COUNT(*) n FROM offer_items GROUP BY status").fetchall()
        responded = c.execute(
            "SELECT COUNT(*) FROM customers WHERE responded_at IS NOT NULL").fetchone()[0]
        contacted = c.execute(
            "SELECT COUNT(*) FROM customers WHERE sent_at IS NOT NULL").fetchone()[0]
    by = {s: 0 for s in STATUSES}
    for r in rows:
        by[r["status"]] = r["n"]
    return {
        "customers": customers,
        "customers_contacted": contacted,
        "customers_responded": responded,
        "items": sum(by.values()),
        **by,
    }


# ── Mutations ───────────────────────────────────────────────────

def mark_sent(customer_id: int, channel: str):
    ts = now()
    with conn() as c:
        c.execute("UPDATE customers SET sent_at=?, send_channel=? WHERE id=?", (ts, channel, customer_id))
        c.execute(
            "UPDATE offer_items SET status=?, sent_at=? WHERE customer_id=? AND status=?",
            (SENT, ts, customer_id, NEW),
        )


def set_item_status(item_id: int, status: str, source: str) -> bool:
    if status not in STATUSES:
        raise ValueError("bad status")
    ts = now()
    responded = ts if status in ANSWERED else None
    with conn() as c:
        row = c.execute("SELECT customer_id FROM offer_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return False
        c.execute(
            "UPDATE offer_items SET status=?, responded_at=?, response_source=? WHERE id=?",
            (status, responded, source if responded else None, item_id),
        )
        if responded:
            c.execute("UPDATE customers SET responded_at=?, needs_review=0 WHERE id=?",
                      (ts, row["customer_id"]))
    return True


def record_response(customer_id: int, answers: dict[int, str], source: str,
                    note: str = None, reply_text: str = None) -> int:
    """answers: {item_id: 'interested'|'not_interested'}. Returns #items updated."""
    ts = now()
    updated = 0
    with conn() as c:
        valid = {r["id"] for r in c.execute(
            "SELECT id FROM offer_items WHERE customer_id=?", (customer_id,)).fetchall()}
        for item_id, status in answers.items():
            if item_id in valid and status in ANSWERED:
                c.execute(
                    "UPDATE offer_items SET status=?, responded_at=?, response_source=? WHERE id=?",
                    (status, ts, source, item_id),
                )
                updated += 1
        if updated or note:
            c.execute(
                "UPDATE customers SET responded_at=?, needs_review=0, "
                "customer_note=COALESCE(?, customer_note), last_reply=COALESCE(?, last_reply) WHERE id=?",
                (ts, note or None, reply_text or None, customer_id),
            )
        elif reply_text:
            c.execute("UPDATE customers SET last_reply=?, needs_review=1 WHERE id=?",
                      (reply_text, customer_id))
    return updated


def update_customer(customer_id: int, name: str = None, phone: str = None):
    with conn() as c:
        if name:
            c.execute("UPDATE customers SET name=? WHERE id=?", (name, customer_id))
        if phone:
            c.execute("UPDATE customers SET phone=? WHERE id=?", (phone, customer_id))


def delete_customer(customer_id: int):
    with conn() as c:
        c.execute("DELETE FROM customers WHERE id=?", (customer_id,))


def delete_item(item_id: int):
    with conn() as c:
        c.execute("DELETE FROM offer_items WHERE id=?", (item_id,))


def reset_all():
    with conn() as c:
        c.execute("DELETE FROM offer_items")
        c.execute("DELETE FROM message_log")
        c.execute("DELETE FROM customers")


def log_message(customer_id, direction, channel, phone, body, status):
    with conn() as c:
        c.execute(
            "INSERT INTO message_log(customer_id, direction, channel, phone, body, status, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (customer_id, direction, channel, phone, body, status, now()),
        )


def recent_messages(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT m.*, cu.name FROM message_log m LEFT JOIN customers cu ON cu.id=m.customer_id "
            "ORDER BY m.id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
