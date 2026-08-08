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

Answers one question, precisely: **for a given building address, how many apartments has
the developer sold to their first buyer, out of how many were approved to be built there?**

**Scope: first sale from the developer only (מכירת קבלן).** Second-hand deals are out of
scope — they are not counted, not listed, and not shown in any table or chart. They exist in
the output in exactly one place, `resale_diagnostics`, and only as a data-quality signal
(see "The resale-only warning" below). Never present a resale figure as a headline.
`--include-resale` exists but is off by default; use it only if the user explicitly asks.

Three things to establish, from three different places — never conflate them:

| What | Question | Source |
|------|----------|--------|
| **Sold** (מכר) | How many apartments has the developer sold to a first buyer? | מידע נדל"ן — `nadlan.gov.il` REST API (script does this) |
| **Approved** (היתר) | How many housing units (יח"ד) does the building permit allow? | Municipal permit/GIS portal → מבא"ת → GovMap → ask the user |
| **Developer** (קבלן/יזם) | Who is building it? | Permit holder (בעל ההיתר) → project site → רשם הקבלנים → ask the user |

**The developer name is a required output field.** Every chat summary and every HTML report
must name the contractor. If it could not be established, print
*"קבלן/יזם: לא אותר"* together with what you tried — never silently drop the line.

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

### Step 2 — Find the approved unit count and permit holder (the "permit" side)

**Try the automated fetch first** — it pulls both the unit count *and* the permit holder
(which doubles as the developer for Step 2b) in one shot:

```bash
python3 ~/.claude/skills/nadlan-units-sold-vs-permit/scripts/permit_lookup.py \
  --city hodhasharon --street "הראשונים" --house 2 --out /tmp/permit.json
```

- `--city <slug>` targets `<slug>.complot.co.il` (the engineering-site product dozens of
  committees run). Don't know the slug? Search `"<city> complot אתר הנדסי"` or
  `"<city> איתור תיק בניין"` and pass the base URL with `--site` instead.
- `--arcgis <services-root>` searches a municipal ArcGIS REST tree as a second strategy.
- `--gush/--helka` work instead of street+house.

Read the output *critically*, not mechanically:
- `ok: true` → take `permit_units`, `permit_holder`, `permit_number`; quote
  `permit_number` in the report as the source. If `confidence` is `low-conflicting`,
  the file has several unit counts (multiple requests/buildings) — inspect `all_rows`
  and pick by the newest issued permit (`הופק היתר`), or ask the user which.
- `ok: false` → `diagnostics` says why. A 403/tunnel error means the environment blocks
  Israeli sites (run it where egress is open). "could not identify search fields" or
  "no tables with permit-like headers" means this committee's site differs from the known
  layout — fall through the manual ladder below. **Extraction is heuristic (Hebrew header
  keywords); a changed site yields a diagnostic, never a silently wrong number.**

Manual ladder when the script comes up empty (full recipes: `references/permit-lookup.md`):

1. **The city's permit lookup / GIS in the browser-ish way** — WebFetch the committee's
   engineering site pages directly and read the permit table yourself.
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

### Step 2b — Find the developer (שם הקבלן) — always

Pass it to the sales script so it lands in the JSON and both outputs:
`--developer "י.נ.ו.ב בניה ופיתוח בע\"מ" --developer-source "בעל ההיתר 2022318, אתר הנדסי הוד השרון"`

Ladder, best first:

1. **`permit_holder` from Step 2's `permit_lookup.py` output** — that IS בעל ההיתר, the
   legally accurate answer, and you already have it. Use it and cite the permit number.
2. **The project's own site or a listing portal** (yad1/yad2, madlan, project microsite).
   Fast and usually right, but it is *marketing* — the marketing brand and the permit holder
   are often different legal entities (a single-project SPV). Label it as such.
3. **רשם הקבלנים** (`gov.il` contractors registry) to confirm the legal entity and its
   classification once you have a name.
4. **Ask the user.**

Two failure modes worth naming, because both silently corrupt the answer:
- **Marketing name ≠ permit holder.** "מגדלי X" may be built by an SPV owned by a larger
  group. When the two differ, report the permit holder and note the marketing name.
- **More than one developer on the plot.** If the feed shows several project names the
  script sets `developer.multiple_projects_in_feed` and warns. Split by house number
  before naming a contractor — otherwise you attribute one builder's sales to another.

### Step 3 — Analyze

The script already computes this; your job is to sanity-check it, not to redo it by hand.

- **Units sold** — the developer's **first sale** of each apartment. Deduplicated by
  תת-חלקה (the third component of the `GUSH` field, e.g. `6638-45-**12**`, which *is* the
  apartment), falling back to (floor, rooms, area) when sub-parcel is absent. Where a unit
  has several deals, only the earliest מכירת קבלן is kept; every later deal is dropped into
  `excluded_deals` with `reason: "resale"`.
- **Absorption** = units sold by the developer ÷ approved units.
- **Remaining** = approved − units sold by the developer.
- **Rooms / floor breakdown** — which apartment types sold and which are left.
- **Sales pace and forecast** — units per month over the trailing 6 months of first-hand
  deals, and projected months to sell out at that rate.

### Step 4 — Deliver both outputs

The user wants **both**, in this order:

**A. Hebrew RTL chat summary** — short, numbers first. Template:

```
🏗️ <כתובת מלאה> | גוש/חלקה <G/H>
קבלן/יזם: <שם הקבלן> (<מקור>)

| מדד | ערך |
|---|---|
| יחידות בהיתר | 48 |
| נמכרו ע"י הקבלן | 31 |
| אחוז מכירה | 64.6% |
| נותרו למכירה | 17 |
| קצב מכירה (6 ח' אחרונים) | 2.3 יח'/חודש |
| צפי גמר מלאי | ~7 חודשים (כ-03/2027) |

היקף: מכירות ראשונות מהקבלן בלבד · מקור היתר: <מקור>
מקור מכר: מידע נדל"ן, עודכן <תאריך>
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

## The resale-only warning — read this before reporting a number

Classification of "first sale" rests entirely on the deal-kind text (`מכירת קבלן` and
friends, in `FIRST_HAND_MARKERS`). So a **unit with deals but no identified contractor
sale** is ambiguous: either the developer's sale was reported under a different description
(⇒ the count is too low), or the unit genuinely only ever changed hands second-hand.

The script counts these in
`resale_diagnostics.units_with_deals_but_no_identified_contractor_sale` and raises a
`warnings` entry. When that count is non-zero:

1. Look at `excluded_deals` with `reason: "resale"` and read their `kind` strings.
2. If a kind clearly denotes a new-apartment sale that the marker list missed, add it to
   `FIRST_HAND_MARKERS` in the script and rerun.
3. If it stays ambiguous, report the count as **"לפחות X"** and tell the user in one line
   that N more units have deals whose type could not be confirmed as a developer sale.

If `units_sold_first_hand` is 0 while deals exist, the classifier is broken for this
building — do not report "0 sold". Inspect `--raw` and fix the markers first.

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
- `scripts/building_sales.py` — the "sold" side: fetch + dedupe + analyze, emits JSON
- `scripts/permit_lookup.py` — the "permit" side: unit count + permit holder from the committee's engineering site (Complot / ArcGIS), emits JSON
- `assets/report_template.html` — RTL HTML report template for the Artifact
- `tests/` — integration, robustness and permit-lookup suites against local mock servers; run them after changing either script
