# VK #451 — recover from a Telegram-only gate in a misrouted VK launch (2026-11-14)

## Evidence / baseline

- Baseline: `tanyapi@7f63fb5a81a85fc13cd9e633f27268874f36b44b`.
- User's iPhone screenshot shows the NEUROMIX Telegram-only login text and widget while attempting to open the VK Mini App.
- Exact copy and card layout match `frontend/miniapp-v0/components/telegram-open-gate.tsx`, which `MiniAppShell` renders only for locked Telegram application state. A correct signed VK launch instead goes through `AccountPlatformEntry` and `VkAccountGate`.
- `https://vk.neuromixbot.com/` was checked read-only on 2026-11-14: HTTP 200; VK build had `vkLaunch = true`; `/revision.txt` returned the baseline SHA. `https://neuromixbot.com/mini-app/revision.txt` returned the same SHA. `/mini-app/api/account-preview/vk-login` on the canonical VK host returned HTTP 303 to `https://vk.com/app54880352_-239915802`. `app.happy-fox.online/mini-app/` was observed serving a static document last modified 2026-09-30, and its corresponding API route returned 404; that is NOT the current NEUROMIX VK host.
- The user's actual WKWebView URL and VK developer-panel launch URL could not be read from the screenshot, so source/domain mismatch or lost VK launch parameters are supported hypotheses, not a proved configuration defect. There is no genuine signed WebView capture yet.

## Scope and security

- Treat a legacy Telegram gate without Telegram credentials as a recoverable launch state rather than forcing an unrelated VK user to sign into Telegram.
- Add a visible **Войти через ВКонтакте** recovery action using the existing same-origin `/mini-app/api/account-preview/vk-login` endpoint and top-level navigation. That server endpoint uses the current configured VK app/community IDs and issues a 303 to the VK platform; the following VK launch is still verified by signature, timestamp and revocable session. Browser-supplied IDs and balances remain untrusted.
- Preserve the normal Telegram Login Widget and flow. Do not infer a VK actor from referrer, user agent or browser state. Never construct an unsigned VK identity.
- `VK_FULL_APP_PARITY_ENABLED`, checkout, video writes, feed comment writes and partial bootstrap flags remain OFF. No prices, provider settings, ledger, schema or secrets changed.

## Test plan and evidence

- Added component regression `telegram-open-gate-vk-recovery.test.tsx`: VK recovery link is available in the locked Telegram UI, points to trusted same-origin API route and navigates the top-level browsing context; Telegram login script remains in place.
- Test file committed before the implementation file (test-first change order). **No local RED run claimed.** GitHub CI on the PR is the mandatory executable verification, including Jest, TypeScript, build and browser regression.
- Post-merge require exact deployed SHA and public link smoke; this change alone cannot fix an incorrect VK developer-panel URL or prove native signed VK acceptance.

## Remaining root-cause and acceptance work

1. Read the actual configured launch URL of VK app `54880352` / community `239915802` with authorized developer access; require canonical `https://vk.neuromixbot.com/`, not TG or stale HappyFox hosting.
2. Capture safely redacted navigation path, build revision and `vk-html-ready` / `vk-react-mounted` / `vk-session-start` / `vk-session-ok` stages for a **real signed** iPhone VK WebView launch (never log signed query, bearer or personal IDs).
3. Verify the VK-only user reaches the native workspace via a signed actor without Telegram. Full seven-tab 10-domain parity remains a separate, uncompleted acceptance of #451.
4. Reopen from the VK app after correction and test Telegram regression. A successful public HTTP 200 alone does not satisfy this.
