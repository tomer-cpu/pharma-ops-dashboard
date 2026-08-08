#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
permit_lookup.py — pull the approved unit count (כמות יח"ד) and the permit holder
(בעל ההיתר) for an address, from the local committee's public engineering site.

Two strategies, tried in order:

  1. complot  — the "אתר הנדסי" product used by dozens of committees at
                <city>.complot.co.il. ASP.NET WebForms: we fetch the search page,
                replay its hidden form state, and heuristically read the result
                tables by their Hebrew column headers.
  2. arcgis   — municipal ArcGIS REST services: walk the services tree, find
                permit/licensing layers, query by address or gush/helka, and read
                unit-count / holder attributes by field alias.

Neither vendor publishes a schema, so extraction is keyword-driven and every run
returns a `diagnostics` trail saying exactly what was tried, what matched and what
did not. When nothing conclusive is found the script says so — it never guesses.

  python3 permit_lookup.py --city hodhasharon --street "הראשונים" --house 2 --out permit.json
  python3 permit_lookup.py --site http://hodhasharon.complot.co.il --gush 6453 --helka 21
  python3 permit_lookup.py --arcgis https://gis.city.muni.il/arcgis/rest/services --street "הראשונים" --house 2

stdlib only.
"""

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# ---- Hebrew header keywords → canonical column meaning ----------------------
UNITS_KEYS   = ("יח\"ד", "יח״ד", "יחידות דיור", "כמות יח", "מספר יח", 'יח"ד')
HOLDER_KEYS  = ("בעל ההיתר", "בעל היתר", "שם המבקש", "מבקש הבקשה", "מבקש", "יזם")
PERMIT_KEYS  = ("מספר היתר", "מס' היתר", "מס היתר", "היתר מס")
REQUEST_KEYS = ("מספר בקשה", "מס' בקשה", "מס בקשה", "בקשה מס")
DATE_KEYS    = ("תאריך היתר", "תאריך הפקה", "תאריך אישור", "תאריך")
STATUS_KEYS  = ("סטטוס", "מצב הבקשה", "שלב")
ADDR_KEYS    = ("כתובת", "רחוב", "מען")
GUSH_KEYS    = ("גוש", "גוש/חלקה", "גוש חלקה")
ESSENCE_KEYS = ("מהות", "תאור הבקשה", "תיאור הבקשה", "מהות הבקשה")

# Form-field name hints on the Complot search page (lowercased substring match).
FORM_STREET_HINTS = ("street", "rechov", "rehov", "rch")
FORM_HOUSE_HINTS  = ("house", "bayit", "bait", "msp", "houseno", "no")
FORM_GUSH_HINTS   = ("gush", "block")
FORM_HELKA_HINTS  = ("helka", "chelka", "parcel")


def _ssl_ctx():
    ctx = ssl.create_default_context()
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def http(url, data=None, timeout=40):
    """GET (data=None) or form-POST. Returns decoded body."""
    headers = {"User-Agent": UA, "Accept-Language": "he-IL,he;q=0.9",
               "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data, encoding="utf-8").encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
        raw = r.read()
    for enc in ("utf-8", "windows-1255", "iso-8859-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------- HTML digestion ---------------------------------

class PageDigest(HTMLParser):
    """Collects <table>s as rows of cell text, and <form> inputs/selects."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._tstack = [], []
        self._cell, self._in_cell = [], False
        self.inputs = {}       # name -> {"type","value"}
        self.selects = {}      # name -> [(value, label), ...]
        self._sel = None
        self._opt = None
        self.form_action = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._tstack.append([])
        elif tag == "tr" and self._tstack:
            self._tstack[-1].append([])
        elif tag in ("td", "th") and self._tstack and self._tstack[-1]:
            self._in_cell, self._cell = True, []
        elif tag == "input" and a.get("name"):
            self.inputs[a["name"]] = {"type": a.get("type", "text"),
                                      "value": a.get("value", "")}
        elif tag == "select" and a.get("name"):
            self._sel = a["name"]
            self.selects[self._sel] = []
        elif tag == "option" and self._sel is not None:
            self._opt = [a.get("value", ""), ""]
        elif tag == "form" and self.form_action is None:
            self.form_action = a.get("action")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            row = self._tstack[-1][-1]
            row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
        elif tag == "table" and self._tstack:
            t = [r for r in self._tstack.pop() if r]
            if t:
                self.tables.append(t)
        elif tag == "select":
            self._sel = None
        elif tag == "option" and self._sel is not None and self._opt:
            self.selects[self._sel].append(tuple(self._opt))
            self._opt = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)
        if self._opt is not None:
            self._opt[1] += data


def digest(html):
    d = PageDigest()
    d.feed(html)
    return d


