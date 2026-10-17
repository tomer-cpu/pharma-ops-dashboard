"""Poll -> detect changes -> validate -> deliver loop."""

import hashlib
import logging
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from csv_sync.base44_client import Base44Client, DeliveryError
from csv_sync.config import SyncConfig
from csv_sync.sources import FileSource, RemoteFile, build_source
from csv_sync.state import SyncState, content_hash
from csv_sync.validator import CSVValidator

log = logging.getLogger("csv_sync")

DONE_STATUSES = ("synced", "rejected")
MAX_LOGGED_ERRORS = 20


@dataclass
class FileOutcome:
    name: str
    status: str            # synced | rejected | failed | unchanged | settling
    sent: int = 0
    skipped_unchanged: int = 0
    invalid: int = 0
    detail: str = ""


@dataclass
class RunReport:
    files: List[FileOutcome] = field(default_factory=list)

    @property
    def sent(self) -> int:
        return sum(f.sent for f in self.files)

    @property
    def failed(self) -> bool:
        return any(f.status == "failed" for f in self.files)


def batch_id_for(file_sha256: str, chunk: List[Dict]) -> str:
    """Deterministic id, so a batch re-sent after a crash is deduplicated by Base44."""
    digest = hashlib.sha256(file_sha256.encode("ascii"))
    for record in chunk:
        digest.update(content_hash(record).encode("ascii"))
    return digest.hexdigest()[:32]


class SyncService:
    def __init__(self, cfg: SyncConfig, source: Optional[FileSource] = None,
                 client: Optional[Base44Client] = None, state: Optional[SyncState] = None):
        self.cfg = cfg
        self.source = source or build_source(cfg)
        self.client = client or Base44Client(
            cfg.base44_endpoint, cfg.base44_signing_secret, cfg.request_timeout,
            cfg.max_retries, cfg.base44_ca_bundle, cfg.allow_insecure_http)
        self.state = state or SyncState(cfg.state_db_path)
        self.validator = CSVValidator(cfg)
        self._stop = threading.Event()

    def run_once(self) -> RunReport:
        report = RunReport()
        for remote in self.source.list_files():
            try:
                outcome = self._process(remote)
            except Exception as exc:  # keep going with the other files
                log.exception("Unexpected error processing %s", remote.name)
                outcome = FileOutcome(remote.name, "failed", detail=str(exc))
            if outcome.status not in ("unchanged", "settling"):
                log.info("%s: %s (sent=%d unchanged=%d invalid=%d) %s", outcome.name,
                         outcome.status, outcome.sent, outcome.skipped_unchanged,
                         outcome.invalid, outcome.detail)
            report.files.append(outcome)
        return report

    def _process(self, remote: RemoteFile) -> FileOutcome:
        prev = self.state.get_file(remote.name)
        if (prev is not None and prev["status"] in DONE_STATUSES
                and prev["size"] == remote.size and prev["mtime"] == remote.mtime):
            return FileOutcome(remote.name, "unchanged")

        if time.time() - remote.mtime < self.cfg.file_settle_seconds:
            return FileOutcome(remote.name, "settling", detail="file modified recently")

        data = self.source.read_bytes(remote.name, self.cfg.max_file_bytes)
        sha256 = hashlib.sha256(data).hexdigest()
        if prev is not None and prev["status"] in DONE_STATUSES and prev["sha256"] == sha256:
            # Touched but identical content
            self.state.mark_file(remote.name, remote.size, remote.mtime, sha256,
                                 prev["status"], prev["detail"])
            return FileOutcome(remote.name, "unchanged")

        result = self.validator.validate(data)
        for warning in result.warnings:
            log.warning("%s: %s", remote.name, warning)
        for err in result.errors[:MAX_LOGGED_ERRORS]:
            log.warning("%s line %d: %s", remote.name, err.line, err.message)
        if len(result.errors) > MAX_LOGGED_ERRORS:
            log.warning("%s: %d more invalid rows not shown", remote.name,
                        len(result.errors) - MAX_LOGGED_ERRORS)

        invalid = len(result.errors)
        if result.file_error or result.invalid_ratio > self.cfg.max_invalid_ratio:
            detail = result.file_error or (
                f"{invalid}/{result.total_rows} rows invalid "
                f"(limit {self.cfg.max_invalid_ratio:.0%}); file not sent")
            self.state.mark_file(remote.name, remote.size, remote.mtime, sha256, "rejected", detail)
            return FileOutcome(remote.name, "rejected", invalid=invalid, detail=detail)

        changed = self.state.changed_records(result.records)
        outcome = FileOutcome(remote.name, "synced", invalid=invalid,
                              skipped_unchanged=len(result.records) - len(changed))
        for start in range(0, len(changed), self.cfg.batch_size):
            chunk = changed[start:start + self.cfg.batch_size]
            try:
                self.client.send_batch(chunk, remote.name, sha256, batch_id_for(sha256, chunk))
            except DeliveryError as exc:
                # File is not marked done, so the remaining records are retried next cycle;
                # chunks already delivered are recorded and will not be re-sent.
                self.state.mark_file(remote.name, remote.size, remote.mtime, "", "failed", str(exc))
                outcome.status, outcome.detail = "failed", str(exc)
                return outcome
            self.state.mark_sent(chunk, remote.name)
            outcome.sent += len(chunk)

        outcome.detail = f"{invalid} invalid rows skipped" if invalid else ""
        self.state.mark_file(remote.name, remote.size, remote.mtime, sha256, "synced",
                             f"sent={outcome.sent} unchanged={outcome.skipped_unchanged} "
                             f"invalid={invalid}")
        return outcome

    def run_forever(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self._stop.set())
            except ValueError:  # not on the main thread
                pass
        log.info("CSV sync started; polling every %ds", self.cfg.poll_interval_seconds)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Sync cycle failed (source unreachable?)")
            self._stop.wait(self.cfg.poll_interval_seconds)
        self.state.close()
        log.info("CSV sync stopped")
