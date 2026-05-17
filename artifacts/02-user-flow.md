# UX Flow

## Primary Flow
Open site -> Studio OS home -> choose Create -> select model -> enter prompt -> call `/api/site/generate` -> show result -> save history -> open History.

## Secondary Flows
- Product-to-content: Catalog -> product detail -> Create with prompt seed.
- Wallet: Wallet -> view demo GOE packages -> open creator or history.
- Operator: Admin -> enter key -> load overview -> inspect KPIs/tasks in safe table/drawer.
- Lead: Contact -> submit form -> backend lead endpoint -> success or retry state.

## Screen Map
- `/`: Studio overview, command center, KPIs, provider/product panels.
- `/creator`: generation composer and output drawer.
- `/catalog`: product grid with search, categories, product-to-content actions.
- `/product/:id`: product detail, prompt seed, cart action.
- `/wallet`: GOE packages, balance, economy chart.
- `/history`: generation history and transaction feed.
- `/dashboard` and `/admin`: operator dashboard.

## Navigation
Desktop uses a left app sidebar plus sticky header. Mobile keeps top navigation and converts dense panels into stacked sections.

## State Matrix
| Screen | Empty | Loading | Error | Success |
| --- | --- | --- | --- | --- |
| Home | demo modules/products | skeleton cards | fallback modules | live profile/products |
| Creator | blank composer | generating | toast + retained prompt | result drawer/panel |
| Catalog | no products | product placeholders | demo products | API products |
| History | empty prompt CTA | refresh button busy | toast | cards/tables |
| Admin | key prompt | loading overview | forbidden message | stats/tasks |
