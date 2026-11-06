# VK Mini App init handshake — 2026-11-06

## Scope

Fix the VK host splash remaining visible after the static Mini App has loaded.
The baseline is `tanyapi` SHA
`d7f152933d6cc967c246a5a60e82181960be49aa`.

## Evidence

The actual pre-hydration bootstrap from
`frontend/miniapp-v0/app/layout.tsx` was executed in a deterministic VK host
emulator. On the baseline it sent no `VKWebAppInit`, so the emulated native
loader remained visible. The branch contained no executable
`VKWebAppInit`; the existing browser smoke opened the export directly and
therefore did not model the host loader handshake.

## Change

VK launches send the VK Bridge-compatible `VKWebAppInit` transport before
React hydration for web iframe, Android, iOS, and React Native hosts. The
existing Telegram ready/expand path is unchanged.

Regression coverage includes:

- the focused bootstrap test for web, Android, and iOS;
- an explicit assertion that Telegram still emits `web_app_ready` without a
  VK event;
- a production-export browser smoke assertion for the host message.

## Verification and release state

- `node --test scripts/check-vk-init-handshake.mjs`: 3 passed.
- `node --check scripts/check-vk-root-browser.mjs`: passed.
- The edited workflow parses as YAML.
- Full npm lint/build/Playwright execution is left to protected PR CI because
  the managed workspace has no installed project dependencies or permitted
  npm/GitHub network route.

No backend, database, payment, provider, balance, migration, or Telegram
behavior was changed. The work remains a Draft PR only; it is not merged or
deployed. A real signed VK client acceptance check is still required before
calling the user-visible incident fixed.

