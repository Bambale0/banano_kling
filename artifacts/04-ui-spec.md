# UI Specification

## Visual Direction
2Loop Pastel Grunge Atelier: soft paper background, blush/ice/mint/butter accents, editorial serif display type, dotted grain, torn-tape bands and raw zine energy. The UX stays functional: generate, GOE, catalog, history and admin remain first-order actions.

## Layouts by Screen
- Home: pastel atelier shell, command palette trigger, KPI paper scraps, generation console, provider health strip, product-to-content grid.
- Creator: model cards, segmented ratio picker, prompt composer, result panel, quick examples.
- Catalog/Product: searchable grid, product detail drawer-like layout, content prompt seed.
- Admin: KPI cards, chart-like status bands, recent tasks table, JSON drawer/pre block.

## Responsive Rules
Desktop: sidebar + two-column work areas. Tablet: narrower sidebar/top nav. Mobile: stacked panels, 44px+ controls, no horizontal overflow.

## Interaction States
Buttons and inputs need focus-visible states, disabled states, toasts, loading text, empty states, and error copy. Admin/API JSON must render with textContent/pre, not HTML injection.

## Animation Notes
Keep animation minimal: hover elevation, drawer/palette fade, no decorative orb/bokeh backgrounds. Respect stable dimensions for cards/tables.

## Implementation Notes
Use existing static HTML/CSS/JS so production routes keep working. Borrow shadcn patterns conceptually: sidebar, command dialog, data table with drawer, KPI cards, chart blocks, badges. Cards use 8px radius, letter spacing is normalized to 0, and mobile controls keep 44px+ tap targets.
