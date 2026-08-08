#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
building_sales.py — how many units in a building have actually been sold.

Pulls registered real-estate transactions for one address from the Israeli
government's מידע נדל"ן service (nadlan.gov.il), deduplicates them into distinct
apartments, separates first-hand (מכירת קבלן) from resale, and — when given the
number of units approved in the building permit — computes absorption, remaining
inventory, sales pace and a sell-out forecast.

stdlib only. Emits JSON on stdout (and to --out).

  python3 building_sales.py --address "הרצל 45 רעננה" --permit-units 48 --out deals.json

Design note: the nadlan API is undocumented and its field names have shifted over
time. Every field is read through FIELD_ALIASES and anything unrecognised is
reported back in the JSON under "unmapped_fields" — so a schema change surfaces
as a visible diagnostic instead of a silently wrong number.
"""

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime

BASE = "https://www.nadlan.gov.il/Nadlan.REST/Main"
QUERY_URL = f"{BASE}/GetDataByQuery"
DEALS_URL = f"{BASE}/GetAssestAndDeals"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# --------------------------------------------------------------------------
# Field aliases: canonical name -> API keys seen in the wild (lowercased).
# Add here when --raw reveals a key we do not yet map.
# --------------------------------------------------------------------------
FIELD_ALIASES = {
    "date":     ["dealdatetime", "dealdate", "deal_date"],
    "amount":   ["dealamount", "deal_amount", "price"],
    "rooms":    ["assetroomnum", "roomnum", "rooms"],
    "floor":    ["floorno", "floor", "floornumber"],
    "area":     ["dealnature", "assetarea", "area", "sqm"],
    "kind":     ["dealnaturedescription", "assettype", "dealnaturedesc"],
    "address":  ["fulladress", "fulladdress", "displayadress", "displayaddress", "address"],
    "gush":     ["gush", "gushhelka", "gush_helka"],
    "project":  ["projectname", "newprojecttext", "project"],
    "yearbuilt": ["yearbuilt", "buildingyear", "yearbuilding"],
    "floors":   ["buildingfloors", "totalfloors"],
    "key":      ["keyvalue", "uniq_id", "uniqid", "id"],
    "trend":    ["trend_format", "trendformat"],
}

# Deal-kind strings that mean "developer selling a brand-new apartment".
FIRST_HAND_MARKERS = ("מכירת קבלן", "דירה חדשה", "קבלן", "חדשה מקבלן")
# Deal kinds that are not a residential unit in this building.
NON_RESIDENTIAL_MARKERS = ("חניה", "מחסן", "מסחר", "חנות", "משרד", "קרקע",
                           "מגרש", "תעשיה", "תעשייה", "אחסנה", "מבנה חקלאי")


# ------------------------------- HTTP -------------------------------------

def _ssl_ctx():
    """nadlan.gov.il rejects some default cipher suites; widen them."""
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def post_json(url, payload, retries=4, timeout=45):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
        "User-Agent": UA,
        "Origin": "https://www.nadlan.gov.il",
        "Referer": "https://www.nadlan.gov.il/",
    }
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
                raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else None
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, ssl.SSLError, json.JSONDecodeError, OSError) as e:
            last = e
            # The service rate-limits aggressively. Back off rather than hammer.
            time.sleep(2 ** attempt)
    raise RuntimeError(f"request to {url} failed after {retries} attempts: {last}")


# ---------------------------- normalisation --------------------------------

def lower_keys(d):
    return {str(k).lower(): v for k, v in d.items()} if isinstance(d, dict) else {}


def pick(rec_lc, canonical):
    for alias in FIELD_ALIASES.get(canonical, []):
        if alias in rec_lc and rec_lc[alias] not in (None, "", "null"):
            return rec_lc[alias]
    return None


def parse_amount(v):
    if v is None:
        return None
    s = re.sub(r"[^\d.]", "", str(v))
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_number(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    m = re.search(r"-?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        f = float(m.group(0))
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def parse_date(v):
    if v is None:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s[:len(fmt) + 6], fmt) if "%f" in fmt \
                else datetime.strptime(s[:len(fmt)], fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def house_number_of(address):
    """Extract the house number from a Hebrew address string."""
    if not address:
        return None
    m = re.search(r"(?<!\d)(\d{1,4})(?:\s*[א-ת])?(?=\s*,|\s|$)", str(address))
    return m.group(1) if m else None


def subparcel_of(gush_str):
    """GUSH looks like '6638-45-12' → (gush, helka, tat-helka). The tat-helka IS the flat."""
    if not gush_str:
        return None, None, None
    parts = [p.strip() for p in re.split(r"[-/]", str(gush_str)) if p.strip()]
    g = parts[0] if len(parts) > 0 else None
    h = parts[1] if len(parts) > 1 else None
    t = parts[2] if len(parts) > 2 else None
    return g, h, t


def normalise(rec, unmapped):
    lc = lower_keys(rec)
    known = {a for aliases in FIELD_ALIASES.values() for a in aliases}
    for k in lc:
        if k not in known:
            unmapped[k] += 1

    gush_raw = pick(lc, "gush")
    g, h, tat = subparcel_of(gush_raw)
    addr = pick(lc, "address")
    dt = parse_date(pick(lc, "date"))
    kind = (pick(lc, "kind") or "").strip()
    area = parse_number(pick(lc, "area"))
    amount = parse_amount(pick(lc, "amount"))

    return {
        "date": dt.strftime("%Y-%m-%d") if dt else None,
        "_dt": dt,
        "amount": amount,
        "rooms": parse_number(pick(lc, "rooms")),
        "floor": parse_number(pick(lc, "floor")),
        "area_sqm": area,
        "price_per_sqm": round(amount / area) if amount and area else None,
        "kind": kind,
        "address": addr,
        "house_number": house_number_of(addr),
        "gush": g, "helka": h, "sub_parcel": tat,
        "gush_raw": gush_raw,
        "project": pick(lc, "project"),
        "year_built": parse_number(pick(lc, "yearbuilt")),
        "building_floors": parse_number(pick(lc, "floors")),
        "key": pick(lc, "key"),
    }


def is_first_hand(deal):
    text = f"{deal.get('kind') or ''} {deal.get('project') or ''}"
    return any(m in text for m in FIRST_HAND_MARKERS)


def is_non_residential(deal):
    return any(m in (deal.get("kind") or "") for m in NON_RESIDENTIAL_MARKERS)


def unit_key(deal):
    """Identity of the physical apartment, best available."""
    if deal.get("sub_parcel"):
        return f"tat:{deal['gush']}-{deal['helka']}-{deal['sub_parcel']}"
    floor = deal.get("floor")
    rooms = deal.get("rooms")
    area = deal.get("area_sqm")
    if floor is not None or rooms is not None or area is not None:
        return f"fra:{deal.get('house_number')}|{floor}|{rooms}|{round(area) if area else None}"
    return f"key:{deal.get('key')}"


# ------------------------------- fetching ----------------------------------

def resolve_address(query):
    """Address / gush-helka free text → the locator object the deals endpoint wants."""
    res = post_json(QUERY_URL, {"Query": query})
    if not res or not isinstance(res, dict):
        raise RuntimeError(f"could not resolve '{query}' (empty response)")
    lc = lower_keys(res)
    if not (lc.get("objectid") or lc.get("desclayerid")):
        raise RuntimeError(f"could not resolve '{query}': {json.dumps(res, ensure_ascii=False)[:400]}")
    return res


def fetch_deals(locator, max_pages=25, sleep=1.2, raw_sink=None):
    """Page through GetAssestAndDeals for a resolved locator."""
    out = []
    for page in range(1, max_pages + 1):
        payload = dict(locator)
        payload.update({
            "PageNo": page,
            "OrderByFilled": "",
            "OrderByDescending": False,
            "ObjectKey": payload.get("ObjectKey") or "UNIQ_ID",
            "ObjectIDType": payload.get("ObjectIDType") or "text",
        })
        res = post_json(DEALS_URL, payload)
        if raw_sink is not None:
            raw_sink.append({"page": page, "response": res})
        if not res:
            break
        lc = lower_keys(res)
        batch = lc.get("allresults") or lc.get("results") or []
        if not batch:
            break
        out.extend(batch)
        if lc.get("islastpage") is True:
            break
        time.sleep(sleep)
    return out


# ------------------------------- analysis ----------------------------------

def months_between(a, b):
    return max(0.0, (b.year - a.year) * 12 + (b.month - a.month) + (b.day - a.day) / 30.0)


def analyse(deals, permit_units=None, pace_window_months=6, include_resale=False):
    """Scope: the developer's first sale of each apartment. Resale is excluded by
    design (--include-resale overrides) and only ever surfaces as a diagnostic."""
    now = datetime.now()

    units = defaultdict(list)
    for d in deals:
        units[unit_key(d)].append(d)
    for k in units:
        units[k].sort(key=lambda x: x["_dt"] or datetime.min)

    first_hand_units, resale_only_units, resold_units = [], [], []
    for k, ds in units.items():
        fh = [d for d in ds if is_first_hand(d)]
        if fh:
            first_hand_units.append((k, ds, fh[0]))
            if len(ds) > 1:
                resold_units.append(k)
        else:
            resale_only_units.append((k, ds))

    fh_dated = sorted([d for _, _, d in first_hand_units if d["_dt"]],
                      key=lambda x: x["_dt"])

    # Sales pace over the trailing window of first-hand deals.
    pace, pace_basis = None, None
    if fh_dated:
        last = fh_dated[-1]["_dt"]
        window_start_idx = 0
        for i, d in enumerate(fh_dated):
            if months_between(d["_dt"], last) <= pace_window_months:
                window_start_idx = i
                break
        window = fh_dated[window_start_idx:]
        span = max(1.0, months_between(window[0]["_dt"], last))
        pace = round(len(window) / span, 2)
        pace_basis = {
            "deals_in_window": len(window),
            "window_months": round(span, 1),
            "window_from": window[0]["_dt"].strftime("%Y-%m"),
            "window_to": last.strftime("%Y-%m"),
            "data_staleness_months": round(months_between(last, now), 1),
        }

    sold_first_hand = len(first_hand_units)
    resale_deal_count = (sum(len(ds) for _, ds in resale_only_units)
                         + sum(len(units[k]) - 1 for k in resold_units))
    result = {
        "units_sold_first_hand": sold_first_hand,
        "first_sale_deals": len(fh_dated),
        "first_deal": fh_dated[0]["_dt"].strftime("%Y-%m-%d") if fh_dated else None,
        "last_deal": fh_dated[-1]["_dt"].strftime("%Y-%m-%d") if fh_dated else None,
        "sales_pace_units_per_month": pace,
        "pace_basis": pace_basis,
    }

    if permit_units:
        remaining = permit_units - sold_first_hand
        result["permit_units"] = permit_units
        result["remaining_units"] = remaining
        result["absorption_pct"] = round(100.0 * sold_first_hand / permit_units, 1)
        result["over_permit"] = remaining < 0
        if pace and pace > 0 and remaining > 0:
            months = remaining / pace
            result["months_to_sellout"] = round(months, 1)
            m = now.month + int(round(months))
            result["projected_sellout"] = f"{((m - 1) % 12) + 1:02d}/{now.year + (m - 1) // 12}"
        elif remaining <= 0:
            result["months_to_sellout"] = 0
            result["projected_sellout"] = "מלאי מוצה"

    # Breakdowns — first-hand only, so "sold" means the developer sold it.
    by_rooms, by_floor, prices = Counter(), Counter(), []
    for _, _, d in first_hand_units:
        by_rooms[str(d["rooms"]) if d["rooms"] is not None else "לא ידוע"] += 1
        by_floor[str(d["floor"]) if d["floor"] is not None else "לא ידוע"] += 1
        if d["price_per_sqm"]:
            prices.append(d["price_per_sqm"])

    def sortable(k):
        try:
            return (0, float(k))
        except ValueError:
            return (1, 0.0)

    result["by_rooms"] = {k: by_rooms[k] for k in sorted(by_rooms, key=sortable)}
    result["by_floor"] = {k: by_floor[k] for k in sorted(by_floor, key=sortable)}

    if prices:
        prices.sort()
        result["price_per_sqm"] = {
            "min": prices[0],
            "median": prices[len(prices) // 2],
            "max": prices[-1],
            "avg": round(sum(prices) / len(prices)),
            "n": len(prices),
        }

    # Monthly first-sale curve, for the report chart.
    monthly = Counter()
    for d in fh_dated:
        monthly[d["_dt"].strftime("%Y-%m")] += 1
    result["monthly_first_hand"] = dict(sorted(monthly.items()))

    # The deal list IS the first-sale list: one row per apartment, the developer's sale.
    reported = [d for _, _, d in first_hand_units] if not include_resale else deals
    result["deals"] = [
        {k: v for k, v in d.items() if not k.startswith("_")}
        for d in sorted(reported, key=lambda x: x["_dt"] or datetime.min, reverse=True)
    ]

    # Resale is out of scope by design — kept only as a data-quality signal, never
    # as a headline number, and never mixed into anything above.
    result["resale_diagnostics"] = {
        "resale_deals_ignored": resale_deal_count,
        "units_resold_after_first_sale": len(resold_units),
        "units_with_deals_but_no_identified_contractor_sale": len(resale_only_units),
    }

    warnings = []
    if resale_only_units:
        warnings.append(
            f"{len(resale_only_units)} יחידות עם עסקאות אך ללא עסקת 'מכירת קבלן' מזוהה — "
            "ייתכן שמכירת הקבלן דווחה תחת תיאור אחר, ולכן ספירת המכירות עלולה להיות חסרה. "
            "בדוק את excluded_deals עם reason=resale."
        )
    if sold_first_hand == 0 and deals:
        warnings.append(
            "לא זוהתה אף עסקת 'מכירת קבלן' למרות שקיימות עסקאות בכתובת — "
            "בדוק את שדה DEALNATUREDESCRIPTION בפלט --raw והתאם את FIRST_HAND_MARKERS."
        )
    result["warnings"] = warnings

    # Handed to main() so every ignored resale is still auditable in excluded_deals.
    first_sale_ids = {id(d) for _, _, d in first_hand_units}
    result["_resale_records"] = [d for d in deals if id(d) not in first_sale_ids]
    return result


def auto_from_year(deals):
    """Earliest year with first-hand activity — everything before it belongs to a prior building."""
    years = [d["_dt"].year for d in deals if d["_dt"] and is_first_hand(d)]
    return min(years) if years else None


# --------------------------------- main ------------------------------------

def main():
    p = argparse.ArgumentParser(description="Units sold in a building vs. its building permit")
    p.add_argument("--address", help='e.g. "הרצל 45 רעננה"')
    p.add_argument("--gush")
    p.add_argument("--helka")
    p.add_argument("--house-number", help="keep only deals at this house number")
    p.add_argument("--permit-units", type=int, help="units approved in the building permit")
    p.add_argument("--from-year", default="auto", help="YYYY | auto | none")
    p.add_argument("--max-pages", type=int, default=25)
    p.add_argument("--sleep", type=float, default=1.2, help="seconds between pages (rate limits)")
    p.add_argument("--include-non-residential", action="store_true")
    p.add_argument("--include-resale", action="store_true",
                   help="also report second-hand deals (default: first sale from the "
                        "developer only — resale is out of scope)")
    p.add_argument("--out", help="write result JSON here")
    p.add_argument("--raw", help="dump untouched API responses here")
    args = p.parse_args()

    if not args.address and not (args.gush and args.helka):
        p.error("give --address, or both --gush and --helka")

    query = args.address or f"גוש {args.gush} חלקה {args.helka}"
    raw_sink = [] if args.raw else None

    try:
        locator = resolve_address(query)
        raw_records = fetch_deals(locator, max_pages=args.max_pages,
                                  sleep=args.sleep, raw_sink=raw_sink)
    except Exception as e:
        err = {"ok": False, "query": query, "error": str(e),
               "hint": "Site unreachable or address unresolved. Try a simplified address, "
                       "or look up gush/helka on govmap.gov.il and pass --gush/--helka. "
                       "Do NOT fabricate transaction data."}
        print(json.dumps(err, ensure_ascii=False, indent=2))
        if args.raw and raw_sink is not None:
            with open(args.raw, "w", encoding="utf-8") as f:
                json.dump(raw_sink, f, ensure_ascii=False, indent=2)
        return 1

    if args.raw:
        with open(args.raw, "w", encoding="utf-8") as f:
            json.dump({"locator": locator, "pages": raw_sink}, f, ensure_ascii=False, indent=2)

    unmapped = Counter()
    deals = [normalise(r, unmapped) for r in raw_records]
    excluded = []

    if args.house_number:
        keep, drop = [], []
        for d in deals:
            (keep if d["house_number"] == str(args.house_number) else drop).append(d)
        excluded += [{"reason": "house_number_mismatch", **{k: v for k, v in d.items()
                                                            if not k.startswith("_")}} for d in drop]
        deals = keep

    if not args.include_non_residential:
        keep, drop = [], []
        for d in deals:
            (drop if is_non_residential(d) else keep).append(d)
        excluded += [{"reason": "non_residential", **{k: v for k, v in d.items()
                                                      if not k.startswith("_")}} for d in drop]
        deals = keep

    from_year = None
    if args.from_year == "auto":
        from_year = auto_from_year(deals)
    elif args.from_year != "none":
        from_year = int(args.from_year)
    if from_year:
        keep, drop = [], []
        for d in deals:
            (keep if (d["_dt"] and d["_dt"].year >= from_year) else drop).append(d)
        excluded += [{"reason": f"before_{from_year}", **{k: v for k, v in d.items()
                                                          if not k.startswith("_")}} for d in drop]
        deals = keep

    result = analyse(deals, permit_units=args.permit_units,
                     include_resale=args.include_resale)
    if not args.include_resale:
        excluded += [{"reason": "resale", **{k: v for k, v in d.items()
                                             if not k.startswith("_")}}
                     for d in result["_resale_records"]]
    result.pop("_resale_records", None)

    addresses = Counter(d["address"] for d in deals if d["address"])
    house_numbers = sorted({d["house_number"] for d in deals if d["house_number"]})

    out = {
        "ok": True,
        "query": query,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "מידע נדל\"ן — nadlan.gov.il (עסקאות מדווחות לרשות המסים)",
        "scope": ("מכירה ראשונה מהקבלן לרוכש הראשון בלבד — עסקאות יד שנייה אינן נספרות"
                  if not args.include_resale else "כולל עסקאות יד שנייה"),
        "locator": {k: locator.get(k) for k in ("ObjectID", "DescLayerID", "Gush", "Parcel",
                                                "ResultLable", "Value") if k in locator},
        "filters": {
            "from_year": from_year,
            "house_number": args.house_number,
            "non_residential_excluded": not args.include_non_residential,
            "resale_excluded": not args.include_resale,
        },
        "addresses_seen": dict(addresses.most_common(10)),
        "house_numbers_seen": house_numbers,
        "multi_building_plot": len(house_numbers) > 1,
        "excluded_deals": excluded,
        "unmapped_fields": dict(unmapped.most_common(25)),
        "caveats": [
            "נספרות רק מכירות ראשונות מהקבלן לרוכש הראשון; עסקאות יד שנייה הוצאו מהניתוח.",
            "המספר הוא רצפה, לא מספר מדויק: עסקאות מדווחות לרשות המסים בפיגור של 1–6 חודשים.",
            "יחידות שלא נמכרו אינן בהכרח זמינות — ייתכן שהוקפאו ע\"י היזם או נמכרו וטרם דווחו.",
            "אם החלקה כוללת יותר ממבנה אחד, יש לפצל לפי מספר בית.",
        ],
        **result,
    }
    if not args.permit_units:
        out["caveats"].append("לא סופק מספר יחידות מההיתר — הושמטו אחוז מכירה, יתרה וצפי גמר.")

    js = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
        summary = {k: v for k, v in out.items() if k not in ("deals", "excluded_deals")}
        summary["deals"] = f"<{len(out['deals'])} deals written to {args.out}>"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(js)
    return 0


if __name__ == "__main__":
    sys.exit(main())
