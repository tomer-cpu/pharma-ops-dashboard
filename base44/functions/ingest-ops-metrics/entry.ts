// Receives signed batches from the csv_sync service and upserts them into OpsDailyMetric.
//
// Required secret (Base44 app settings -> Secrets):
//   CSV_SYNC_SIGNING_SECRET  same value as BASE44_SIGNING_SECRET on the sync service
import { createClientFromRequest } from "npm:@base44/sdk";

const MAX_SKEW_SECONDS = 300;
const MAX_BODY_BYTES = 5 * 1024 * 1024;
const MAX_RECORDS = 1000;
const LOOKUP_CONCURRENCY = 20;

const KEY_FIELDS = ["date", "site", "product_line"];
const NUMERIC_FIELDS = [
  "batches_produced", "batches_rejected", "compliance_audits", "compliance_passed",
  "rft_batches", "total_deviations", "critical_deviations", "capa_open",
  "investigations", "audit_findings",
  "supply_units", "demand_units", "otif_orders_total", "otif_orders_met",
  "sla_total_orders", "sla_met_orders",
  "scheduled_batches", "completed_scheduled", "production_output_units",
  "backorders", "total_orders", "forecast_demand", "actual_demand",
  "waste_units", "total_produced_units", "rework_units",
  "theoretical_yield", "actual_yield", "capa_closed_days", "investigation_days",
  "lead_time_days", "response_time_hours", "order_cycle_days",
  "available_capacity", "used_capacity",
  "cogs_amount", "revenue_amount", "inventory_value", "carrying_cost_rate",
  "cost_per_batch_amount", "copq_amount", "scrap_cost_amount",
  "planned_cost", "actual_cost",
  "oee_score", "downtime_hours", "available_hours", "changeover_hours",
  "line_output", "line_capacity",
  "supplier_risk", "stockout_risk_score", "batch_failure_prob", "service_risk",
];

const encoder = new TextEncoder();

async function hmacHex(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(message));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function sanitizeRecord(raw: Record<string, unknown>): Record<string, unknown> | string {
  const out: Record<string, unknown> = {};
  for (const field of KEY_FIELDS) {
    const value = raw[field];
    if (typeof value !== "string" || value.length === 0 || value.length > 100) {
      return `invalid ${field}`;
    }
    out[field] = value;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(out.date as string)) return "invalid date";
  for (const field of NUMERIC_FIELDS) {
    if (!(field in raw)) continue;
    const value = raw[field];
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return `invalid ${field}`;
    }
    out[field] = value;
  }
  out.record_key = `${out.date}|${out.site}|${out.product_line}`;
  return out;
}

async function mapLimited<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return results;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }
  const secret = Deno.env.get("CSV_SYNC_SIGNING_SECRET");
  if (!secret) {
    return Response.json({ error: "Server not configured" }, { status: 500 });
  }

  const contentLength = Number(req.headers.get("content-length") ?? "0");
  if (contentLength > MAX_BODY_BYTES) {
    return Response.json({ error: "Payload too large" }, { status: 413 });
  }
  const body = await req.text();
  if (encoder.encode(body).length > MAX_BODY_BYTES) {
    return Response.json({ error: "Payload too large" }, { status: 413 });
  }

  // Authenticate: HMAC over "<timestamp>.<body>", timestamp within +-5 minutes
  const timestamp = req.headers.get("x-sync-timestamp") ?? "";
  const signature = (req.headers.get("x-sync-signature") ?? "").toLowerCase();
  const ts = Number(timestamp);
  if (!/^\d+$/.test(timestamp) || Math.abs(Date.now() / 1000 - ts) > MAX_SKEW_SECONDS) {
    return Response.json({ error: "Stale or missing timestamp" }, { status: 401 });
  }
  const expected = await hmacHex(secret, `${timestamp}.${body}`);
  if (!timingSafeEqual(expected, signature)) {
    return Response.json({ error: "Invalid signature" }, { status: 401 });
  }

  let payload: { batch_id?: string; source_file?: string; file_sha256?: string; records?: unknown[] };
  try {
    payload = JSON.parse(body);
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const { batch_id, source_file, file_sha256, records } = payload;
  if (typeof batch_id !== "string" || !/^[A-Za-z0-9-]{8,64}$/.test(batch_id)
      || req.headers.get("idempotency-key") !== batch_id) {
    return Response.json({ error: "Invalid batch_id" }, { status: 400 });
  }
  if (!Array.isArray(records) || records.length === 0 || records.length > MAX_RECORDS) {
    return Response.json({ error: `records must be 1-${MAX_RECORDS} items` }, { status: 400 });
  }

  const clean: Record<string, unknown>[] = [];
  for (let i = 0; i < records.length; i++) {
    const result = sanitizeRecord((records[i] ?? {}) as Record<string, unknown>);
    if (typeof result === "string") {
      return Response.json({ error: `record ${i}: ${result}` }, { status: 422 });
    }
    clean.push({ ...result, source_file: String(source_file ?? "").slice(0, 255), batch_id });
  }

  try {
    const base44 = createClientFromRequest(req);
    const db = base44.asServiceRole.entities;

    // Idempotency: a batch already applied is acknowledged without writing again
    const existingBatch = await db.SyncBatch.filter({ batch_id }, undefined, 1);
    if (existingBatch.length > 0) {
      return Response.json({ status: "duplicate", batch_id });
    }

    const existing = await mapLimited(clean, LOOKUP_CONCURRENCY, (rec) =>
      db.OpsDailyMetric.filter({ record_key: rec.record_key }, undefined, 1)
    );
    const toCreate = clean.filter((_, i) => existing[i].length === 0);
    const toUpdate = clean
      .map((rec, i) => (existing[i].length > 0 ? { ...rec, id: existing[i][0].id } : null))
      .filter((rec) => rec !== null);

    if (toCreate.length) await db.OpsDailyMetric.bulkCreate(toCreate);
    if (toUpdate.length) await db.OpsDailyMetric.bulkUpdate(toUpdate);

    await db.SyncBatch.create({
      batch_id,
      source_file: String(source_file ?? "").slice(0, 255),
      file_sha256: typeof file_sha256 === "string" ? file_sha256.slice(0, 64) : "",
      created_count: toCreate.length,
      updated_count: toUpdate.length,
      received_at: new Date().toISOString(),
    });

    return Response.json({
      status: "ok", batch_id, created: toCreate.length, updated: toUpdate.length,
    });
  } catch (error) {
    console.error("ingest-ops-metrics failed", batch_id, error);
    return Response.json({ error: "Ingest failed" }, { status: 500 });
  }
});
