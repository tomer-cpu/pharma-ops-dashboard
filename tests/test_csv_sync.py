import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from csv_sync.base44_client import Base44Client, DeliveryError, sign
from csv_sync.config import ConfigError, SyncConfig
from csv_sync.service import SyncService
from csv_sync.sources import LocalFolderSource
from csv_sync.state import SyncState
from csv_sync.validator import CSVValidator

SECRET = "s" * 40
HEADER = "date,site,product_line,batches_produced,batches_rejected,oee_score\n"


class FakeBase44(BaseHTTPRequestHandler):
    received = []
    fail_next = 0

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        ts = self.headers["X-Sync-Timestamp"]
        if not hmac.compare_digest(sign(SECRET, ts, body), self.headers["X-Sync-Signature"]):
            self.send_response(401)
            self.end_headers()
            return
        if FakeBase44.fail_next:
            FakeBase44.fail_next -= 1
            self.send_response(503)
            self.end_headers()
            return
        FakeBase44.received.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):
        pass


def make_cfg(folder, url, **overrides):
    cfg = SyncConfig(source_path=folder, state_db_path=":memory:", base44_endpoint=url,
                     base44_signing_secret=SECRET, allow_insecure_http=True,
                     file_settle_seconds=0, max_retries=2, request_timeout=5)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.v = CSVValidator(SyncConfig(allowed_sites=("Basel", "Dublin")))

    def test_valid_rows_are_typed_and_normalised(self):
        data = (HEADER + "2026-01-05,basel,Oncology,10,1,85.5\n").encode()
        result = self.v.validate(data, today=date(2026, 2, 1))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.records[0], {
            "date": "2026-01-05", "site": "Basel", "product_line": "Oncology",
            "batches_produced": 10, "batches_rejected": 1, "oee_score": 85.5})

    def test_row_level_errors(self):
        rows = [
            "2026-01-05,Basel,Onc,10,11,50",      # rejected > produced
            "2026-01-06,Paris,Onc,10,1,50",       # site not allowed
            "2026-01-07,Basel,Onc,-1,0,50",       # negative
            "2026-01-08,Basel,Onc,1.5,0,50",      # non-integer count
            "2026-01-09,Basel,Onc,10,1,150",      # percentage > 100
            "2027-01-01,Basel,Onc,10,1,50",       # future date
            "05/01/2026,Basel,Onc,10,1,50",       # dd/mm/yyyy accepted
            "2026-01-05,Basel,Onc,10,1,50",       # duplicate key of the line above
            "2026-01-10,=cmd(),Onc,10,1,50",      # formula injection
        ]
        result = self.v.validate((HEADER + "\n".join(rows)).encode(), today=date(2026, 2, 1))
        self.assertEqual(len(result.records), 1)
        self.assertEqual(len(result.errors), 8)

    def test_semicolon_delimited_cp1255_with_bom_header(self):
        text = "Date;Site;Product Line;Batches Produced\n2026-01-05;Dublin;אונקולוגיה;7\n"
        result = self.v.validate(text.encode("cp1255"), today=date(2026, 2, 1))
        self.assertEqual(result.errors, [])
        self.assertEqual(result.records[0]["product_line"], "אונקולוגיה")

    def test_missing_key_column_is_file_error(self):
        result = self.v.validate(b"date,site\n2026-01-05,Basel\n")
        self.assertIn("product_line", result.file_error)


class ConfigTests(unittest.TestCase):
    def test_https_and_secret_are_enforced(self):
        cfg = SyncConfig(source_path="x", base44_endpoint="http://example.com",
                         base44_signing_secret="short")
        with self.assertRaises(ConfigError) as ctx:
            cfg.validate()
        self.assertIn("https", str(ctx.exception))
        self.assertIn("32 characters", str(ctx.exception))

    def test_client_refuses_plain_http(self):
        with self.assertRaises(ValueError):
            Base44Client("http://example.com", SECRET)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeBase44)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/ingest"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeBase44.received = []
        FakeBase44.fail_next = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.service = SyncService(make_cfg(self.folder, self.url),
                                   source=LocalFolderSource(self.folder, "*.csv"),
                                   state=SyncState(":memory:"))

    def tearDown(self):
        self.service.state.close()
        self.tmp.cleanup()

    def write(self, name, body, mtime=None):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(HEADER + body)
        stamp = mtime or time.time() - 60
        os.utime(path, (stamp, stamp))

    def sent_keys(self):
        return [(r["date"], r["batches_produced"])
                for batch in FakeBase44.received for r in batch["records"]]

    def test_only_new_or_changed_rows_are_sent(self):
        self.write("a.csv", "2026-01-01,Basel,Onc,10,1,80\n2026-01-02,Basel,Onc,11,1,80\n")
        self.assertEqual(self.service.run_once().sent, 2)

        # Unchanged file: nothing read or sent
        report = self.service.run_once()
        self.assertEqual(report.files[0].status, "unchanged")

        # One row edited, one added
        self.write("a.csv", "2026-01-01,Basel,Onc,10,1,80\n2026-01-02,Basel,Onc,12,1,80\n"
                            "2026-01-03,Basel,Onc,9,0,80\n", mtime=time.time() - 30)
        report = self.service.run_once()
        self.assertEqual(report.sent, 2)
        self.assertEqual(report.files[0].skipped_unchanged, 1)
        self.assertEqual(self.sent_keys()[-2:], [("2026-01-02", 12), ("2026-01-03", 9)])

    def test_file_still_being_written_is_deferred(self):
        self.service.cfg.file_settle_seconds = 30
        self.write("a.csv", "2026-01-01,Basel,Onc,10,1,80\n", mtime=time.time())
        self.assertEqual(self.service.run_once().files[0].status, "settling")
        self.assertEqual(FakeBase44.received, [])

    def test_mostly_invalid_file_is_rejected_entirely(self):
        self.write("bad.csv", "2026-01-01,Basel,Onc,10,99,80\n2026-01-02,Basel,Onc,10,1,80\n")
        report = self.service.run_once()
        self.assertEqual(report.files[0].status, "rejected")
        self.assertEqual(FakeBase44.received, [])

    def test_transient_failure_is_retried_and_failure_is_resumed(self):
        FakeBase44.fail_next = 1
        self.write("a.csv", "2026-01-01,Basel,Onc,10,1,80\n")
        self.assertEqual(self.service.run_once().sent, 1)

        self.write("b.csv", "2026-01-05,Basel,Onc,10,1,80\n")
        FakeBase44.fail_next = 2  # exhausts max_retries=2
        report = self.service.run_once()
        self.assertTrue(report.failed)
        report = self.service.run_once()  # next cycle picks it up again
        self.assertEqual([f.status for f in report.files if f.name == "b.csv"], ["synced"])
        self.assertEqual(report.sent, 1)

    def test_wrong_secret_is_rejected_without_retry(self):
        client = Base44Client(self.url, "x" * 40, allow_insecure_http=True, max_retries=3)
        with self.assertRaises(DeliveryError) as ctx:
            client.send_batch([{"date": "2026-01-01"}], "a.csv", "0" * 64)
        self.assertIn("HTTP 401", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
