"""Signed HTTPS delivery to the Base44 `ingest-ops-metrics` backend function.

Each request carries:
  X-Sync-Timestamp   unix seconds; the function rejects requests older than 5 minutes
  X-Sync-Signature   hex HMAC-SHA256 of "<timestamp>.<raw body>" with the shared secret
  Idempotency-Key    the batch id; re-sending a batch after a timeout is a no-op on Base44
"""

import hashlib
import hmac
import json
import logging
import random
import ssl
import time
import urllib.error
import urllib.request
import uuid
from typing import Dict, List, Optional

log = logging.getLogger("csv_sync.base44")

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class DeliveryError(RuntimeError):
    pass


def sign(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


class Base44Client:
    def __init__(self, endpoint: str, secret: str, timeout: float = 30.0,
                 max_retries: int = 5, ca_bundle: Optional[str] = None,
                 allow_insecure_http: bool = False):
        if not endpoint.lower().startswith("https://") and not allow_insecure_http:
            raise ValueError("Base44 endpoint must use HTTPS")
        self.endpoint = endpoint
        self.secret = secret
        self.timeout = timeout
        self.max_retries = max_retries
        self.ssl_context = ssl.create_default_context(cafile=ca_bundle)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    def send_batch(self, records: List[Dict], source_file: str, file_sha256: str,
                   batch_id: Optional[str] = None) -> Dict:
        batch_id = batch_id or str(uuid.uuid4())
        body = json.dumps({
            "batch_id": batch_id,
            "source_file": source_file,
            "file_sha256": file_sha256,
            "records": records,
        }, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        for attempt in range(1, self.max_retries + 1):
            # Fresh timestamp/signature per attempt so retries stay inside the replay window
            timestamp = str(int(time.time()))
            request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Sync-Timestamp": timestamp,
                "X-Sync-Signature": sign(self.secret, timestamp, body),
                "Idempotency-Key": batch_id,
                "User-Agent": "pharma-ops-csv-sync/1.0",
            })
            try:
                with urllib.request.urlopen(request, timeout=self.timeout,
                                            context=self.ssl_context) as resp:
                    payload = resp.read().decode("utf-8") or "{}"
                    return json.loads(payload)
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:500].decode("utf-8", "replace")
                if exc.code not in RETRYABLE_STATUS:
                    raise DeliveryError(f"Base44 rejected batch {batch_id}: HTTP {exc.code} {detail}")
                reason = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                reason = str(getattr(exc, "reason", exc))
            if attempt == self.max_retries:
                raise DeliveryError(f"Giving up on batch {batch_id} after {attempt} attempts: {reason}")
            delay = min(60.0, 2 ** attempt) + random.uniform(0, 1)
            log.warning("Batch %s attempt %d failed (%s); retrying in %.1fs",
                        batch_id, attempt, reason, delay)
            time.sleep(delay)
        raise DeliveryError("unreachable")
