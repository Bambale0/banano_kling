// Runs before the React/Next bundles. It must not depend on the SDK, CSS or React.
// Recovery is limited to startup; never reload an already mounted generation form.
const basePath = process.env.NEXT_PUBLIC_MINIAPP_BASE_PATH || '/mini-app'
export const STARTUP_RECOVERY_AFTER_MS = 12_000


export const startupRecoveryMarkup = `<aside id="miniapp-startup-recovery" hidden role="alert" style="position:fixed;z-index:9999;left:16px;right:16px;bottom:20px;max-width:480px;margin:0 auto;padding:20px;border-radius:20px;border:1px solid #b58a3a;background:#11151b;color:#f3f3f3;font-family:system-ui,sans-serif;box-shadow:0 8px 40px #0008">
<p style="margin:0 0 8px;font-weight:600">Загрузка приложения прервалась или идёт слишком долго</p>
<p style="margin:0 0 16px;font-size:14px;line-height:1.5">Не все файлы приложения загрузились. Повторите загрузку. Данные входа Telegram и ссылка на работу сохранятся.</p>
<button id="miniapp-startup-retry" type="button" style="width:100%;min-height:44px;padding:10px 16px;border:0;border-radius:12px;background:#e4a338;color:#111;font-size:16px;font-weight:600;cursor:pointer">Повторить загрузку</button>
</aside>`

export const startupRecoveryScript = `
(function () {
  if (window.__BANANO_BOOT_RECOVERY__) return;
  var done = false, shown = false, failedPath = '', timer;
  var base = ${JSON.stringify(basePath)};
  var markup = ${JSON.stringify(startupRecoveryMarkup)};
  function hide() {
    var panel = document.getElementById('miniapp-startup-recovery');
    if (panel) panel.hidden = true;
  }
  function show() {
    if (done) return;
    var panel = document.getElementById('miniapp-startup-recovery');
    if (!panel) {
      if (!document.body) { timer = setTimeout(show, 500); return; }
      // Next's fatal entry-chunk error can replace the whole document body.
      // The recovery UI must survive that path too. Markup is a static literal.
      var root = document.createElement('div');
      root.innerHTML = markup;
      document.body.appendChild(root);
      panel = document.getElementById('miniapp-startup-recovery');
    }
    panel.hidden = false;
    if (shown) return;
    shown = true;
    // Never send the launch URL, hash, initData or referral/user identifiers.
    try {
      fetch(base + '/api/client-log', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, keepalive: true,
        body: JSON.stringify({event: 'startup-assets-incomplete', message: 'before-react', source: failedPath})
      }).catch(function () {});
    } catch (e) {}
  }
  function onResourceError(event) {
    if (done) return;
    var element = event.target;
    if (!element || (element.tagName !== 'SCRIPT' && element.tagName !== 'LINK')) return;
    try {
      var url = new URL(element.src || element.href, location.href);
      if (url.origin !== location.origin || url.pathname.indexOf(base + '/') !== 0) return;
      failedPath = url.pathname;
      // Next owns chunk retries. Do not race it by executing a second script.
    } catch (e) {}
  }
  function retry(event) {
    var element = event.target;
    if (done || !element || element.id !== 'miniapp-startup-retry') return;
    var url = new URL(location.href);
    var launch = window.__BANANO_INITIAL_LAUNCH__;
    // Next may have already consumed the hash before a dependent chunk stalled.
    if (launch && launch.hash) url.hash = launch.hash;
    url.searchParams.set('_boot_reload', String(Date.now()));
    location.replace(url.toString());
  }
  function finish() {
    done = true;
    clearTimeout(timer);
    hide();
    window.removeEventListener('error', onResourceError, true);
    document.removeEventListener('click', retry, true);
  }
  window.__BANANO_BOOT_RECOVERY__ = { done: finish };
  window.addEventListener('error', onResourceError, true);
  // React's event replay may stop bubbling while hydration is blocked.
  document.addEventListener('click', retry, true);
  timer = setTimeout(show, ${STARTUP_RECOVERY_AFTER_MS});
})();
`

declare global {
  interface Window {
    __BANANO_BOOT_RECOVERY__?: { done: () => void }
  }
}
