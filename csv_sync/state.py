"""Local SQLite state used for change detection.

* files     - fingerprint (size, mtime, sha256) of every file already processed
* records   - content hash of every record last delivered, keyed by date|site|product_line
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    name TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    record_key TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    source_file TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
"""


def record_key(record: Dict) -> str:
    return f"{record['date']}|{record['site']}|{record['product_line']}"


def content_hash(record: Dict) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SyncState:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get_file(self, name: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM files WHERE name = ?", (name,)).fetchone()

    def mark_file(self, name: str, size: int, mtime: float, sha256: str,
                  status: str, detail: str = "") -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO files (name, size, mtime, sha256, status, detail, processed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                     sha256=excluded.sha256, status=excluded.status, detail=excluded.detail,
                     processed_at=excluded.processed_at""",
                (name, size, mtime, sha256, status, detail, _now()))

    def changed_records(self, records: Iterable[Dict]):
        """Return only records that are new or whose content differs from what was last sent."""
        changed = []
        for rec in records:
            key = record_key(rec)
            row = self.conn.execute(
                "SELECT content_hash FROM records WHERE record_key = ?", (key,)).fetchone()
            if row is None or row["content_hash"] != content_hash(rec):
                changed.append(rec)
        return changed

    def mark_sent(self, records: Iterable[Dict], source_file: str) -> None:
        now = _now()
        with self.conn:
            self.conn.executemany(
                """INSERT INTO records (record_key, content_hash, source_file, sent_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(record_key) DO UPDATE SET content_hash=excluded.content_hash,
                     source_file=excluded.source_file, sent_at=excluded.sent_at""",
                [(record_key(r), content_hash(r), source_file, now) for r in records])

    def summary(self) -> Dict:
        files = {row["status"]: row["n"] for row in self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM files GROUP BY status")}
        records = self.conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        return {"files": files, "records_tracked": records}
