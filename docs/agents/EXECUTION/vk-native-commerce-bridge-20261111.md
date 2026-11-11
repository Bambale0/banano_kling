# VK Mini App authenticated commerce-read adapter — 2026-11-11

## Source of truth and boundaries

- Read-only native VK endpoint shipped as `tanyavk` #78 to production at `a84324d97a0c5454f8ed7dd4782da2d87b37494c`. The subsequent #79 startup-order hotfix is also live: `1dd2c01e77d236ac98ba99671e2a8aecb9c288a7`. Native text bot Callback API is back and receives `message_new` events and sends `message_reply`.
- New `GET /mini-app/api/account-preview/vk-commerce` in main backend accepts only the **VK bearer session** validated against signed VK launch; ignores query `vk_user_id`, rejects TG bearer. Its own HMAC timestamp signs a fixed loopback-only GET `/internal/v1/miniapp/users/{real_vk_id}/commerce` on port 1777.
- Returns native VK SQLite balance, configured Lava package availability, last ten payment summaries and partner counts/earned RUB. No Telegram user ID, order/invoice IDs or secret credentials. No write to wallets, no fake payment link or unsupported purchase method.
- Shared VK-only discovery screen shows these read-only details in `Мои работы`. If commerce fails, the tasks/trends and native VK balance remain readable with an explicit error. The full seven-tab `MiniAppShell` gate stays intentionally OFF until all ten real native VK operations exist.

## TDD and verification

- RED: commerce route not found (404); missing bridge function import; frontend `Мои работы` lacked partner/payment data.
- GREEN: signed owner, mixed platform denial, forged query ignored; signed loopback headers and response shape, UI native referral/receipt, commerce-failure isolation. TypeScript/ESLint and native tests required.
- Release main adapter only after protected checks, exact SHA live in Docker + VK static export, and HMAC actual state. Its publication does **not** meet issue #451 full financial E2E, because creating an actual Lava invoice and both payment-success+refund paths are still missing from VK Mini App.
