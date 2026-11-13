# VK #451 — shared service cards with native signed actor routing

Status: incremental. This is **not** full services parity; the full ten-domain
VK gateway gate remains OFF.

The VK tab previously showed a standalone placeholder, despite the shared
`ServiceGrid` present in the Telegram `ServicesTab`. This slice renders the
**exact same** `ServiceGrid` component, with capability-based disabled actions.
The existing Telegram callers/handlers and UI are unchanged when no native
capability overrides are passed.

Actual VK behavior:
- Edit photo routes to the native VK Photo tab **only** after signed native
  state confirms a registered, unblocked actor AND the VK public capability
  allows photo generation.
- Animate photo routes to the native VK Video tab **only** after the signed
  native `video_generation_enabled` gate reports true.
- Partners routes to native VK Profile, where the existing authoritative
  native commerce/referral ledger is shown, with no Telegram balance.
- Support uses the **server-verified** VK community ID from the signed login
  profile, never a client-chosen URL/recipient.
- Pinterest AI, prompt-by-photo AI assistant and Avatar remain disabled until
  actual native provider/price/refund contracts exist. No misleading paid
  buttons or arbitrary provider settings.
- Linked Telegram and blocked/unregistered VK actors cannot call the native
  paid service path. A transport failure fails closed and does not fall back
  to Telegram credentials or balances.

Every action above routes through existing native APIs/feature flags. Neither
a payment switch nor any admin policy is changed by this PR.

Full services acceptance still requires native assistant, prompt, avatar,
music, voice, Genjutsu and any other modules listed in #451, plus shared
TabContent and actor-owned task/settlement/refund/delivery E2E.
