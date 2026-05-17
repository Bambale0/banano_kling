# 2Loop Pastel Grunge Screen Map

## Public Site

- `/` and `/dashboard`: pastel grunge atelier dashboard with GOE snapshot, generation modules, provider status, product references.
- `/creator`: AI Scrap Creator with model cards, prompt composer, format selector, output panel.
- `/catalog` and `/shop`: product archive used as purchase surface and AI reference source.
- `/product/:article`: product detail with image, price, content seed actions and JSON detail drawer.
- `/wallet`: GOE balance, packages and ledger-style usage chart.
- `/history`: generation diary and transaction archive.
- `/admin`: admin overview gated by `SHOP_ADMIN_KEY`.
- Legal/support routes: same shell, lighter paper panel treatment.

## Mini App

- `create`: mobile-first zine creator, flow cards, composer, output diary.
- `wallet`: GOE balance, package cards and usage metrics.
- `history`: generation diary.
- `catalog`: product reference archive.
- `admin`: visible only for Telegram admins.

## UX Notes

- Shared visual language: paper grain, torn-tape bands, soft pink/ice/sage palette, serif editorial headings, square 8px cards.
- Functional language remains product-first: generate, GOE, catalog, history, admin.
- Auth-required state remains explicit in Mini App for non-Telegram opens.
