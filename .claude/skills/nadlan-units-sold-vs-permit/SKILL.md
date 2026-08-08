---
name: nadlan-units-sold-vs-permit
description: >
  Compares how many apartments in a new building have already been sold (from the Israeli
  government real-estate transactions site, מידע נדל"ן / nadlan.gov.il) against how many
  housing units were approved for that address in its building permit (היתר בנייה).
  Produces sold-vs-approved counts, absorption %, remaining inventory, a rooms/floor
  breakdown, sales pace and a sell-out forecast — as a Hebrew RTL chat summary plus a
  designed HTML report. Use this skill whenever the user gives a building address and asks
  how many units were sold, how many are left, how a project is selling, or asks to compare
  sales against the permit. Triggers in Hebrew and English alike: "כמה דירות נמכרו ב...",
  "כמה יחידות נמכרו בבניין", "כמה נשאר למכור בפרויקט", "תבדוק קצב מכירות ב...",
  "מול היתר הבנייה", "כמה יחידות אושרו בכתובת", "בדוק את הפרויקט ברחוב X מספר Y",
  "how many units sold at [address]", "check sales pace for this project",
  "sold vs approved units". Always use this skill for these questions — never answer from
  memory, transaction and permit data change constantly and must be looked up live.
compatibility: "Requires bash with python3 (stdlib only) and outbound HTTPS to nadlan.gov.il / govmap.gov.il; WebFetch/WebSearch for the permit side"
---

# Units Sold vs. Building Permit (נמכרו מול היתר)

Answers one question, precisely: **for a given building address, how many apartments have
already been sold, out of how many were approved to be built there?**

Two independent halves — never conflate them:

| Half | Question | Source |
|------|----------|--------|
| **Sold** (מכר) | How many distinct units in this building have registered transactions? | מידע נדל"ן — `nadlan.gov.il` REST API (script does this) |
| **Approved** (היתר) | How many housing units (יח"ד) does the building permit allow? | Municipal permit/GIS portal → מבא"ת → GovMap → ask the user |

---

## Workflow

### Step 0 — Get the address

Need: **street + house number + city**. A street with no house number, or a project name
alone, is not enough — ask for the missing piece before doing anything else.

If the user gives a project name ("פרויקט האגמים"), ask for the street address; the
transaction records are keyed by address and gush/helka, not by marketing name.

### Step 1 — Pull the transactions (the "sold" side)

```bash
python3 ~/.claude/skills/nadlan-units-sold-vs-permit/scripts/building_sales.py \
  --address "הרצל 45 רעננה" \
  --out /tmp/deals.json \
  --raw /tmp/deals_raw.json
```

Useful flags:
- `--permit-units N` — pass the approved count once you have it (Step 2) to get the full comparison computed
- `--gush G --helka H` — search by block/parcel instead of address
- `--from-year YYYY` — ignore deals before this year (default: auto — see "New building detection")
- `--max-pages N` — paging cap (default 25)
- `--raw FILE` — dump untouched API responses

**On the first run against a new address, open `--raw` output and confirm the field names.**
The nadlan API is undocumented and its keys have changed before. The script normalizes
through an alias table (`references/data-sources.md`) and reports
`"unmapped_fields"` in its JSON when it sees keys it does not recognize. If a needed field
is missing, add the alias to `FIELD_ALIASES` in the script rather than hand-parsing.

If the script fails, it exits non-zero with `{"ok": false, "error": ...}`. Fall back in order:
1. Retry with a simplified address (`"הרצל 45 רעננה"` → `"הרצל רעננה"`, then filter with `--house-number 45`)
2. Look up gush/helka on GovMap and rerun with `--gush/--helka`
3. If the error mentions a tunnel/proxy/403, the sandbox is blocking `nadlan.gov.il` — say so
   plainly and offer to run it where egress is open. **Never fabricate transaction data.**

Two diagnostics in the output to read before trusting the numbers:
- `pace_basis.data_staleness_months` — months since the last recorded deal. Large (>6) means
  either the project finished selling or the feed is stale; say which you think it is.
- `multi_building_plot` / `house_numbers_seen` — more than one house number means the parcel
  carries several buildings; rerun with `--house-number` before reporting anything.

### Step 2 — Find the approved unit count (the "permit" side)

Work down this ladder, stopping at the first source that gives a **number of housing units
(מספר יח"ד) tied to this specific address**. Full lookup recipes:
`references/permit-lookup.md`.

1. **The city's own permit lookup / GIS layer** — most authoritative and usually has an
   explicit יח"ד field. Search `"<city> איתור בקשות רישוי והיתרי בנייה"` or `"<city> GIS הנדסה"`.
2. **מבא"ת** (`mavat.iplan.gov.il`) — the תב"ע covering the parcel. Its unit count is for
   the *plan area*, which may cover several buildings. Usable, but label it clearly as
   a plan-level figure, not a permit-level one.
3. **GovMap** (`govmap.gov.il`) — parcel identification and links onward.
4. **Ask the user** — this is the designed fallback, not a failure. Ask plainly:
   > "לא הצלחתי לאתר את מספר היחידות בהיתר עבור הכתובת הזו במקורות הציבוריים. יש לך את מספר
   > היחידות שאושרו, או קובץ ההיתר / נסח / דף מידע שאפשר לקרוא ממנו?"
   If they attach a permit PDF, read it and extract the יח"ד count.

**Always record which source the number came from and how confident it is.** The final
report must state it — a plan-level number and a permit-level number are not the same claim.

### Step 3 — Analyze

The script already computes this; your job is to sanity-check it, not to redo it by hand.

- **Distinct units sold** — deduplicated by תת-חלקה (the third component of the `GUSH`
  field, e.g. `6638-45-**12**`, which *is* the apartment) and falling back to
  (floor, rooms, area) when sub-parcel is absent. A unit that sold twice (developer → buyer,
  then resale) counts as **one sold unit**, not two.
- **First-hand vs. resale** — first-hand ("מכירת קבלן" / new-apartment deals) is what
  measures the developer's absorption. Resales are excluded from absorption but reported
  separately, and their presence is itself a signal (people are already flipping).
- **Absorption** = distinct first-hand units ÷ approved units.
- **Remaining** = approved − distinct first-hand units sold.
- **Rooms / floor breakdown** — which apartment types sold and which are left.
- **Sales pace and forecast** — units per month over the trailing 6 months of first-hand
  deals, and projected months to sell out at that rate.

### Step 4 — Deliver both outputs

The user wants **both**, in this order:

**A. Hebrew RTL chat summary** — short, numbers first. Template:

```
🏗️ <כתובת מלאה> | גוש/חלקה <G/H>

| מדד | ערך |
|---|---|
| יחידות בהיתר | 48 |
| יחידות שנמכרו (מכירת קבלן) | 31 |
| אחוז מכירה | 64.6% |
| נותרו למכירה | 17 |
| עסקאות יד שנייה | 3 |
| קצב מכירה (6 ח' אחרונים) | 2.3 יח'/חודש |
| צפי גמר מלאי | ~7 חודשים (כ-03/2027) |

מקור היתר: <מקור> · מקור מכר: מידע נדל"ן, עודכן <תאריך>
⚠️ <אזהרת פיגור רישום — ראה למטה>
```

Then the rooms/floor breakdown as a second small table, then the caveats.

**B. Designed HTML report as an Artifact.** Use
`assets/report_template.html` as the starting point — it is already RTL, theme-aware and
self-contained. Fill in the `{{...}}` placeholders, delete unused blocks, write it to a
file, then publish with the `Artifact` tool (favicon `🏗️`). Do not load `artifact-design`
for this — the template carries the design. Keep the same file path across updates so the
URL stays stable.

---

## Data honesty rules — these are not optional

Every output, chat and HTML alike, must carry these where relevant:

1. **Registration lag.** nadlan.gov.il shows transactions *reported to רשות המסים*.
   A developer sale typically surfaces **1–6 months** after signing. So the sold figure is a
   **lower bound** — always phrase it as "לפחות X נמכרו", never "בדיוק X".
2. **Never invent a number.** If either half is unavailable, present the half you have and
   say plainly which half is missing and why. A partial answer with a stated gap beats a
   confident wrong one.
3. **Permit ≠ plan.** If the approved count came from a תב"ע rather than the permit itself,
   say so in the same sentence as the number.
4. **Multi-building plots.** One gush/helka can carry several buildings. If the transaction
   addresses show more than one house number, split by house number (`--house-number`) and
   say the plot is shared.
5. **Unsold ≠ available.** Remaining inventory may include units held back by the developer,
   units sold but not yet reported, or non-residential units counted in the permit. Say it.
6. **Deals below/above the building** — parking spots, storage, commercial units and land
   deals sometimes appear in the same feed. The script filters by
   `DEALNATUREDESCRIPTION`; check `"excluded_deals"` in the JSON and mention any surprises.

## New building detection

For a new building, second-hand deals from a *previous* structure on the same parcel
(pre-demolition, common in תמ"א 38 / פינוי-בינוי) will pollute the feed. The script's
default `--from-year auto` picks the year of the earliest cluster of "מכירת קבלן" deals and
ignores everything before it. If the building is a תמ"א 38 addition, say so — the permit
count there covers *added* units and the pre-existing units were never "sold" by a developer.

---

## Reference files

- `references/data-sources.md` — endpoints, request bodies, response field dictionary, aliases, rate limits
- `references/permit-lookup.md` — how to find the approved unit count, per source, with search recipes
- `scripts/building_sales.py` — fetch + dedupe + analyze, emits JSON
- `assets/report_template.html` — RTL HTML report template for the Artifact
