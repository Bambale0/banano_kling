# Astro year: new personalized forecast instructions — 2026-11-19

- Baseline `tanyapi`: `3a398b5b7b3126786316e559d4d3b368f0f840d5`.
- Owner instruction: standalone annual prognosis, strict selected calendar year (when YYYY), 12 user-facing sections, client-friendly Russian «Вы», interpretation grounded only in verified natal and transit data, no forced page count.
- Preflight: existing year plan v2 has 29 static chapters plus 12 auto-generated monthly prediction chapters and asks for solar/profections/progressions without corresponding year data. `build_transit_snapshots` returns only 12 local-noon first-of-month snapshots with disclaimer that exact aspect dates are not calculated. The input UI/API currently selects `YYYY` only, not an arbitrary rolling 12 months.
- Implementation: retain exact supplied instruction under `docs/astro/year-system-20261119.md` and versioned `services.year.service_instructions`; switch year to 12 sections and balanced minimum 2500 words, no `dynamic_period`, but validate complete 12 snapshots. Archive original year v2 and resolve in-flight jobs by HMAC exact plan fingerprint, both historic and per-click.
- Invariants: no invented aspect dates/retrograde repetitions; 2028 selects January 1—December 31, not solar year. Engine-provided samples are observation points not exact event windows. Solar, natal and other five services untouched. Keep global fact gate and schema. No changes to prices, payment, AI provider, auth, DB or frontend.
- Tests: full owner spec; prompt exact source isolation; year twelve sections; empty/incorrect snapshots failure; signed old job resume; full seven-service complete reports fixture; pytest CI and release gates.
- Remaining limitation: exact aspect-crossing solver and rolling 12-month UI support are not implemented by this prompt update. Do not claim calculated periods or end-to-end paid annual generation without live smoke.
- Rollback: restore year v2 plan, preserve archive and persisted checkpoints.
