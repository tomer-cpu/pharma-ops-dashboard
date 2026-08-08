# -*- coding: utf-8 -*-
"""
End-to-end test of building_sales.py against a local server that speaks the
nadlan.gov.il wire format. Exercises the real code path: resolve -> paged fetch ->
normalise -> filter -> analyse -> JSON out. Only the remote host is substituted.

Scenario — "הרצל 45, רעננה", a real-shaped new project:
  * 24 units approved in the permit
  * 14 developer first sales, spread over 2024-2025, arriving across 2 API pages
  * 1 of those units already flipped (resale)   -> must NOT add to the count
  * 1 unit with a resale but no contractor sale -> must raise the undercount warning
  * parking + storage rows                      -> must be excluded
  * a 2009 deal from the demolished building    -> must be excluded by --from-year auto
  * a deal at house number 47 on the same plot  -> must be excluded by --house-number
"""
import importlib.util, json, subprocess, sys, threading, http.server, socketserver

SKILL = "/root/.claude/skills/nadlan-units-sold-vs-permit/scripts/building_sales.py"

# ---------------------------------------------------------------- fixture data
def d(date, amount, rooms, floor, area, kind, tat, addr="הרצל 45, רעננה"):
    return {"DEALDATETIME": date + "T00:00:00", "DEALAMOUNT": amount,
            "ASSETROOMNUM": rooms, "FLOORNO": floor, "DEALNATURE": area,
            "DEALNATUREDESCRIPTION": kind, "GUSH": f"6638-45-{tat}",
            "FULLADRESS": addr, "NEWPROJECTTEXT": "מגדלי הפארק",
            "YEARBUILT": "2023", "BUILDINGFLOORS": "9", "KEYVALUE": f"K{tat}_{date}"}

FIRST_SALES = [
    ("2024-01-18", "2,290,000", "3", "1", "76", 1),
    ("2024-02-06", "2,380,000", "4", "1", "97", 2),
    ("2024-03-21", "2,410,000", "4", "2", "97", 3),
    ("2024-05-09", "2,880,000", "5", "3", "119", 4),
    ("2024-06-27", "2,340,000", "3", "2", "77", 5),
    ("2024-09-12", "2,520,000", "4", "3", "98", 6),
    ("2024-12-03", "2,610,000", "4", "4", "98", 7),
    ("2025-01-22", "3,020,000", "5", "5", "120", 8),
    ("2025-02-14", "2,480,000", "3", "4", "78", 9),
    ("2025-03-30", "2,690,000", "4", "5", "99", 10),
    ("2025-05-11", "2,750,000", "4", "6", "99", 11),
    ("2025-06-02", "3,280,000", "5", "7", "121", 12),
    ("2025-07-08", "2,830,000", "4", "7", "98", 13),
    ("2025-07-25", "2,560,000", "3", "6", "78", 14),
]
PAGE1 = [d(*s[:5], "מכירת קבלן", s[5]) for s in FIRST_SALES[:8]]
PAGE2 = [d(*s[:5], "מכירת קבלן", s[5]) for s in FIRST_SALES[8:]] + [
    d("2025-06-18", "3,450,000", "5", "3", "119", "דירה בבית קומות", 4),      # flip of unit 4
    d("2025-04-02", "2,700,000", "4", "8", "100", "דירה בבית קומות", 21),     # no contractor sale
    d("2025-03-05", "145,000", "", "-1", "13", "חניה", 90),                   # parking
    d("2025-03-05", "72,000", "", "-1", "7", "מחסן", 91),                     # storage
    d("2009-08-14", "780,000", "3", "1", "68", "דירה בבית קומות", 61),        # old building
    d("2025-05-20", "2,455,000", "4", "2", "96", "מכירת קבלן", 31,
      addr="הרצל 47, רעננה"),                                                 # neighbouring block
]

LOCATOR = {"ObjectID": "OBJ-6638-45", "DescLayerID": "ADRESS_LAYER", "CurrentLavel": 7,
           "Gush": "6638", "Parcel": "45", "ResultLable": "הרצל 45, רעננה",
           "Value": "הרצל 45 רעננה", "X": 187654.0, "Y": 678901.0}

# ---------------------------------------------------------------- mock server
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        if self.path.endswith("/GetDataByQuery"):
            payload = dict(LOCATOR)
        elif self.path.endswith("/GetAssestAndDeals"):
            calls.append(body)
            page = body.get("PageNo", 1)
            if page == 1:
                payload = {"AllResults": PAGE1, "IsLastPage": False, "TotalRecords": 20}
            elif page == 2:
                payload = {"AllResults": PAGE2, "IsLastPage": True, "TotalRecords": 20}
            else:
                payload = {"AllResults": [], "IsLastPage": True}
        else:
            self.send_error(404); return
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

calls = []
srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# ---------------------------------------------------------------- run the tool
spec = importlib.util.spec_from_file_location("bs", SKILL)
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
bs.QUERY_URL = f"http://127.0.0.1:{port}/Nadlan.REST/Main/GetDataByQuery"
bs.DEALS_URL = f"http://127.0.0.1:{port}/Nadlan.REST/Main/GetAssestAndDeals"

