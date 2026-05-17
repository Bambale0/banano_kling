# 2Loop Pastel Grunge UI Directions

## Goal

Move the public website and Mini App away from dark glass/aurora into a soft pastel grunge system: paper, ice, editorial composition, tactile textures, and clear product workflows.

## Direction 1: Pastel Grunge Studio

Primary recommendation. Soft paper base, ice-blue panels, blush/lilac/mint accents, raw editorial typography, thin dark borders, slightly imperfect texture.

- UX: keep the current dashboard shell, because it exposes backend capabilities clearly.
- UI: square-ish cards, mono labels, large serif/editorial headings, visible GOE economy.
- CSS: `--paper`, `--ice`, `--blush`, `--lilac`, `--mint`, `--ink`, textured pseudo-elements.
- Components: sidebar, command palette, product cards, wallet cards, generator forms.

## Direction 2: Frozen Zine

More experimental and fashion/editorial. Layered cutouts, torn-paper separators, oversized headlines, campaign-like product storytelling.

- UX: best for landing/home and product pages.
- UI: asymmetric grids, large product imagery, magazine captions, hand-stamped badges.
- CSS: heavier grain, rotated tags, mixed serif/sans headings.
- Risk: can become less operational for admin/dashboard screens.

## Direction 3: Gentle Ice Atelier

Calmer and more premium. Ice, porcelain, pale silver, fine borders, minimal texture.

- UX: best for ecommerce catalog and wallet/payment trust.
- UI: soft panels, reserved palette, product photography first.
- CSS: fewer grunge marks, more whitespace, higher contrast for forms.
- Risk: less distinctive than grunge.

## Direction 4: Blush Ops Desk

Operational SaaS with warm pastel accents. Dense, clear, still tactile.

- UX: best for exposing backend modules, admin overview, history and GOE transactions.
- UI: compact tables, paper dashboard panels, colored status tags.
- CSS: high information density, restrained backgrounds, strong focus states.
- Risk: less emotional for brand landing moments.

## Implemented Choice

Implemented Direction 1 as the shared visual system:

- Site: new `/static/landing/css/site.css`.
- Mini App: replaced visual layer in `/miniapp/src/styles.css`.
- HTML theme colors: switched to paper tone where static shell allows it.

## Component Recommendations

- Buttons: use clear text buttons for commands, with high-contrast primary action and ghost secondary action.
- Cards: keep small radius, visible border, paper/ice backgrounds, no nested card styling.
- Forms: pale input fields with dark text, strong focus outline, enough tap height.
- Status: use stamp-like badges for GOE, ready/watch/admin/module labels.
- Product media: keep actual product/reference images, but frame them with paper/ice texture.
- Mini App: keep bottom nav, generator-first flow, and Telegram auth notice; match website palette and typography.
