# VK #451: common seven-tab navigation with signed native-domain fallback

Status: **incremental**. This is not the full 10-domain shared `TabContent` release.

## Problem and verified boundary

The old VK-only fallback in `AccountPlatformEntry` rendered three standalone
catalogue switches instead of Telegram Mini App's seven navigation tabs, even
though a signed VK actor could already browse trends/feed, generate native
photos, read native tasks, see its VK wallet/referrals and quote limited video.
Mounting the shared Telegram `AppProvider` before all native handlers exist
would create a more severe bug: some legacy routes rely on Telegram numeric IDs.

## Change

- `AppTabBar` is a reusable presentational export from the very same
  `tab-nav.tsx` used by the common `MiniAppShell`. VK-only users now see
  Studio, Photo, Video, Feed, Trends, Services, Profile (no Motion), matching
  labels, order, icons and appearance. The existing Telegram `TabNav`
  continues to get its state from the unchanged `AppProvider`.
- The VK transition mounts `VkNativeWorkspace`, not a Telegram store.
  `VkStandaloneDiscovery` accepts a native tab-specific surface and
  reuses signed server read endpoints and the owner-scoped generation panel.
  Native profile reads only the native wallet, tasks, payments and referrals.
- Existing VK trend and feed links route to their respective shared tabs,
  never silently open a photo trend for a feed remix.
- Photo/video forms still require existing signed server capability gates;
  if disabled, the real operation is unavailable and no paid request fires.
  Services deliberately show an honest unavailable state rather than
  calling Telegram-owned pricing, generations or payments.
- Optional Telegram linkage and the verified native bot chat link remain
  available. No fake Telegram actor, financial transfer or stateful browser
  session storage is introduced.

## Release gates

The existing `full_vk_adapter()` readiness remains ten-domain and **OFF**
until actual Photo/Video/Trends/Feed/Services/Profile/Payments/Referrals/Tasks
backends are fully wired through `PlatformActor`. This UI navigation slice
does **not** assert parity or approve opening `VK_FULL_APP_PARITY_ENABLED`,
`VK_MINIAPP_VIDEO_WRITES_ENABLED` or `VK_MINIAPP_CHECKOUT_ENABLED`.

Acceptance: frontend TypeScript/static build, VK build at root, native
navigation/read/write-gate regression tests, signed VK WebView smoke after
exact-SHA deployment. An unavailable signed native endpoint must not
be replaced by a Telegram endpoint.

Rollback: revert the task PR; native API flags remain unchanged.