OUT = "/tmp/claude-0/-home-user-pharma-ops-dashboard/ea32af02-63a4-5735-8bb1-a62491f20f01/scratchpad/result.json"
sys.argv = ["building_sales.py", "--address", "הרצל 45 רעננה",
            "--house-number", "45", "--permit-units", "24",
            "--developer", "י.נ.ו.ב בניה ופיתוח בע\"מ",
            "--developer-source", "בעל ההיתר, GIS עירוני",
            "--sleep", "0", "--out", OUT,
            "--raw", OUT.replace("result", "raw")]
rc = bs.main()
srv.shutdown()

res = json.load(open(OUT, encoding="utf-8"))

# ---------------------------------------------------------------- assertions
def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")
    if not cond:
        check.failed += 1
check.failed = 0

print("\n=== exit / transport ===")
check("exit code 0", rc == 0, rc)
check("paged until IsLastPage (2 calls, no 3rd)", len(calls) == 2, f"{len(calls)} calls")
check("page numbers 1,2", [c["PageNo"] for c in calls] == [1, 2])
check("locator forwarded to deals endpoint", calls[0].get("ObjectID") == "OBJ-6638-45")
check("ObjectKey defaulted", calls[0].get("ObjectKey") == "UNIQ_ID")

print("\n=== the headline number ===")
check("14 first sales counted", res["units_sold_first_hand"] == 14, res["units_sold_first_hand"])
check("flip did NOT inflate the count", res["units_sold_first_hand"] == 14)
check("permit units carried through", res["permit_units"] == 24)
check("remaining = 24-14 = 10", res["remaining_units"] == 10, res["remaining_units"])
check("absorption 58.3%", res["absorption_pct"] == 58.3, res["absorption_pct"])
check("not over permit", res["over_permit"] is False)

print("\n=== resale is out of scope ===")
check("every reported row is a contractor sale",
      all("קבלן" in r["kind"] for r in res["deals"]), {r["kind"] for r in res["deals"]})
check("one row per apartment (14)", len(res["deals"]) == 14, len(res["deals"]))
check("2 resale deals ignored",
      res["resale_diagnostics"]["resale_deals_ignored"] == 2, res["resale_diagnostics"])
check("flip recorded as diagnostic only",
      res["resale_diagnostics"]["units_resold_after_first_sale"] == 1)
check("undercount warning raised for the unit with no contractor sale",
      any("ללא עסקת" in w for w in res["warnings"]), res["warnings"])
resale_excl = [e for e in res["excluded_deals"] if e["reason"] == "resale"]
check("resale still auditable in excluded_deals", len(resale_excl) == 2, len(resale_excl))

print("\n=== noise filtering ===")
reasons = {}
for e in res["excluded_deals"]:
    reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
check("parking + storage excluded", reasons.get("non_residential") == 2, reasons)
check("2009 pre-demolition deal excluded", reasons.get("before_2024") == 1, reasons)
check("auto from_year found 2024", res["filters"]["from_year"] == 2024)
check("house 47 excluded", reasons.get("house_number_mismatch") == 1, reasons)
check("only house 45 remains", res["house_numbers_seen"] == ["45"], res["house_numbers_seen"])
check("scope stated in output", "יד שנייה" in res["scope"], res["scope"])

print("\n=== developer name (required field) ===")
check("developer present", res["developer"]["name"] == 'י.נ.ו.ב בניה ופיתוח בע"מ', res["developer"]["name"])
check("source recorded", res["developer"]["source"] == "בעל ההיתר, GIS עירוני")
check("confidence high when sourced", res["developer"]["confidence"] == "high")
check("project name captured from feed",
      res["developer"]["project_names_in_feed"] == ["מגדלי הפארק"], res["developer"]["project_names_in_feed"])
check("single project -> no multi-developer warning",
      res["developer"]["multiple_projects_in_feed"] is False)
check("no missing-developer warning", not any("שם הקבלן" in w for w in res["warnings"]))

print("\n=== derived analytics ===")
check("pace computed", res["sales_pace_units_per_month"] > 0, res["sales_pace_units_per_month"])
check("sellout projection present", bool(res.get("projected_sellout")), res.get("projected_sellout"))
check("rooms breakdown sums to 14", sum(res["by_rooms"].values()) == 14, res["by_rooms"])
check("floor breakdown sums to 14", sum(res["by_floor"].values()) == 14, res["by_floor"])
check("price stats over 14 sales", res["price_per_sqm"]["n"] == 14, res["price_per_sqm"])
check("monthly curve sums to 14", sum(res["monthly_first_hand"].values()) == 14)
check("no unmapped fields for a clean payload", res["unmapped_fields"] == {}, res["unmapped_fields"])

print("\n=== key numbers ===")
for k in ("permit_units", "units_sold_first_hand", "absorption_pct", "remaining_units",
          "sales_pace_units_per_month", "months_to_sellout", "projected_sellout",
          "first_deal", "last_deal"):
    print(f"  {k:32} {res.get(k)}")
print(f"  {'by_rooms':32} {res['by_rooms']}")
print(f"  {'price_per_sqm':32} {res['price_per_sqm']}")
print(f"  {'pace_basis':32} {res['pace_basis']}")

print(f"\n{'ALL CHECKS PASSED' if not check.failed else str(check.failed) + ' CHECK(S) FAILED'}")
sys.exit(1 if check.failed else 0)
