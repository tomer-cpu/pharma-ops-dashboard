"""HTTP API for Agroshtil grower offers."""
import base64
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import urllib.parse
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from ops_dashboard.agro import db, messaging


# ── Admin auth (optional) ──────────────────────────────────────
# Set AGRO_ADMIN_PASSWORD to protect the admin page and API with HTTP Basic
# auth (any username). The customer offer page and webhooks stay public.

def require_admin(request: Request):
    password = os.environ.get("AGRO_ADMIN_PASSWORD")
    if not password:
        return
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            _, _, given = base64.b64decode(header[6:]).decode().partition(":")
        except Exception:
            given = ""
        if secrets.compare_digest(given, password):
            return
    raise HTTPException(401, "נדרשת סיסמה", headers={"WWW-Authenticate": 'Basic realm="agroshtil"'})


admin = APIRouter(dependencies=[Depends(require_admin)])
public = APIRouter()


def base_url(request: Request) -> str:
    return os.environ.get("AGRO_PUBLIC_BASE_URL", str(request.base_url)).rstrip("/")


def offer_link(request: Request, customer: dict) -> str:
    return f"{base_url(request)}/o/{customer['token']}"


# ── Schemas ────────────────────────────────────────────────────

class ImportRow(BaseModel):
    name: str = ""
    phone: str = ""
    vegetable: str = ""
    variety: str = ""
    quantity: str = ""
    notes: str = ""


class ImportRequest(BaseModel):
    rows: list[ImportRow]


class SendRequest(BaseModel):
    customer_ids: Optional[list[int]] = None   # None = all customers with unsent items
    channel: Literal["manual", "twilio", "whatsapp"] = "manual"
    resend: bool = False                       # include customers already contacted & awaiting


class ItemStatus(BaseModel):
    status: Literal["new", "sent", "interested", "not_interested"]


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class SettingsUpdate(BaseModel):
    template: str = Field(min_length=5)


class PublicAnswer(BaseModel):
    answers: dict[int, Literal["interested", "not_interested"]]
    note: str = ""


# ── Admin endpoints ────────────────────────────────────────────

@admin.get("/customers")
def customers(request: Request):
    rows = db.list_customers()
    for r in rows:
        r["offer_link"] = offer_link(request, r)
    return rows


@admin.get("/stats")
def get_stats():
    return db.stats()


@admin.post("/import")
def import_rows(req: ImportRequest):
    if not req.rows:
        raise HTTPException(400, "לא התקבלו שורות")
    return db.import_rows([r.model_dump() for r in req.rows])


@admin.get("/settings")
def get_settings():
    return {
        "template": db.get_template(),
        "default_template": db.DEFAULT_TEMPLATE,
        "channels": messaging.available_channels(),
        "admin_protected": bool(os.environ.get("AGRO_ADMIN_PASSWORD")),
    }


@admin.put("/settings")
def put_settings(req: SettingsUpdate):
    if "{link}" not in req.template:
        raise HTTPException(400, "התבנית חייבת לכלול {link} כדי שהלקוח יוכל להשיב")
    db.set_setting("template", req.template)
    return {"status": "ok"}


@admin.get("/customers/{customer_id}/preview")
def preview(customer_id: int, request: Request):
    cu = db.get_customer(customer_id=customer_id)
    if not cu:
        raise HTTPException(404, "לקוח לא נמצא")
    link = offer_link(request, cu)
    msg = messaging.compose_message(cu, link)
    return {"message": msg, "wa_link": messaging.wa_link(cu["phone"], msg), "offer_link": link}


@admin.post("/send")
def send(req: SendRequest, request: Request):
    targets = db.list_customers()
    if req.customer_ids is not None:
        wanted = set(req.customer_ids)
        targets = [c for c in targets if c["id"] in wanted]
    eligible = []
    for c in targets:
        if c["counts"]["new"] or (req.resend and c["counts"]["sent"]):
            eligible.append(c)
    results = []
    for c in eligible:
        try:
            r = messaging.send_offer(c, offer_link(request, c), req.channel)
            results.append({"customer_id": c["id"], "name": c["name"], "ok": True, **r})
        except messaging.SendError as e:
            results.append({"customer_id": c["id"], "name": c["name"], "ok": False, "error": str(e)})
    return {"requested": len(targets), "processed": len(results), "results": results}


@admin.put("/items/{item_id}")
def put_item(item_id: int, req: ItemStatus):
    if not db.set_item_status(item_id, req.status, "manual"):
        raise HTTPException(404, "שורה לא נמצאה")
    return {"status": "ok"}


@admin.delete("/items/{item_id}")
def del_item(item_id: int):
    db.delete_item(item_id)
    return {"status": "ok"}


