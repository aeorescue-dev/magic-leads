# P1 — Live trade grid (Angi-inspired discovery)

## Objective

Add an interactive discovery block immediately below the hero that shows **real,
dynamic counts of active opportunities by trade and region/ZIP**, while making
the Magic Leads difference explicit: **exclusive leads, 1-hour priority, owner
phone, no auction, one contractor per address**.

The goal is to capture intent in the first screen: a visitor sees work available
in their own market and can move directly into the week pass.

## UX concept

- Light section directly below the dark hero, so the counts feel like a
  marketplace and the page keeps its light/dark rhythm.
- Location bar: `All cities` + New York / Boston / Dallas / Chicago, each with
  its live count, plus a 5-digit ZIP field.
- Trade grid (2 columns on mobile) with a prominent count, trade label,
  relative-volume bar and a live indicator.
- **Hard floor: only trades with 10+ active opportunities are shown.** Trades
  below 10 are hidden until they cross the threshold.
- Selecting a trade updates a dark summary strip with:
  - selected trade + count + region;
  - `1-hour priority · owner phone`;
  - `No auction · one contractor per address`;
  - primary CTA `See this week's openings`.
- Loading skeletons, empty state for a ZIP with no work, and a retry state.
- Aggregated counts only: no addresses, owner names or phone numbers.

## Data contract

`GET /api/public/trade-grid?city=New%20York&zip=11215`

- Public, rate-limited (`60/minute`), privacy-safe aggregate.
- Window: qualified leads reported in the **last 7 days**.
- Filters: qualified + not junk + not closed/resolved/archived.
- `zip` (5 digits) takes precedence over `city`.
- 60-second in-process cache per `(city, zip)`.
- Response:

```json
{
  "region": { "city": "New York", "zip": null },
  "window_days": 7,
  "total": 3604,
  "trades": { "Roof": 14, "Plumbing": 817, "...": 0 },
  "cities": [
    { "key": "new-york", "label": "New York", "count": 3604 }
  ],
  "updated_at": "2026-11-11T00:46:26+00:00"
}
```

The trade keys are the 16 canonical DB categories; the frontend maps them to the
localized labels already used on the landing.

## Interaction and conversion

- Default city: New York (main market), with all-city and other-city options.
- ZIP submit validates 5 digits; invalid input shows a local error and does not
  fire a request.
- City selection clears ZIP; ZIP selection clears city.
- Trade selection updates the summary and CTA.
- CTA reuses the P0 `openModal` flow (auth → checkout intent).
- Analytics via `data-track`:
  - `p1_city_<city>`
  - `p1_zip_submit`
  - `p1_trade_<trade>`
  - `p1_trade_cta`

## Visual rules

- White/light section, white cards, hairline borders, soft shadows.
- Counts and labels in graphite (`#0B1220`) and slate gray.
- Emerald reserved for the primary CTA, the selected-card border, the live dot
  and the small exclusivity badge.
- No colored title gradients.

## Localization

New keys under `landing.p1*` in EN/PT/ES: kicker, title, subtitle, city/ZIP
labels, active/last-7-days, exclusivity, CTA, loading, error, empty, note.

## Final decisions (approved)

1. **Position:** keep the grid directly below the hero.

**Copy (approved direction):** title “These are real clients waiting for your
call right now.” / “Estes são os clientes reais agora aguardando o seu
contato.”; subtitle “Qualified jobs updated just now!” / “Obras qualificadas
atualizadas agora há pouco!”.
2. **ZIP filter:** hide trades below the `10`-opportunity floor always, so only
   "hot" categories remain.
3. **Geography:** city and ZIP only for now; no neighborhood selector.
4. **Checkout:** the clicked trade is shown in auth and sent as optional
   `trade` metadata on new Stripe checkout sessions.
5. **A/B:** evolve the below-hero version first; test a hero-embedded variant
   later.

## Performance and safety

- One aggregate query per request; cached 60s; no lead-level data.
- Endpoint is public but rate-limited and input-validated.
- The checkout endpoint accepts an optional `trade` field; calls without it are
  unchanged.
- The section is client-side only; the hero remains server-rendered.

## Rollout

1. P1 branch `feat/p1-live-trade-grid` on local staging (this prototype).
2. Review counts and layout with the team.
3. Deploy backend endpoint to the staging environment (not production).
4. Merge P1 only after explicit approval; P0 branch remains independently
   deployable.

## Open questions for the next iteration

- A/B test: grid below hero vs. grid inside the hero panel.
- Should the dashboard auto-apply the selected trade after checkout?
- Public preview URL (Vercel preview + staging backend) for outside reviewers.
