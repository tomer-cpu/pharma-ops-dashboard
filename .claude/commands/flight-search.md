---
description: Find the best round-trip flights by price, time, and stay-maximization
argument-hint: [destination] [dates/range] [preferences like "morning out / evening back, 2 nights, direct"]
allowed-tools: mcp__Kiwi_com__search-flight
---

# Flight search — stay-maximizer

You are running the user's personal flight-shopping tool. The user's home airport is **TLV (Tel Aviv, Ben Gurion)** unless the request says otherwise. The user cares about three things, in this order:

1. **Maximum time at the destination** — earliest sensible outbound arrival, latest sensible return departure.
2. **Direct flights** unless a stopover buys real value (>25% cheaper or unlocks a much better time window).
3. **Fair price** — not necessarily the cheapest, but priced right for the time-quality it delivers.

## Inputs to extract from `$ARGUMENTS`

- **Destination** (city / IATA). Resolve city names to IATA when clear.
- **Date window**. Accept forms like "next week", "Aug 3–26", "mid-August", "מהאמצע של החודש הבא". Convert to `dd/mm/yyyy` for `departureDate` / `departureDateTo` (today's date is available in context).
- **Trip length**. "2 days later" = `nights_in_dst_from=2, nights_in_dst_to=2`. "Long weekend" = 3. If ambiguous, run 2 and 3 in parallel and compare.
- **Preferred weekdays**. "Mid-week" → outbound Mon/Tue/Wed = `fly_days=1,2,3`, return Wed/Thu/Fri = `ret_fly_days=3,4,5`.
- **Time-of-day windows** (LOCAL times):
  - "Morning out": `dtime_from=5, dtime_to=11`
  - "Evening back": `ret_dtime_from=17, ret_dtime_to=23`
  - "Red-eye ok" → widen accordingly.
- **Stops policy**. Default `max_sector_stopovers=0` (direct). If no direct exists at all, retry with `max_sector_stopovers=1, stopover_to=4`.
- **Passengers / cabin / bags** — pass through only what the user mentioned.
- **Currency** — EUR by default; ILS or USD if the user says so.

## Run strategy — always do these searches in parallel

1. **Primary**: direct-only, exact spec (`sort=quality`).
2. **+1 night comparator**: same filters but `nights_in_dst_from/to = requested+1`. Often a longer stay is cheaper or better-timed — flag it if it dominates.
3. **Fallback**: `max_sector_stopovers=1, stopover_to=4, sort=price` — only used if #1 returns nothing OR to show a "budget alternative" that saves >25%.

If the primary returns zero results, also widen `dtime_*` by ±2 hours and rerun once before giving up.

## Ranking — the "Stay-Maximizer Score"

For each returned itinerary, compute (mentally, per candidate):

- **Stay hours** = `inbound.departureTime − outbound.arrivalTime`, in hours. Higher = better.
- **Price penalty** = `price / stay_hours` (EUR per hour on the ground).
- **Directness bonus**: direct both ways = ✓✓; one stop = ✓; two stops = ✗ (drop unless explicitly requested).
- **Anti-red-eye penalty**: return that lands after 01:00 local costs 8 usable "stay hours" (fatigue tax).
- **Carrier sanity**: prefer scheduled carriers (LY, A3, LH, TK, AF, KL, BA, U2, W6, FR) over unknown/virtual-interline combinations for a short trip.

Sort candidates by `stay_hours / price` (higher is better), then break ties by directness.

## Output — always this shape

Reply in the user's language (Hebrew if they wrote Hebrew). Structure:

### 🥇 Top pick
One itinerary. Give: dates, outbound (carrier + flight # + times), return (same), stops, total price, **hours at destination**, and one sentence of *why* it wins.

### Runner-ups (up to 2)
Compact table:

| # | Depart | Return | Stops | Price | Hours in city | Notes |

### Cheaper alternatives (only if >25% savings)
Same table format. Explicitly state the trade-off (extra stop, red-eye landing, worse time).

### 💡 Better-value option (only if a +1 night trip dominates)
"If you can add one night, Aug 10→13 is €480 with direct flights both ways — €11 cheaper and 22 more hours in the city."

### Booking links
Bulleted list with the `bookingUrl` for each option shown.

### Final line
"Nice trip! ✈️ Fun fact about {destination}: {one short fact}."

## Hard rules

- Never invent prices, times, or flight numbers. Only use what the tool returned.
- Never omit the `bookingUrl` — that's the whole point.
- Never silently drop a filter the user set (bag count, cabin, non-stop). If a filter kills all results, say so and ask before relaxing it.
- Local ISO timestamps from the API are already in the airport's local time — do NOT apply a timezone shift.

Now parse `$ARGUMENTS`, run the parallel searches, and produce the report.
