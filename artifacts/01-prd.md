# Product Requirements Document

## Goal
Build the public 2Loop web surface as a usable Studio OS that exposes the backend: AI generation, GOE wallet, catalog, history, admin overview, orders, and operational status.

## Target Users
- Creators, coaches, skating schools, SMM specialists.
- 2Loop operators managing products, orders, payments, generation tasks, and analytics.

## Core User Stories
- As a creator, I can choose a generation scenario, enter a prompt, spend GOE, and see the result.
- As a shopper, I can browse products and turn a product into a content prompt.
- As a user, I can see my GOE balance, generation history, and transactions.
- As an operator, I can inspect dashboard metrics, recent tasks, products, orders, and failed areas.

## MVP Scope
- App shell inspired by shadcn dashboard patterns: sidebar, sticky header, KPI cards, charts, tables, drawers, command palette.
- Safe rendering for product/catalog/history/admin data.
- Routes: `/`, `/creator`, `/catalog`, `/product/:id`, `/wallet`, `/history`, `/dashboard`, `/admin`, informational pages.
- Existing backend endpoints only, with graceful empty/loading/error states.

## Out of Scope
- New paid checkout implementation.
- Real provider retry controls.
- New auth model beyond existing admin key/initData behavior.

## Acceptance Criteria
- Existing landing tests keep passing.
- The site loads without a build step.
- User-provided/catalog/backend data is not inserted via unsafe template HTML.
- Contact form posts to `/api/shop/lead`.
- Admin overview uses `/api/shop/admin/overview` and renders JSON safely.
