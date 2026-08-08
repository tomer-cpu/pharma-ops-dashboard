# Finding the approved unit count (מספר יח"ד בהיתר)

There is **no single national public API** that returns "housing units approved at
address X". Permits are issued by local committees (ועדות מקומיות) and published on
each authority's own system. So this is a ladder, not a lookup.

Stop at the first rung that gives a unit count tied to **this address**. Record which
rung you used — the report must state the source and its confidence.

---

## Rung 1 — The city's permit lookup / engineering GIS  ✅ highest confidence

Most authorities publish a map of licensing requests and issued permits, with an
attribute table that includes `מספר יח"ד` / `יחידות דיור`.

**Search recipe** (use WebSearch, then WebFetch the result):
```
"<שם העיר> איתור בקשות רישוי והיתרי בנייה"
"<שם העיר> GIS הנדסה מפה עירונית היתרי בנייה"
"<שם העיר> ועדה מקומית לתכנון ובנייה חיפוש בקשה"
```

Confirmed example — **Tel Aviv-Yafo**:
`https://www.tel-aviv.gov.il/Residents/Construction/Pages/LocatingRequest.aspx`
Searchable by request number, address, or gush/helka; shows all licensing requests
and permits in the city on one map.

Most municipal maps are **ArcGIS Server** underneath, which means the data is
queryable directly. Once you find the city's map viewer, look for its services root
(commonly `.../arcgis/rest/services`) and probe:

```
<root>?f=json                                  # list services
<root>/<Service>/MapServer?f=json              # list layers, find one named היתרי בנייה / רישוי
<root>/<Service>/MapServer/<id>?f=json         # field names — look for יח"ד / YEHIDOT / UNITS
<root>/<Service>/MapServer/<id>/query?where=<addr filter>&outFields=*&f=json
```

Spatial query when you have coordinates instead of a clean address string:
`.../query?geometry=<x>,<y>&geometryType=esriGeometryPoint&inSR=2039&spatialRel=esriSpatialRelIntersects&outFields=*&f=json`
(Israeli municipal layers are usually in ITM / EPSG:2039.)

## Rung 2 — מבא"ת, the planning information site  ⚠️ plan-level, not permit-level

`https://mavat.iplan.gov.il/` — search plans by address, gush/helka, plan number or
number of housing units; the plan detail screen lists approved יח"ד and offers GIS
file downloads.

Also: `https://apps.land.gov.il/TabaSearch/` (RMI plan search) and
`https://www.govmap.gov.il/?app=app07` (איתור תוכניות בניין עיר).

**The catch:** a תב"ע covers a plan *area*, which may span several buildings or a whole
block. Its unit count is an upper bound on any one building, sometimes by a lot.
If you use this rung, the number must be labelled in the output as
*"לפי התב"ע החלה על החלקה — לא לפי ההיתר עצמו"*, and the absorption percentage
presented as approximate.

## Rung 3 — GovMap  ℹ️ identification, not unit counts

`https://www.govmap.gov.il/` — resolve the address to gush/helka and coordinates,
see the parcel outline and which plans apply. Use it to feed Rungs 1 and 2, and to
detect whether the parcel holds one building or several. It does not itself publish
permit unit counts.

## Rung 4 — Ask the user  ✅ designed fallback, not a failure

This rung is expected to be used often. Ask directly and specifically:

> "לא הצלחתי לאתר את מספר היחידות שאושרו בהיתר עבור הכתובת הזו במקורות הציבוריים.
> יש לך את המספר, או קובץ שאפשר לקרוא ממנו — ההיתר עצמו, דף מידע להיתר, נסח טאבו,
> או מפרט מכר של הפרויקט?"

If they attach a document, read it. On a permit, the count appears as
**"מספר יחידות דיור"** or **"יח״ד"** in the permit header table or the שטחים table.
Watch for a permit that lists *added* units (תמ"א 38 / תוספת בנייה) rather than total —
in that case the comparison base is the added units only, and the report must say so.

---

---

## Finding the developer name (שם הקבלן) — required in every report

1. **בעל ההיתר / מבקש ההיתר** — the permit record from Rung 1 above. Legally accurate, and
   you are already there getting the unit count. The attribute is usually
   `בעל ההיתר`, `מבקש`, `שם המבקש` or `YAZAM` in a municipal ArcGIS layer:
   `.../query?where=...&outFields=*&f=json` and read the field list.
2. **The project's own site / listing portals** — yad1 (`yad2.co.il/yad1`), madlan,
   the developer's site. Fast, but marketing: the brand name and the permit holder are
   frequently different legal entities.
3. **רשם הקבלנים** — `https://www.gov.il/he/service/contractors-registry` — confirms the
   registered company, its number and classification once you have a candidate name.
4. **Ask the user.**

**Marketing brand vs. permit holder.** Israeli projects are commonly built by a
single-purpose company owned by a larger group ("X בע\"מ" building for "קבוצת Y").
When the two names differ, report the permit holder as the contractor and mention the
marketing name alongside — do not silently pick one.

**Two developers on one plot.** If the transaction feed carries more than one project
name, the script sets `developer.multiple_projects_in_feed` and warns. Resolve it by
house number *before* naming a contractor — otherwise you credit one builder with
another's sales.

## Cross-checks worth running

Cheap, and they catch a wrong number before it reaches the user:

- **Floors × units per floor.** `BUILDINGFLOORS` from the transaction data × the typical
  units-per-floor implied by the floor breakdown should land near the permit count.
  A factor-of-two gap usually means the permit covers two buildings on the plot.
- **Distinct תת-חלקה count.** If the parcel's sub-parcel numbers run to 40 and the permit
  says 24, the permit is probably for one of several buildings — or includes parking and
  storage sub-parcels, which are registered separately and inflate the count.
- **Deals above the permit count.** If distinct first-hand units exceed approved units,
  something is wrong (usually a shared plot or a resale counted as first-hand). The script
  sets `"over_permit": true` — never present that as "sold out and then some". Investigate.
- **Project name consistency.** If `NEWPROJECTTEXT` shows two different project names,
  the feed is covering more than one building.
