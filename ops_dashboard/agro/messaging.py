"""Outbound offers and inbound reply parsing.

Channels
--------
* ``manual``   – no credentials needed. The dashboard opens a WhatsApp
                 click-to-chat link (wa.me) with the message pre-filled and the
                 user presses "send" in WhatsApp. Replies come back through the
                 personal offer link (one-click buttons) or are marked by hand.
* ``twilio``   – automatic SMS or WhatsApp through Twilio.
                 Env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM
                 (e.g. ``+972...`` for SMS or ``whatsapp:+14155238886``).
                 Inbound webhook: POST /api/agro/webhook/twilio
* ``whatsapp`` – automatic WhatsApp through the Meta WhatsApp Cloud API.
                 Env: WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID,
                 WHATSAPP_VERIFY_TOKEN (webhook verification).
                 Inbound webhook: GET/POST /api/agro/webhook/whatsapp
                 Note: Meta only allows free-form text inside a 24h customer
                 service window; cold outreach needs an approved template
                 (WHATSAPP_TEMPLATE_NAME, with body params {{1}}=name,
                 {{2}}=items, {{3}}=link).
"""
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from ops_dashboard.agro import db


# ── Message composition ────────────────────────────────────────

def item_label(it: dict) -> str:
    parts = [it["vegetable"]]
    if it.get("variety"):
        parts.append(f"זן {it['variety']}")
    label = " ".join(parts)
    if it.get("quantity"):
        label += f" ({it['quantity']})"
    return label


def compose_message(customer: dict, link: str, template: str = None) -> str:
    template = template or db.get_template()
    items = [it for it in customer["items"] if it["status"] in (db.NEW, db.SENT)]
    items_text = "\n".join(f"• שתילי {item_label(it)}" for it in items)
    first_name = customer["name"].split()[0] if customer["name"] else ""
    return (template
            .replace("{name}", customer["name"])
            .replace("{first_name}", first_name)
            .replace("{items}", items_text)
            .replace("{link}", link))


def wa_link(phone: str, text: str) -> str:
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"


# ── Providers ──────────────────────────────────────────────────

def available_channels() -> dict:
    return {
        "manual": True,
        "twilio": all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM")),
        "whatsapp": all(os.environ.get(k) for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID")),
    }


class SendError(Exception):
    pass


def _post(url: str, data: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise SendError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SendError(str(e.reason))


def send_twilio(phone: str, body: str) -> str:
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    sender = os.environ["TWILIO_FROM"]
    to = f"+{phone}"
    if sender.startswith("whatsapp:"):
        to = f"whatsapp:{to}"
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    res = _post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode(),
        {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
    )
    return res.get("sid", "sent")


def send_whatsapp_cloud(phone: str, body: str, customer: dict, items_text: str, link: str) -> str:
    token = os.environ["WHATSAPP_TOKEN"]
    number_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
    template = os.environ.get("WHATSAPP_TEMPLATE_NAME")
    if template:
        payload = {
            "messaging_product": "whatsapp", "to": phone, "type": "template",
            "template": {
                "name": template,
                "language": {"code": os.environ.get("WHATSAPP_TEMPLATE_LANG", "he")},
                "components": [{"type": "body", "parameters": [
                    {"type": "text", "text": customer["name"]},
                    {"type": "text", "text": items_text.replace("\n", " | ")},
                    {"type": "text", "text": link},
                ]}],
            },
        }
    else:
        payload = {"messaging_product": "whatsapp", "to": phone, "type": "text",
                   "text": {"body": body, "preview_url": True}}
    res = _post(
        f"https://graph.facebook.com/v20.0/{number_id}/messages",
        json.dumps(payload).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    msgs = res.get("messages") or [{}]
    return msgs[0].get("id", "sent")


def send_offer(customer: dict, link: str, channel: str) -> dict:
    """Send (or prepare) the offer. Marks the customer's new items as sent."""
    body = compose_message(customer, link)
    if channel == "manual":
        # The browser opens WhatsApp; we record it as sent when the link is produced.
        db.mark_sent(customer["id"], "manual")
        db.log_message(customer["id"], "out", "manual", customer["phone"], body, "opened")
        return {"channel": "manual", "wa_link": wa_link(customer["phone"], body), "message": body}

    if not available_channels().get(channel):
        raise SendError(f"ערוץ {channel} לא מוגדר בשרת (חסרים משתני סביבה)")
    try:
        if channel == "twilio":
            ref = send_twilio(customer["phone"], body)
        elif channel == "whatsapp":
            items = [it for it in customer["items"] if it["status"] in (db.NEW, db.SENT)]
            items_text = ", ".join(item_label(it) for it in items)
            ref = send_whatsapp_cloud(customer["phone"], body, customer, items_text, link)
        else:
            raise SendError(f"ערוץ לא מוכר: {channel}")
    except SendError as e:
        db.log_message(customer["id"], "out", channel, customer["phone"], body, f"error: {e}")
        raise
    db.mark_sent(customer["id"], channel)
    db.log_message(customer["id"], "out", channel, customer["phone"], body, f"sent {ref}")
    return {"channel": channel, "ref": ref, "message": body}


# ── Inbound reply parsing ──────────────────────────────────────

_NEG_WORDS = {"לא", "2", "no", "לאא", "❌", "👎"}
_POS_WORDS = {"כן", "1", "yes", "מעוניין", "מעוניינת", "מעוניינים", "בטח", "אשמח", "סגור",
              "👍", "✅", "ok", "אוקי"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.;:!?()\"'\-]+", text.strip().lower()) if t]


def parse_reply(text: str, items: list[dict]) -> dict[int, str]:
    """Map a free-text reply onto pending items.

    * "2" / "לא" / "לא מעוניין"      → all pending items not interested
    * "1" / "כן" / "מעוניין"          → all pending items interested
    * mentions specific vegetables    → those items interested (rest untouched,
                                        or not interested when the reply says "רק")
    Returns {} when the reply cannot be interpreted (left for manual review).
    """
    pending = [it for it in items if it["status"] == db.SENT] or \
              [it for it in items if it["status"] in db.ANSWERED]
    if not text or not pending:
        return {}
    toks = _tokens(text)
    low = text.lower()
    mentioned = [it for it in pending if it["vegetable"] and it["vegetable"].lower() in low]
    negative = any(t in _NEG_WORDS for t in toks)
    positive = any(t in _POS_WORDS for t in toks)

    if mentioned and not negative:
        answers = {it["id"]: db.INTERESTED for it in mentioned}
        if "רק" in toks or "only" in toks:   # "רק עגבניה" → the rest are a no
            answers.update({it["id"]: db.NOT_INTERESTED for it in pending if it["id"] not in answers})
        return answers
    if mentioned and negative:
        # e.g. "עגבניה כן, מלפפון לא" is ambiguous – leave for a human
        return {}
    if negative:
        return {it["id"]: db.NOT_INTERESTED for it in pending}
    if positive:
        return {it["id"]: db.INTERESTED for it in pending}
    return {}


def handle_inbound(phone_raw: str, text: str, channel: str) -> dict:
    phone = db.normalize_phone(phone_raw)
    customer = db.get_customer(phone=phone) if phone else None
    db.log_message(customer["id"] if customer else None, "in", channel, phone or phone_raw, text,
                   "matched" if customer else "unknown sender")
    if not customer:
        return {"matched": False}
    answers = parse_reply(text, customer["items"])
    updated = db.record_response(customer["id"], answers, channel, reply_text=text)
    return {"matched": True, "customer_id": customer["id"], "updated": updated,
            "understood": bool(answers)}
