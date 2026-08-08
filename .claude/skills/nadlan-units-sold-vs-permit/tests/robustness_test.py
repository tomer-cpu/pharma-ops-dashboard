# -*- coding: utf-8 -*-
"""Do the two documented failure modes actually surface, instead of producing a
confident wrong number?

  A. Schema drift  — the API renames fields. Must show up in unmapped_fields.
  B. Unknown deal-kind wording — no 'מכירת קבלן' string anywhere. Must NOT report
     "0 sold" quietly; must raise the loud classifier warning.
  C. Fuzzy resolution — the resolver falls back to the whole street, so deals from
     several house numbers arrive. Must set multi_building_plot.
"""
import importlib.util, json
from collections import Counter

spec = importlib.util.spec_from_file_location(
    "bs", "/root/.claude/skills/nadlan-units-sold-vs-permit/scripts/building_sales.py")
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)

fails = []
def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")
    if not cond: fails.append(label)

# --- A. schema drift -------------------------------------------------------
print("\n=== A. the API renames its fields ===")
drifted = [{"DEAL_DATE": "2025-03-01T00:00:00", "PRICE": "2,400,000",
            "ROOMS": "4", "FLOOR": "3", "AREA": "98",
            "ASSETTYPE": "מכירת קבלן", "GUSH": "6638-45-7",
            "ADDRESS": "הרצל 45, רעננה",
            "SETTLEMENT_CODE_NEW_2027": "1234"}]
un = Counter()
nd = [bs.normalise(r, un) for r in drifted]
check("aliases absorb the renames (date/price/rooms/floor/area/kind survive)",
      nd[0]["date"] == "2025-03-01" and nd[0]["amount"] == 2400000
      and nd[0]["rooms"] == 4 and nd[0]["floor"] == 3 and nd[0]["area_sqm"] == 98
      and "קבלן" in nd[0]["kind"],
      {k: nd[0][k] for k in ("date", "amount", "rooms", "floor", "area_sqm", "kind")})
check("genuinely unknown field is reported, not swallowed",
      "settlement_code_new_2027" in un, dict(un))

# --- B. deal-kind wording the marker list does not know --------------------
print("\n=== B. contractor sales written in wording we don't recognise ===")
odd = []
for i in range(6):
    odd.append({"DEALDATETIME": f"2025-0{i+1}-10T00:00:00", "DEALAMOUNT": "2,400,000",
                "ASSETROOMNUM": "4", "FLOORNO": str(i + 1), "DEALNATURE": "98",
                "DEALNATUREDESCRIPTION": "רכישה מיזם",          # unknown wording
                "GUSH": f"6638-45-{i+1}", "FULLADRESS": "הרצל 45, רעננה"})
un2 = Counter()
deals = [bs.normalise(r, un2) for r in odd]
res = bs.analyse(deals, permit_units=24)
check("does not silently report 0 sold as fact", res["units_sold_first_hand"] == 0
      and bool(res["warnings"]), res["warnings"])
check("raises the classifier-broken warning specifically",
      any("FIRST_HAND_MARKERS" in w for w in res["warnings"]), res["warnings"])
check("the 6 deals stay visible as diagnostics",
      res["resale_diagnostics"]["units_with_deals_but_no_identified_contractor_sale"] == 6,
      res["resale_diagnostics"])

print("\n  -> then the documented fix: add the wording to FIRST_HAND_MARKERS")
bs.FIRST_HAND_MARKERS = bs.FIRST_HAND_MARKERS + ("רכישה מיזם",)
res2 = bs.analyse([bs.normalise(r, Counter()) for r in odd], permit_units=24)
check("after the fix the 6 sales are counted", res2["units_sold_first_hand"] == 6,
      res2["units_sold_first_hand"])
check("and the warning clears", not res2["warnings"], res2["warnings"])

# --- C. resolver fell back to the street -----------------------------------
print("\n=== C. resolver matched the street, not the building ===")
street = []
for hn, tat in ((45, 1), (45, 2), (47, 3), (49, 4)):
    street.append({"DEALDATETIME": "2025-04-01T00:00:00", "DEALAMOUNT": "2,400,000",
                   "ASSETROOMNUM": "4", "FLOORNO": "2", "DEALNATURE": "98",
                   "DEALNATUREDESCRIPTION": "מכירת קבלן", "GUSH": f"6638-45-{tat}",
                   "FULLADRESS": f"הרצל {hn}, רעננה"})
sd = [bs.normalise(r, Counter()) for r in street]
hns = sorted({d["house_number"] for d in sd if d["house_number"]})
check("several house numbers detected", len(hns) > 1, hns)
check("multi_building_plot would be flagged", len(hns) > 1)
only45 = [d for d in sd if d["house_number"] == "45"]
check("--house-number narrows to the actual building", len(only45) == 2, len(only45))

print(f"\n{'ALL CHECKS PASSED' if not fails else str(len(fails)) + ' FAILED: ' + str(fails)}")
raise SystemExit(1 if fails else 0)
