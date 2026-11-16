# Admin Astro — full natal chart and city-to-UTC contract

## Data flow

Telegram Mini App -> signed init_data -> server-resolved place_id from GeoNames
SQLite -> trusted latitude/longitude and IANA timezone -> historical UTC/date
-> SHA-256-verified JPL DE440 + MIT openephem 0.5.0 ->
12 Placidus house cusps, ASC/DSC/MC/IC, planetary positions, major aspects.

The client never sends authoritative coords or timezone to the full chart
endpoint. Server checks current Telegram admin rights before and after CPU
work. It returns no birth data logs and makes no user charges or persistence.
No VK endpoints or independent account bypasses. Admin-only toggle stays.

## Operational assets

1. The host holds two independently verified **read-only** artifacts in the
   operator-managed astro-assets directory (not under repo Git history).
   The compose bind is read-only, never download these on a user request.
2. JPL de440.bsp (119799808 bytes). For the 2026-11-16 source snapshot:
   SHA256 a4ce9bf9b3282becc9f4b2ac3cebe03a2ae7599981aabd7265fd8482fff7c4b5.
   Source: https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440.bsp
3. GeoNames generated SQLite 171939 rows, SHA256
   98f6fd9046819ff380a5e0ef24bff4a851a58cbc593290e66c158c11a7fa8350.
   GeoNames CC BY 4.0: https://www.geonames.org/
   Source ZIP SHA256 46a35f52226f34dd56b64d57b4e9bb380a8ad06605354f8095ea9cdc561aba2c.
4. Optional, gitignored .env.astro in production project root sets
   ASTRO_DE440_PATH=/app/astro-assets/de440.bsp,
   ASTRO_DE440_SHA256=<approved digest>,
   ASTRO_PLACES_DB_PATH=/app/astro-assets/geonames-20261116.sqlite3.
   Paths and integrity hash are environment configuration, not hardcoded
   in application logic. Missing, tampered or incompatible artifacts result
   in a sanitised 503 rather than invented facts.
5. Production CI/deploy must use the exact PR merge SHA. Verify
   docker inspect exposes the read-only mount and configured variables
   (without dumping secret env), health=200, direct Python real fixture 12
   objects/12 cusps/ASC/MC, signed admin HTTP and anonymous 401.
   Then confirm GUI in a Telegram admin WebView. Roll back app by one squash
   commit revert; remove optional .env.astro to deactivate.

## Known limitations

- Unknown birth time: no ASC/houses or unreliable Moon, correctly absent.
- Placidus undefined at some high latitudes: explicit 503, no silent
  fallback to Whole Sign; chart validation needed against independent oracle.
- Timezone historic coverage is limited by IANA tzdb; very old offsets can be
  uncertain. GeoNames cities1000 excludes small villages; extend catalog
  without guessing or silent nearest-city fallback.
- This PR implements deterministic chart facts and UI. Long personalized
  interpretations, provider worker checkpoints, consent and optional pricing
  stay in epic #568/#569, **not claimed complete**.
