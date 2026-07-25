---
name: flight-finder
description: >-
  Finds the cheapest flight that a person would actually enjoy taking — filtering out red-eyes,
  pre-dawn departures, and 3am landings BEFORE comparing prices, then picking the cheapest of what
  survives. Use this skill whenever the user wants to find, search, compare, or book flights, or asks
  about airfare, dates to fly, or how to maximize time at a destination. Triggers on English and
  Hebrew alike: "find me a flight to X", "cheapest flights to Athens in October", "I want to fly
  Monday morning and come back Wednesday evening", "מצא לי טיסה", "אני רוצה לטוס ל...", "כמה עולה
  טיסה ל...", "טיסות זולות ל...", "מתי הכי כדאי לטוס". Also use it when the user describes a trip
  in terms of timing rather than price ("two nights midweek", "long weekend", "מקסימום שהות"), or
  asks to monitor/watch fares. Always use this skill for flight requests rather than answering from
  memory — fares and schedules change daily and must be looked up live.
---

# Flight Finder

Find the cheapest flight **that is actually worth taking**.

Most flight search optimizes one number: price. That's why it keeps surfacing the €134 fare that
departs at 04:00 and lands at 06:00 — technically the cheapest, practically two ruined days. This
skill inverts the order of operations: **decide what's tolerable first, then find the cheapest thing
inside that set.**

The user's home airport is **TLV (Tel Aviv, Ben Gurion)** unless they say otherwise.

---

## The core idea: score the human, not the itinerary

An itinerary's departure and arrival times don't hurt anyone. What hurts is **when you have to wake
up** and **when you get home**. Translate every candidate into those numbers first — everything
downstream gets easier and more honest.

```
wake_out   ≈ outbound departure − 3h     (2h airport buffer + 1h to get there)
wake_back  ≈ inbound  departure − 2.5h   (same, but you're already near the airport)
home_time  ≈ inbound  arrival   + 1h     (baggage, passport, drive home)
```

For short hops (TLV↔LCA, TLV↔ATH) shave 30–60 minutes off the buffers; for long-haul or unfamiliar
airports, add some. The exact constant matters far less than doing the translation at all.

**Both wake-ups count.** This is the part that price-sorted search always misses. The classic trap
is a fare that looks fine on both endpoints — departs 23:30, lands 06:00 — until you notice the
return flight leaves the destination at 04:00, meaning you're up at 01:30 on your last day. Nothing
about the itinerary's own timestamps flags that. `wake_back` does.

---

## The civility gate

Sort every candidate into one of three bands. This is a **gate, not a score** — bands don't trade
off against price, they decide who gets to compete on price at all.

| Band | Condition | What it means |
|---|---|---|
| 🟢 **GREEN** | both wake-ups `≥ 05:00` **and** `home_time ≤ 00:30` | A normal day. No recovery needed. |
| 🟡 **AMBER** | either wake-up 03:30–05:00, **or** `home_time` 00:30–02:00 | One rough edge. Survivable for a short trip. |
| 🔴 **RED** | either wake-up `< 03:30`, **or** `home_time > 02:00` | Costs a full day on top of the fare. |

Worked examples, so the bands stay calibrated:

| Itinerary | wake_out | wake_back | home | Band |
|---|---|---|---|---|
| Out 14:50, back 09:55→12:00 | 11:50 | 07:25 | 13:00 | 🟢 |
| Out 08:05, back 17:30→18:30 | 05:05 | 15:00 | 19:30 | 🟢 |
| Out 20:55, back 07:00→09:10 | 17:55 | 04:30 | 10:10 | 🟡 |
| Out 23:30, back 04:00→06:00 | 20:30 | **01:30** | 07:00 | 🔴 |

Note the last row: every individual timestamp looks survivable, and it was the cheapest fare on the
route by €50. The band comes entirely from `wake_back`.

Then apply this order, which is the skill's actual decision rule:

1. **If any GREEN exists → the cheapest GREEN is the recommendation.** Not the cheapest overall.
   Not the best price-per-hour ratio. The cheapest one that doesn't hurt.
2. **Show the cheapest AMBER only if it undercuts the winner by ≥ 25%.** Below that threshold the
   savings don't buy back the discomfort, and offering it just adds noise.
3. **Show RED options only as a labeled warning**, never as a recommendation — and always name the
   specific cost in wake-times and lost days, not a vague "red-eye" tag. "Return departs 04:00 —
   you're up at 01:30 on your last day" lands; "red-eye" doesn't.
4. **If no GREEN exists at all**, say so plainly before presenting AMBER. The user asked for a
   flight, not for a fantasy — but they should know the tradeoff is forced, not chosen.

Among candidates in the same band at the same price, prefer more hours at the destination, then
fewer stops, then a scheduled carrier over an unfamiliar one.

### When the user overrides

If they say "I don't mind a red-eye", "רד-איי זה בסדר", or "cheapest, I don't care" — collapse the
gate and rank on price alone. Say once that you've done so. Their stated preference beats the
default every time; the gate exists to protect people who haven't thought about it, not to argue
with people who have.

---

## Searching

Use `mcp__Kiwi_com__search-flight`. Key parameters:

