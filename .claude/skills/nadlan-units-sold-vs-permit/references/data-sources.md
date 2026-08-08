# Data sources — the "sold" side

## Primary: מידע נדל"ן (nadlan.gov.il)

The official Israel Tax Authority / Planning Administration transactions service.
Undocumented internal REST API. `scripts/building_sales.py` wraps it; this file is
what you need when the wrapper breaks.

Base: `https://www.nadlan.gov.il/Nadlan.REST/Main`

### 1. Resolve free text → locator

```
POST /GetDataByQuery
Content-Type: application/json
{"Query": "הרצל 45 רעננה"}
```

Returns a locator object. The fields that matter downstream:

| Field | Meaning |
|---|---|
| `ObjectID` | opaque id of the resolved entity |
| `DescLayerID` | which layer matched (`ADRESS_LAYER`, `PARCEL_ALL_LAYER`, `SETL_MID_POINT`, …) |
| `CurrentLavel` | search level — 2 city, 3 neighborhood, 6 gush/parcel, 7 address (note the typo, it's `Lavel` in the API) |
| `Gush`, `Parcel` | block / parcel when resolved that far |
| `X`, `Y` | ITM coordinates |
| `ResultLable`, `Value` | human-readable echo of what matched — **check this**, the resolver is fuzzy and will happily match a different street |

### 2. Page the transactions

```
POST /GetAssestAndDeals
{ ...the whole locator object..., "PageNo": 1, "OrderByFilled": "",
  "OrderByDescending": false, "ObjectKey": "UNIQ_ID", "ObjectIDType": "text" }
```

Returns `{"AllResults": [...], "IsLastPage": bool, "TotalRecords": n}`.

### 3. Response field dictionary

Names observed in `AllResults[]`. The script maps these through `FIELD_ALIASES` —
**when `--raw` shows a key that is not listed here, add it to the alias table.**

| API key | Meaning | Notes |
|---|---|---|
| `DEALDATETIME` / `DEALDATE` | transaction date | date of *reporting*, close to signing but not identical |
| `DEALAMOUNT` | price in ₪ | comma-formatted string, e.g. `"2,450,000"` |
| `DEALNATUREDESCRIPTION` | deal kind | **the field the whole analysis hinges on** — `"מכירת קבלן"` marks the developer's first sale, which is the only kind in scope. Also carries חניה / מחסן / מסחר rows |
| `ASSETROOMNUM` | rooms | may be `"4"`, `"4.5"` or empty |
| `FLOORNO` | floor | Hebrew strings like `"קרקע"` appear; parsed leniently |
| `DEALNATURE` | area in m² | despite the name, this is the size, not the kind |
| `GUSH` | `gush-helka-tat_helka` | **the third component is the apartment** — the dedup key |
| `FULLADRESS` / `DISPLAYADRESS` | address | note the single-D spelling |
| `NEWPROJECTTEXT` / `PROJECTNAME` | project marketing name | present ⇒ strong first-hand signal |
| `YEARBUILT` / `BUILDINGYEAR` | construction year | |
| `BUILDINGFLOORS` | floors in the building | useful sanity check vs. permit |
| `KEYVALUE` | row id | last-resort dedup key |

### Gotchas

- **Datacenter/cloud IPs get reCAPTCHA.** Verified 2026-08: loading nadlan.gov.il through a
  cloud browser (Apify, datacenter proxy) returns only a reCAPTCHA challenge page, and
  Complot sites time out from foreign datacenter IPs. Run this skill from a regular
  (Israeli, residential/office) connection — the user's own machine. Do not try to defeat
  the CAPTCHA or geo-block with proxy tricks; that's the site telling automation to slow
  down, and the skill must respect it.
- **Rate limiting is aggressive.** Keep `--sleep` at ≥1s. The script backs off exponentially
  on failure; don't defeat that by looping it.
- **TLS**: the host rejects some modern default cipher lists. The script relaxes
  `SECLEVEL` for this reason. If you hit a handshake error from another tool, that's why.
- **Fuzzy resolution**: `GetDataByQuery` will silently resolve to the street or the city
  when the house number doesn't match. Always verify `ResultLable` and check
  `house_numbers_seen` in the output before believing the count.
- **Deals ≠ units.** A unit sold twice appears twice. Dedup by תת-חלקה, keep the earliest
  מכירת קבלן, drop the rest. This is the single most common way to overcount a project's sales.
- **Deal-kind wording is not a stable enum.** `DEALNATUREDESCRIPTION` is free-ish text and the
  developer-sale wording has varied (`מכירת קבלן`, `דירה חדשה`, occasionally just `קבלן`).
  `FIRST_HAND_MARKERS` in the script holds the list; when a building shows deals but zero
  first sales, that list is the first thing to check against the `--raw` output.

## Fallback: GovMap real-estate API

`https://www.govmap.gov.il/api/` — the newer front-end that nadlan increasingly redirects to.

| Endpoint | Use |
|---|---|
| `POST /search-service/autocomplete` | free-text address → coordinates |
| `POST /layers-catalog/entitiesByPoint` | coordinates → gush / helka |
| `GET /real-estate/deals/{point}/{radius}` | deals within a radius of a point |
| `GET /real-estate/street-deals/{polygon_id}` | deals on a street polygon |

Useful when nadlan's address resolver fails: autocomplete the address, get the point,
pull deals in a ~50m radius, then filter by house number. Field names differ from the
nadlan REST shape — inspect before mapping.

## What this data is and is not

It is: **transactions reported to רשות המסים** and published after processing.

It is not: a live inventory feed. A contract signed today typically appears in
1–6 months. Therefore every "sold" count from this source is a **lower bound**.
Developer inventory held off-market, units allocated to owners in תמ"א 38 /
פינוי-בינוי, and unreported sales are all invisible here.