@admin.put("/customers/{customer_id}")
def put_customer(customer_id: int, req: CustomerUpdate):
    phone = None
    if req.phone:
        phone = db.normalize_phone(req.phone)
        if not phone:
            raise HTTPException(400, "מספר נייד לא תקין")
    db.update_customer(customer_id, (req.name or "").strip() or None, phone)
    return {"status": "ok"}


@admin.delete("/customers/{customer_id}")
def del_customer(customer_id: int):
    db.delete_customer(customer_id)
    return {"status": "ok"}


@admin.delete("/all")
def del_all():
    db.reset_all()
    return {"status": "ok"}


@admin.get("/messages")
def messages(limit: int = 50):
    return db.recent_messages(limit)


STATUS_HE = {"new": "טרם נשלח", "sent": "ממתין לתשובה",
             "interested": "מעוניין", "not_interested": "לא מעוניין"}


@admin.get("/export.csv")
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["שם לקוח", "נייד", "ירק", "זן", "כמות", "הערות", "סטטוס",
                "נשלח", "נענה", "מקור תשובה", "הערת לקוח"])
    for c in db.list_customers():
        for it in c["items"]:
            w.writerow([c["name"], c["phone_display"], it["vegetable"], it["variety"], it["quantity"],
                        it["notes"], STATUS_HE.get(it["status"], it["status"]), it["sent_at"] or "",
                        it["responded_at"] or "", it["response_source"] or "", c["customer_note"] or ""])
    data = "﻿" + out.getvalue()   # BOM so Excel opens Hebrew correctly
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="agroshtil_offers.csv"'})


# ── Public: customer offer page API ────────────────────────────

@public.get("/public/{token}")
def public_offer(token: str):
    cu = db.get_customer(token=token)
    if not cu:
        raise HTTPException(404, "ההצעה לא נמצאה")
    items = [
        {k: it[k] for k in ("id", "vegetable", "variety", "quantity", "notes", "status")}
        for it in cu["items"] if it["status"] != db.NEW
    ]
    return {"name": cu["name"], "items": items, "note": cu["customer_note"] or ""}


@public.post("/public/{token}")
def public_answer(token: str, req: PublicAnswer):
    cu = db.get_customer(token=token)
    if not cu:
        raise HTTPException(404, "ההצעה לא נמצאה")
    answers = {int(k): v for k, v in req.answers.items()}
    updated = db.record_response(cu["id"], answers, "web", note=req.note.strip()[:1000] or None)
    db.log_message(cu["id"], "in", "web", cu["phone"],
                   json.dumps({"answers": answers, "note": req.note}, ensure_ascii=False), "web form")
    return {"status": "ok", "updated": updated}


# ── Webhooks for inbound SMS / WhatsApp replies ────────────────

def _twilio_signature_ok(request: Request, params: dict) -> bool:
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not token or not os.environ.get("AGRO_PUBLIC_BASE_URL"):
        return True   # cannot reconstruct the public URL reliably – skip validation
    url = f"{base_url(request)}{request.url.path}"
    payload = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, request.headers.get("x-twilio-signature", ""))


@public.post("/webhook/twilio")
async def twilio_webhook(request: Request):
    raw = (await request.body()).decode()
    params = {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
    if not _twilio_signature_ok(request, params):
        raise HTTPException(403, "bad signature")
    sender = params.get("From", "").replace("whatsapp:", "")
    channel = "whatsapp" if params.get("From", "").startswith("whatsapp:") else "sms"
    res = messaging.handle_inbound(sender, params.get("Body", ""), channel)
    reply = ""
    if res.get("matched"):
        reply = "תודה! קיבלנו את תשובתך 🌱 אגרושתיל" if res.get("understood") else \
                "תודה! נציג אגרושתיל יחזור אליך בהקדם 🌱"
    twiml = '<?xml version="1.0" encoding="UTF-8"?><Response>'
    if reply:
        twiml += f"<Message>{reply}</Message>"
    twiml += "</Response>"
    return Response(twiml, media_type="application/xml")


@public.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") and \
            q.get("hub.verify_token") == os.environ.get("WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verification failed")


@public.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    raw = await request.body()
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if secret:
        expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
            raise HTTPException(403, "bad signature")
    data = json.loads(raw or b"{}")
    handled = 0
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                text = ""
                if msg.get("type") == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg.get("type") == "button":
                    text = msg.get("button", {}).get("text", "")
                elif msg.get("type") == "interactive":
                    inter = msg.get("interactive", {})
                    text = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
                messaging.handle_inbound(msg.get("from", ""), text, "whatsapp")
                handled += 1
    return {"status": "ok", "handled": handled}