| Intent | Parameters |
|---|---|
| Date range | `departureDate` + `departureDateTo` (both `dd/mm/yyyy`) |
| Trip length | `nights_in_dst_from` / `nights_in_dst_to` — this turns it into a return search |
| Weekdays | `fly_days` / `ret_fly_days` — comma-separated, `0`=Sunday … `6`=Saturday |
| Time windows | `dtime_from`/`dtime_to`, `ret_dtime_from`/`ret_dtime_to` — local hours 0–23 |
| Direct only | `max_sector_stopovers: 0` |
| Budget cap | `price_to` |
| Specific airlines | `select_airlines` (IATA codes, comma-separated) |

**Run three searches in parallel, always:**

1. **Primary** — the user's exact spec, direct only, `sort: quality`.
2. **Flex-a-night** — identical but `nights_in_dst ± 1`. This regularly finds a *cheaper* fare with
   *more* time at the destination, because weekday fare buckets don't move in step with trip length.
   Worth surfacing every time it wins on both axes.
3. **Relaxed** — `max_sector_stopovers: 1, stopover_to: 4, sort: price`. Used to answer "is there a
   materially cheaper option?" — usually the answer is no, and confirming that is worth the call.

If the primary returns nothing, widen the time windows by ±2 hours and rerun once before reporting
an empty result.

### Reading weekdays correctly

Requests like "Monday morning to Wednesday evening" translate to `fly_days` / `ret_fly_days`, but
**check them against the actual date window first.** A five-day window may only contain one legal
departure day, which quietly collapses the search to a single date pair. Tell the user when that
happens — it explains why they got three results instead of thirty, and it's usually a sign their
window is too tight rather than that the route is expensive.

Sunday is `0`. Israeli work weeks start Sunday, so "midweek" in a Hebrew request usually means
Monday–Wednesday (`1,2,3`), not Tuesday–Thursday.

---

## Things worth noticing and reporting

These come up constantly and each one changes what the user should do:

**All options share one leg.** When every result returns on the same flight, the return is a
fixed constraint, not a choice — the entire price difference lives in the outbound. Say so directly:
it turns a confusing three-way comparison into a simple one. (Real case: three Larnaca options at
€273 / €343 / €347 all flew home on the same 17:30 Cyprus Airways flight. The €70 premium bought 55
minutes.)

**Zero results is information.** An empty return under a price cap means the cap is wrong for that
route, not that the search failed. Report the empty window, state the realistic price level, and
suggest a specific new threshold.

**Seasonality dwarfs everything.** The same route can triple between August and October. When the
date window is wide, a one-line note about which end is cheap is worth more than another itinerary.

**Israeli carrier coverage.** El Al (`LY`) and Israir (`6H`) appear in results normally. **Arkia
(`IZ`) does not surface through this tool** — if the user is asking about Arkia routes (Rhodes,
Batumi, Eilat, some Larnaca), tell them to check `arkia.co.il` directly rather than implying the
search covered it.

**Timestamps are already local.** The API returns local time at each airport. Applying a timezone
shift corrupts every calculation downstream — don't.

---

## Output

Reply in the user's language. Hebrew request → Hebrew answer, RTL, with flight numbers and times
kept LTR so they stay readable.

Lead with the recommendation and the reason it won. Then the alternatives, then the caveats. Someone
skimming should be able to book from the first six lines.

```markdown
# 🥇 <dates> · <price> · <direct/stops>

| | Airline | Flight | Times |
|---|---|---|---|
| Out | <name> | <number> | <FROM hh:mm → TO hh:mm> |
| Back | <name> | <number> | <FROM hh:mm → TO hh:mm> |

**<N> hours at the destination.** Up at <hh:mm> going out, <hh:mm> coming back, home by <hh:mm>.

<One sentence on why this one — usually "cheapest option that doesn't cost you a day".>

🔗 <bookingUrl>
```

Then, as they apply:

- **Runner-ups** — a compact table with dates, times, price, hours at destination, and a one-phrase
  note on what the price difference actually buys.
- **⚠️ Cheaper but costly** — RED options, with the wake-time or home-time named explicitly.
- **💡 Worth knowing** — a flex-a-night option that beats the winner on both price and time, a
  seasonal note, or a collapsed-window explanation.

Every option shown carries its `bookingUrl`. A recommendation the user can't act on isn't one.

Close with a short, genuinely specific fact about the destination — the kind that comes from the
place's own history rather than a travel brochure. It costs one line and it's the difference between
a search result and a recommendation from someone who's been paying attention.

---

## Ground rules

**Only report what the tool returned.** Never fill in a plausible flight number, a price you expect,
or a schedule you remember. Fares change daily; invented specifics are worse than missing ones
because the user can't tell them apart.

**Never silently drop a constraint.** If the user's bag count, cabin, or non-stop requirement kills
every result, say which filter did it and what relaxing it would cost — then let them decide. A
result that quietly ignores what they asked for is worse than no result.

**Name the tradeoff, don't just flag it.** "Lands 02:55" is data. "Lands 02:55 — you're home at 4am
and Thursday is gone" is a decision the user can actually make.