def header_map(row):
    """Map column index -> canonical meaning for a header row."""
    m = {}
    for i, cell in enumerate(row):
        for canon, keys in (("units", UNITS_KEYS), ("holder", HOLDER_KEYS),
                            ("permit_number", PERMIT_KEYS), ("request_number", REQUEST_KEYS),
                            ("status", STATUS_KEYS), ("address", ADDR_KEYS),
                            ("gush", GUSH_KEYS), ("essence", ESSENCE_KEYS),
                            ("date", DATE_KEYS)):
            if canon not in m.values() and any(k in cell for k in keys):
                m[i] = canon
                break
    return m


def parse_int(v):
    m = re.search(r"\d+", str(v).replace(",", "")) if v is not None else None
    return int(m.group(0)) if m else None


def extract_permit_rows(tables):
    """Find tables whose header row names permit-ish columns; yield row dicts."""
    out, seen_headers = [], []
    for t in tables:
        hm = header_map(t[0])
        # A useful table names at least a units or holder column plus one identifier.
        if not hm or not ({"units", "holder"} & set(hm.values())):
            continue
        seen_headers.append([t[0][i] for i in sorted(hm)])
        for row in t[1:]:
            rec = {"raw_row": row}
            for i, canon in hm.items():
                if i < len(row):
                    rec[canon] = row[i]
            if rec.get("units") is not None:
                rec["units"] = parse_int(rec["units"])
            if any(rec.get(k) for k in ("units", "holder", "permit_number", "request_number")):
                out.append(rec)
    return out, seen_headers


# ----------------------------- strategy: complot -----------------------------

def try_complot(site, street, house, gush, helka, diag):
    search_url = site.rstrip("/") + "/newengine/Pages/buildings2.aspx"
    diag.append(f"complot: GET {search_url}")
    page = digest(http(search_url))

    # Replay the WebForms state and fill whichever inputs look like our fields.
    form = {n: v["value"] for n, v in page.inputs.items()
            if v["type"] in ("hidden", "text") or n.startswith("__")}

    def fill(hints, value):
        if value is None:
            return None
        for name in list(page.inputs) + list(page.selects):
            low = name.lower()
            if any(h in low for h in hints):
                if name in page.selects:   # street may be a <select> of street codes
                    for val, label in page.selects[name]:
                        if value in label:
                            form[name] = val
                            return name
                else:
                    form[name] = value
                    return name
        return None

    hits = [fill(FORM_STREET_HINTS, street), fill(FORM_HOUSE_HINTS, house),
            fill(FORM_GUSH_HINTS, gush), fill(FORM_HELKA_HINTS, helka)]
    hits = [h for h in hits if h]
    diag.append(f"complot: matched form fields {hits}" if hits
                else "complot: could not identify search fields on the form — "
                     "page structure differs from the known Complot layout")
    if not hits:
        return [], []

    # Press the first submit-looking button.
    for n, v in page.inputs.items():
        if v["type"] in ("submit", "image") and n not in form:
            form[n] = v["value"] or "חפש"
            break

    diag.append("complot: POST search form")
    results = digest(http(search_url, data=form))
    rows, headers = extract_permit_rows(results.tables)
    diag.append(f"complot: {len(rows)} candidate rows from headers {headers}"
                if rows else "complot: no tables with permit-like headers in response")
    return rows, headers


# ----------------------------- strategy: arcgis ------------------------------

def try_arcgis(root, street, house, gush, helka, diag, max_layers=40):
    def j(url):
        sep = "&" if "?" in url else "?"
        return json.loads(http(f"{url}{sep}f=json"))

    root = root.rstrip("/")
    diag.append(f"arcgis: walking {root}")
    tree = j(root)
    services = [f"{root}/{s['name'].split('/')[-1]}/{s['type']}"
                for s in tree.get("services", [])]
    for folder in tree.get("folders", []):
        try:
            sub = j(f"{root}/{folder}")
            services += [f"{root}/{folder}/{s['name'].split('/')[-1]}/{s['type']}"
                         for s in sub.get("services", [])]
        except Exception:
            continue

    PERMIT_LAYER_KEYS = ("היתר", "רישוי", "בקשות", "permit", "rishuy", "licens")
    rows, headers, scanned = [], [], 0
    for svc in services:
        try:
            info = j(svc)
        except Exception:
            continue
        for layer in info.get("layers", []):
            if scanned >= max_layers:
                break
            name = str(layer.get("name", ""))
            if not any(k in name.lower() or k in name for k in PERMIT_LAYER_KEYS):
                continue
            scanned += 1
            lurl = f"{svc}/{layer['id']}"
            try:
                meta = j(lurl)
            except Exception:
                continue
            fields = meta.get("fields") or []
            alias = {f["name"]: str(f.get("alias", f["name"])) for f in fields}

            def field_for(keys):
                for fn, al in alias.items():
                    if any(k in al or k in fn for k in keys):
                        return fn
                return None

            f_units, f_holder = field_for(UNITS_KEYS), field_for(HOLDER_KEYS)
            f_addr, f_gush = field_for(ADDR_KEYS), field_for(GUSH_KEYS)
            f_permit = field_for(PERMIT_KEYS)
            if not (f_units or f_holder):
                diag.append(f"arcgis: layer '{name}' has no units/holder-like fields")
                continue

            where = []
            if street and f_addr:
                where.append(f"{f_addr} LIKE '%{street}%'"
                             + (f" AND {f_addr} LIKE '%{house}%'" if house else ""))
            if gush and f_gush:
                where.append(f"{f_gush} LIKE '%{gush}%'")
            if not where:
                diag.append(f"arcgis: layer '{name}' — no address/gush field to filter on")
                continue
            q = (f"{lurl}/query?where={urllib.parse.quote(' OR '.join(where))}"
                 f"&outFields=*&returnGeometry=false")
            try:
                res = json.loads(http(q + "&f=json"))
            except Exception as e:
                diag.append(f"arcgis: query failed on '{name}': {e}")
                continue
            feats = res.get("features", [])
            diag.append(f"arcgis: layer '{name}' → {len(feats)} features")
            for ft in feats:
                at = ft.get("attributes", {})
                rows.append({
                    "units": parse_int(at.get(f_units)) if f_units else None,
                    "holder": at.get(f_holder) if f_holder else None,
                    "permit_number": at.get(f_permit) if f_permit else None,
                    "address": at.get(f_addr) if f_addr else None,
                    "raw_row": at,
                })
            headers.append({"layer": name, "units_field": f_units, "holder_field": f_holder})
    return rows, headers


# --------------------------------- pick best ---------------------------------

def choose_best(rows):
    """Prefer rows that are issued permits with a unit count; newest first."""
    def score(r):
        s = 0
        if r.get("units"):
            s += 4
        if r.get("holder"):
            s += 2
        if r.get("permit_number"):
            s += 2
        st = str(r.get("status") or "")
        if "היתר" in st or "הופק" in st or "אושר" in st:
            s += 1
        return s

    ranked = sorted(rows, key=score, reverse=True)
    best = ranked[0] if ranked and score(ranked[0]) >= 4 else None
    conflict = False
    if best:
        peers = [r for r in ranked if r.get("units") and score(r) == score(best)]
        conflict = len({r["units"] for r in peers}) > 1
    return best, conflict


# ------------------------------------ main -----------------------------------

def main():
    p = argparse.ArgumentParser(description="Fetch permit unit count + permit holder "
                                            "from a committee's public engineering site")
    p.add_argument("--city", help="Complot slug, e.g. hodhasharon → hodhasharon.complot.co.il")
    p.add_argument("--site", help="full engineering-site base URL (overrides --city)")
    p.add_argument("--arcgis", help="ArcGIS REST services root to search as well/instead")
    p.add_argument("--street")
    p.add_argument("--house")
    p.add_argument("--gush")
    p.add_argument("--helka")
    p.add_argument("--out")
    args = p.parse_args()

    if not (args.site or args.city or args.arcgis):
        p.error("give --site, --city or --arcgis")
    if not (args.street or args.gush):
        p.error("give --street (with --house) or --gush/--helka")

    diag, rows, headers = [], [], []
    site = args.site or (f"http://{args.city}.complot.co.il" if args.city else None)

    if site:
        try:
            rows, headers = try_complot(site, args.street, args.house,
                                        args.gush, args.helka, diag)
        except Exception as e:
            diag.append(f"complot: FAILED — {e}")
    if not rows and args.arcgis:
        try:
            rows, headers = try_arcgis(args.arcgis, args.street, args.house,
                                       args.gush, args.helka, diag)
        except Exception as e:
            diag.append(f"arcgis: FAILED — {e}")

    best, conflict = choose_best(rows)
    out = {
        "ok": best is not None,
        "query": {"site": site, "arcgis": args.arcgis, "street": args.street,
                  "house": args.house, "gush": args.gush, "helka": args.helka},
        "permit_units": best.get("units") if best else None,
        "permit_holder": (best.get("holder") or "").strip() or None if best else None,
        "permit_number": best.get("permit_number") if best else None,
        "source": site or args.arcgis,
        "confidence": ("low-conflicting" if conflict else "high") if best else None,
        "all_rows": rows,
        "matched_headers": headers,
        "diagnostics": diag,
    }
    if conflict:
        out.setdefault("warnings", []).append(
            "נמצאו כמה רשומות עם כמות יח\"ד שונה — ייתכן שהתיק כולל כמה בקשות/מבנים. "
            "בחר ידנית מתוך all_rows לפי מספר ההיתר העדכני.")
    if not best:
        out["hint"] = ("לא חולץ מספר יח\"ד. אם diagnostics מראה חסימת רשת — הרץ בסביבה "
                       "פתוחה. אם המבנה שונה — פתח את האתר ידנית (WebFetch) וקרא את "
                       "הטבלה, או שאל את המשתמש. אל תמציא מספר.")

    js = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
    print(js)
    return 0 if best else 1


if __name__ == "__main__":
    sys.exit(main())
